"""The convergence and manifest-building steps shared by apply, import, init and uninstall."""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from claude_sync import manifest, paths, settings, sync
from claude_sync import mcp as mcp_mod
from claude_sync import skills as skills_mod
from claude_sync.claude_cli import ClaudeCli, ClaudeCliError
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError
from claude_sync.exit_codes import ExitCode

ACCEPT_HINT = "accept with: claude-sync import"
UPSTREAM_KINDS = ("version", "commit")


def command_line(action: sync.Action) -> str:
    return "claude " + shlex.join(action.args)


def question(
    actions: list[sync.Action],
    skill_actions: Sequence[skills_mod.SkillAction] = (),
    mcp_actions: Sequence[mcp_mod.McpAction] = (),
) -> str:
    items = [
        f"  {command_line(a)}  (removes a marketplace: uninstalls its plugins, deletes their data)"
        if a.args[:3] == ("plugin", "marketplace", "remove")
        else f"  {command_line(a)}"
        for a in actions
        if a.confirm
    ]
    items += [f"  {a.description}" for a in [*skill_actions, *mcp_actions] if a.confirm]
    return "These changes need your approval:\n" + "\n".join(items) + "\nContinue?"


def converge(
    profile_dir: Path,
    ctx: Context,
    prune: bool = False,
    cli: ClaudeCli | None = None,
    drift_hint: str = ACCEPT_HINT,
    skills: bool = True,
    mcp: bool = True,
) -> int:
    """Make the plugins, marketplaces, skills and MCP servers of a profile match its manifest.

    `cli` runs the `claude` commands (default: `ClaudeCli(profile_dir)`);
    uninstall passes `ClaudeCli(None)` to rebuild `~/.claude` with
    CLAUDE_CONFIG_DIR unset. `drift_hint` is printed after a version or commit
    that moved upstream. init and uninstall pass `skills=False`: they converge
    plugins only, and `mcp=False` as well (they leave MCP servers alone).

    The skill and MCP plans are built before anything runs, so a refusal of
    `skills.plan` (a real directory in the way, another profile's conflict, a
    dirty clone) or of `mcp.plan` (a reference that does not resolve) stops
    with an error before any change. Prints the dry-run listing, asks one
    confirmation covering the plugin, skill and MCP actions that need one,
    runs the `claude` commands, the skill actions then the MCP commands (a
    failing one raises an error built from its masked form), writes the
    account guide keys, and returns ExitCode.DRIFT when an upstream version or
    commit moved, else ExitCode.OK.
    """
    declared = manifest.load(profile_dir / manifest.MANIFEST_FILE)
    cli = cli or ClaudeCli(profile_dir)
    observed = sync.observe(cli, profile_dir)
    actions = sync.plan(declared, observed, prune)
    skill_actions = (
        skills_mod.plan(declared, skills_mod.observe(profile_dir, declared), prune)
        if skills
        else []
    )
    mcp_actions = mcp_mod.plan(declared, mcp_mod.observe(profile_dir), prune) if mcp else []
    org = declared.account.org_uuid if declared.account else None
    write_guide = org is not None and observed.guide != org
    if ctx.dry_run:
        for action in actions:
            print(f"would run: {command_line(action)}")
        for skill_action in skill_actions:
            print(f"would {skill_action.description}")
        for mcp_action in mcp_actions:
            print(f"would {mcp_action.description}")
        if write_guide:
            print(f"would write forceLoginMethod and forceLoginOrgUUID to {profile_dir}")
        return int(ExitCode.OK)
    needs_approval = any(a.confirm for a in [*actions, *skill_actions, *mcp_actions])
    if needs_approval and not ctx.confirm(question(actions, skill_actions, mcp_actions)):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    for action in actions:
        cli.run(action.args)
    for skill_action in skill_actions:
        skill_action.run()
    for mcp_action in mcp_actions:
        _run_mcp(cli, mcp_action)
    if write_guide:
        settings.apply_guide(profile_dir, org)
    moved = [
        d for d in sync.diff(declared, sync.observe(cli, profile_dir)) if d.kind in UPSTREAM_KINDS
    ]
    if skills:
        moved += [
            d
            for d in skills_mod.diff(declared, skills_mod.observe(profile_dir, declared))
            if d.kind == "skill-tree"
        ]
    if moved:
        for d in moved:
            print(f"{d.kind} {d.subject}: expected {d.expected!r}, found {d.actual!r}")
        print(drift_hint)
        return int(ExitCode.DRIFT)
    return int(ExitCode.OK)


def _scrubbed(text: str, secrets: Sequence[str]) -> str:
    """`text` with each secret, raw or JSON-escaped, replaced by `***` (longest first)."""
    forms = {form for s in secrets if s for form in (s, json.dumps(s)[1:-1])}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "***")
    return text


def _run_mcp(cli: ClaudeCli, action: mcp_mod.McpAction) -> None:
    """Run an MCP command; its failure names the masked form, never the real arguments."""
    try:
        cli.run(action.args)
    except ClaudeCliError as error:
        stderr = _scrubbed(error.stderr.strip(), action.secrets)
        hint = " (run apply again)" if action.args[1] == "add-json" else ""
        raise ClaudeSyncError(f"`{action.shown}` failed: {stderr}{hint}") from None


def _managed_source(source: str) -> str:
    kind, _, rest = source.partition(":")
    return f"path:{paths.display(rest)}" if kind == "path" else source


def state_dir_of(config_dir: Path) -> Path:
    """The directory holding the `.claude.json` of the configuration `config_dir`.

    Without CLAUDE_CONFIG_DIR Claude Code keeps it in the home directory, next
    to `~/.claude` rather than inside; any other directory holds its own.
    """
    home = Path.home()
    return home if paths.key(config_dir) == paths.key(home / ".claude") else config_dir


def build_manifest(
    config_dir: Path,
    account: manifest.Account | None,
    cli: ClaudeCli | None = None,
    previous: manifest.Manifest | None = None,
) -> manifest.Manifest:
    """The manifest of the plugins, managed marketplaces, external skills and
    user-scope MCP servers of `config_dir`.

    `previous` is the manifest being replaced, if any: the skill import keeps
    its refs and trees (`skills.import_skills`) and the MCP import its
    references (`mcp.import_servers`). The MCP servers are read in the
    `.claude.json` of `state_dir_of(config_dir)`. The
    environment variables to export for the references the import made are
    listed on stderr (names only).

    `cli` runs the `claude` commands (default: `ClaudeCli(config_dir)`); init
    passes `ClaudeCli(None)` to read `~/.claude` with CLAUDE_CONFIG_DIR unset.
    A marketplace claude-sync cannot manage is skipped with a warning on stderr,
    and so are its plugins.
    """
    observed = sync.observe(cli or ClaudeCli(config_dir), config_dir)
    markets = []
    for market in observed.marketplaces:
        if market.source is None:
            print(
                f"claude-sync: warning: skipped marketplace {market.name!r} "
                f"({market.kind} source, not managed by claude-sync)",
                file=sys.stderr,
            )
            continue
        markets.append(
            manifest.Marketplace(
                market.name, _managed_source(market.source), market.ref, market.commit
            )
        )
    names = {m.name for m in markets}
    plugins = [
        manifest.Plugin(p.id, p.version, p.enabled)
        for p in observed.plugins
        if p.id.rpartition("@")[2] in names
    ]
    sources, linked = skills_mod.import_skills(config_dir, previous)
    servers, exports = mcp_mod.import_servers(state_dir_of(config_dir), previous)
    if exports:
        print(
            "claude-sync: export these variables in the shell that starts Claude Code:\n"
            + "\n".join(f"  {name}" for name in exports),
            file=sys.stderr,
        )
    return manifest.Manifest(tuple(markets), tuple(plugins), account, sources, linked, servers)
