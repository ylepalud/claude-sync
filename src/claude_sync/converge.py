"""The convergence and manifest-building steps shared by apply, import, init and uninstall."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from claude_sync import manifest, paths, settings, sync
from claude_sync.claude_cli import ClaudeCli
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode

ACCEPT_HINT = "accept with: claude-sync import"
UPSTREAM_KINDS = ("version", "commit")


def command_line(action: sync.Action) -> str:
    return "claude " + shlex.join(action.args)


def question(actions: list[sync.Action]) -> str:
    listing = "\n".join(f"  {command_line(a)}" for a in actions if a.confirm)
    return (
        "Removing a marketplace uninstalls its plugins and deletes their data. "
        f"These commands will run:\n{listing}\nContinue?"
    )


def converge(profile_dir: Path, ctx: Context, prune: bool = False) -> int:
    """Make the plugins and marketplaces of `profile_dir` match its manifest.

    Prints the dry-run listing, asks the confirmation when an action needs one,
    runs the `claude` commands, writes the account guide keys, and returns
    ExitCode.DRIFT when an upstream version or commit moved, else ExitCode.OK.
    """
    declared = manifest.load(profile_dir / manifest.MANIFEST_FILE)
    cli = ClaudeCli(profile_dir)
    observed = sync.observe(cli, profile_dir)
    actions = sync.plan(declared, observed, prune)
    org = declared.account.org_uuid if declared.account else None
    write_guide = org is not None and observed.guide != org
    if ctx.dry_run:
        for action in actions:
            print(f"would run: {command_line(action)}")
        if write_guide:
            print(f"would write forceLoginMethod and forceLoginOrgUUID to {profile_dir}")
        return int(ExitCode.OK)
    if any(a.confirm for a in actions) and not ctx.confirm(question(actions)):
        print("cancelled", file=sys.stderr)
        return int(ExitCode.OK)
    for action in actions:
        cli.run(action.args)
    if write_guide:
        settings.apply_guide(profile_dir, org)
    moved = [
        d for d in sync.diff(declared, sync.observe(cli, profile_dir)) if d.kind in UPSTREAM_KINDS
    ]
    if moved:
        for d in moved:
            print(f"{d.kind} {d.subject}: expected {d.expected!r}, found {d.actual!r}")
        print(ACCEPT_HINT)
        return int(ExitCode.DRIFT)
    return int(ExitCode.OK)


def _managed_source(source: str) -> str:
    kind, _, rest = source.partition(":")
    return f"path:{paths.display(rest)}" if kind == "path" else source


def build_manifest(
    config_dir: Path, account: manifest.Account | None, cli: ClaudeCli | None = None
) -> manifest.Manifest:
    """The manifest of the user-scope plugins and managed marketplaces installed in `config_dir`.

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
    return manifest.Manifest(tuple(markets), tuple(plugins), account)
