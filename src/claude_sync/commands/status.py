from __future__ import annotations

import argparse
from dataclasses import asdict

from claude_sync import manifest, skills, sync, target
from claude_sync.claude_cli import ClaudeCli
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", metavar="NAME", help="profile to check (default: current directory)"
    )


def _line(difference: sync.Difference) -> str:
    return (
        f"{difference.kind} {difference.subject}: "
        f"expected {difference.expected!r}, found {difference.actual!r}"
    )


def differences_of(profile: target.Target) -> list[sync.Difference]:
    declared = manifest.load(profile.directory / manifest.MANIFEST_FILE)
    observed = sync.observe(ClaudeCli(profile.directory), profile.directory)
    return sync.diff(declared, observed) + skills.diff(
        declared, skills.observe(profile.directory, declared)
    )


def run(args: argparse.Namespace, ctx: Context) -> int:
    profile = target.resolve_target(args.profile)
    differences = differences_of(profile)
    drift = [d for d in differences if d.drift]
    information = [d for d in differences if not d.drift]
    lines = [f"profile {profile.name}: " + ("drift" if drift else "no drift")]
    lines += [f"  drift: {_line(d)}" for d in drift]
    lines += [f"  info: {_line(d)}" for d in information]
    data = {
        "profile": profile.name,
        "drift": bool(drift),
        "differences": [{**asdict(d), "drift": d.drift} for d in differences],
    }
    ctx.emit(data, "\n".join(lines))
    return int(ExitCode.DRIFT if drift else ExitCode.OK)


COMMAND = Command(
    name="status",
    summary="compare a profile with its manifest",
    description=(
        "Compare profile.toml of a profile with what the claude CLI reports and list\n"
        "each difference: a marketplace or plugin missing or unlisted, another\n"
        "source, ref, commit, plugin version or enabled state, absent or different\n"
        "account guide keys, and a signed-in organization other than org_uuid.\n"
        "Skills are compared too: a skill without its link, a link pointing\n"
        "elsewhere (run claude-sync apply), an unlisted link into the sources\n"
        "directory, a missing or dirty clone, another commit, ref or tree.\n"
        "Marketplaces and skill sources without a recorded commit and unmanaged\n"
        "marketplaces are listed as information, not drift.\n"
        "\n"
        "The profile is --profile NAME, else the profile of the current directory;\n"
        "its directory must exist (claude-sync profile create NAME)."
    ),
    examples=[
        ("claude-sync status", "check the profile of the current directory"),
        ("claude-sync status --profile work", "check the work profile"),
        ("claude-sync status --profile work --json", "print one JSON document, skills included"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE, ExitCode.DRIFT],
    kind="read",
    configure=configure,
    run=run,
)
