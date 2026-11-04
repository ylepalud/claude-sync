from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace

from claude_sync import manifest, paths, tools
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fix",
        action="store_true",
        help="install or upgrade the missing and too old tools that have a recipe",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON document")


@dataclass(frozen=True)
class Row:
    requirement: tools.Requirement
    status: tools.ToolStatus

    @property
    def name(self) -> str:
        return self.requirement.tool.name


def _rows() -> tuple[list[Row], list[tools.Conflict]]:
    manifests = {
        profile: manifest.load(paths.profile_dir(profile) / manifest.MANIFEST_FILE)
        for profile in tools.all_profiles()
    }
    requirements, conflicts = tools.merge(manifests)
    return [Row(r, tools.check(r.tool)) for r in requirements], conflicts


def _data(rows: list[Row], conflicts: list[tools.Conflict]) -> dict:
    return {
        "tools": [
            {
                "name": row.name,
                "status": row.status.status,
                "installed": row.status.installed,
                "required": row.status.required,
                "profiles": list(row.requirement.profiles),
                "recipe": row.requirement.tool.install,
                "path": tools.resolved_path(row.name),
            }
            for row in rows
        ],
        "conflicts": [
            {
                "name": c.name,
                "recipes": [{"profile": p, "recipe": r} for p, r in c.recipes],
            }
            for c in conflicts
        ],
        "ok": _ok(rows, conflicts),
    }


def _ok(rows: list[Row], conflicts: list[tools.Conflict]) -> bool:
    return not conflicts and all(row.status.status == "ok" for row in rows)


def _text(rows: list[Row], conflicts: list[tools.Conflict]) -> str:
    if not rows:
        return "no tools declared"
    lines = []
    for row in rows:
        tool = row.requirement.tool
        lines.append(
            f"{row.status.status:<8} {row.name}  installed {row.status.installed or '-'}"
            f"  required {row.status.required or '-'}"
            f"  by {', '.join(row.requirement.profiles)}"
            f"  recipe {tool.install or '-'}"
            f"  path {tools.resolved_path(row.name) or '-'}"
        )
    for conflict in conflicts:
        recipes = "; ".join(f"{profile} {recipe}" for profile, recipe in conflict.recipes)
        lines.append(f"conflict {conflict.name}: {recipes}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Step:
    row: Row
    argv: list[str]

    @property
    def is_script(self) -> bool:
        return (self.row.requirement.tool.install or "").startswith("script:")

    def shown(self) -> str:
        return shlex.join(self.argv)


def _question(steps: list[Step]) -> str:
    return "These commands will run:\n" + "\n".join(f"  {s.shown()}" for s in steps) + "\nContinue?"


def _run_step(step: Step) -> None:
    result = subprocess.run(step.argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise ClaudeSyncError(
            f"{step.shown()} failed with exit code {result.returncode}: {result.stderr.strip()}"
        )


def _fix(rows: list[Row], ctx: Context, say) -> tuple[bool, list[str]]:
    """Run the fix commands; returns (cancelled or dry run, names of skipped scripts)."""
    steps = [
        Step(row, tools.fix_command(row.requirement.tool.install))
        for row in rows
        if row.status.status != "ok" and row.requirement.tool.install
    ]
    interactive = ctx.stdin_is_tty and not ctx.json
    skipped = [s for s in steps if s.is_script and not interactive]
    if ctx.dry_run and ctx.json:
        ctx.emit(
            {
                "planned": [
                    {"name": s.row.name, "command": s.shown()} for s in steps if s not in skipped
                ],
                "skipped": [s.row.name for s in skipped],
            },
            "",
        )
        return True, []
    if ctx.dry_run:
        for step in steps:
            say(f"would run: {step.shown()}")
        return True, []
    runnable = [s for s in steps if s not in skipped]
    if runnable and ctx.yes:
        scripts = [s for s in runnable if s.is_script]
        if scripts and not replace(ctx, yes=False).confirm(_question(scripts)):
            skipped += scripts
            runnable = [s for s in runnable if s not in scripts]
    elif runnable and not ctx.confirm(_question(runnable)):
        print("cancelled", file=sys.stderr)
        return True, []
    for step in runnable:
        say(f"run: {step.shown()}")
        _run_step(step)
    return False, [s.row.name for s in skipped]


def run(args: argparse.Namespace, ctx: Context) -> int:
    if args.fix and ctx.json and not ctx.yes:
        print("claude-sync: error: doctor --fix --json requires --yes", file=sys.stderr)
        return int(ExitCode.USAGE)
    rows, conflicts = _rows()
    if not args.fix:
        ctx.emit(_data(rows, conflicts), _text(rows, conflicts))
        return int(ExitCode.OK if _ok(rows, conflicts) else ExitCode.DRIFT)
    stream = sys.stderr if ctx.json else sys.stdout

    def say(line: str) -> None:
        print(line, file=stream)

    if not ctx.json:
        say(_text(rows, conflicts))
    stop, skipped = _fix(rows, ctx, say)
    if stop:
        return int(ExitCode.OK)
    rows, conflicts = _rows()
    ctx.emit(_data(rows, conflicts), _text(rows, conflicts))
    for name in skipped:
        say(f"skipped (needs an interactive confirmation): {name}")
    for row in rows:
        if row.status.status == "missing":
            say(f"still missing: {row.name}")
        elif row.status.status == "too-old":
            say(
                f"still too-old: {row.name} {row.status.installed or '?'}, "
                f"found first at {tools.resolved_path(row.name)}"
            )
    return int(ExitCode.OK if _ok(rows, conflicts) else ExitCode.DRIFT)


COMMAND = Command(
    name="doctor",
    summary="check the command-line tools the profiles require",
    description=(
        "Read the [[tool]] tables of every profile, merge them by tool name (the\n"
        "highest minimum version wins; the check command and the install recipe\n"
        "come from the first profile, in name order, that declares them; other\n"
        "different recipes are reported as conflicts), run each check command (no\n"
        "shell, 10 second timeout) and list for each tool its status (ok, missing,\n"
        "too-old), installed and required version, requiring profiles, recipe and\n"
        "resolved path. The installed version is the first dotted number in the\n"
        "output of the check command (default: <name> --version). Exit 0 when\n"
        "every tool is ok and there is no conflict, 4 otherwise.\n"
        "\n"
        "--fix installs or upgrades every missing or too old tool that has a\n"
        "recipe: brew:<formula> (brew install, or brew upgrade when brew lists\n"
        "it), npm:<package> (npm install -g <package>@latest), uv:<package>\n"
        "(uv tool install --upgrade), cargo:<crate> (cargo install --force) or\n"
        "script:<command> (run by /bin/sh -c). It prints every command, managers\n"
        "by absolute path, and asks one confirmation (exit 3 without a terminal\n"
        "and without --yes). A script: recipe always needs its own confirmation on\n"
        "a terminal, even with --yes; without a terminal, and with --json, it is\n"
        "skipped and reported. Nothing to run asks nothing. The commands run in\n"
        "order and stop at the first failure (exit 1, with the command and its\n"
        "error output); doctor then checks again and exits 0 or 4. A tool without\n"
        "a recipe is only reported. --dry-run prints the commands and runs none\n"
        "(exit 0). --fix with --json requires --yes and prints the progress on\n"
        "stderr.\n"
        "\n"
        '--json prints {"tools": [...], "conflicts": [...], "ok": bool}.'
    ),
    examples=[
        ("claude-sync doctor", "list the tools every profile requires"),
        ("claude-sync doctor --json", "the same as one JSON document"),
        ("claude-sync doctor --fix --dry-run", "print the install commands, run none"),
        ("claude-sync doctor --fix", "install or upgrade the tools after one confirmation"),
        (
            "claude-sync doctor --fix --yes",
            "no prompt for managers (a script: recipe still asks on a terminal, else is skipped)",
        ),
    ],
    exit_codes=[
        ExitCode.OK,
        ExitCode.ERROR,
        ExitCode.USAGE,
        ExitCode.CONFIRMATION_REQUIRED,
        ExitCode.DRIFT,
    ],
    kind="mutate",
    configure=configure,
    run=run,
)
