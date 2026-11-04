"""Compare a profile with its manifest, and plan the `claude` commands converging it."""

from dataclasses import dataclass
from pathlib import Path

from claude_sync import paths, settings
from claude_sync.claude_cli import ClaudeCli, InstalledMarketplace, InstalledPlugin, command
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, Plugin, source_spec

# Manifest source prefix of each CLI source kind claude-sync manages.
_MANAGED = {"github": "github", "git": "git", "url": "url", "directory": "path"}

# Difference kinds that are information, not drift.
INFORMATION = frozenset({"unpinned", "unmanaged", "skill-unpinned", "mcp-unmanaged"})


@dataclass(frozen=True)
class ObservedMarketplace:
    name: str
    kind: str
    """The CLI's source kind (github, git, url, directory, file, a claude.ai one)."""
    source: str | None
    """The source in manifest form; None when the kind is not managed."""
    ref: str | None
    commit: str | None
    """HEAD of the copy when it is its own git repository."""


@dataclass(frozen=True)
class Observed:
    marketplaces: tuple[ObservedMarketplace, ...]
    plugins: tuple[InstalledPlugin, ...]
    guide: str | None
    """The organization the profile's guide keys point to."""
    signed_in_org: str | None


@dataclass(frozen=True)
class Difference:
    kind: str
    subject: str
    """A marketplace name, a plugin id, or `account`."""
    expected: str | bool | None
    actual: str | bool | None

    @property
    def drift(self) -> bool:
        return self.kind not in INFORMATION


def manifest_source(market: InstalledMarketplace) -> str | None:
    """The manifest form of an installed marketplace's source; None when unmanaged."""
    prefix = _MANAGED.get(market.source)
    return None if prefix is None else f"{prefix}:{market.target}"


def observe(cli: ClaudeCli, profile_dir: Path) -> Observed:
    """What the profile has: marketplaces with their commits, plugins, account."""
    markets = []
    for market in cli.marketplaces():
        source = manifest_source(market)
        pinnable = source is not None and not source.startswith("path:")
        commit = cli.marketplace_commit(market.location) if pinnable else None
        markets.append(ObservedMarketplace(market.name, market.source, source, market.ref, commit))
    return Observed(
        tuple(markets),
        tuple(cli.plugins()),
        settings.guide_of(settings.read(profile_dir)),
        settings.signed_in_org(profile_dir),
    )


def _same_source(declared: str, actual: str | None) -> bool:
    if actual is None:
        return False
    kind, _, rest = declared.partition(":")
    actual_kind, _, actual_rest = actual.partition(":")
    if kind == actual_kind == "path":
        return paths.normalize(rest) == paths.normalize(actual_rest)
    return declared == actual


def diff(manifest: Manifest, observed: Observed) -> list[Difference]:
    differences: list[Difference] = []
    seen = {m.name: m for m in observed.marketplaces}
    declared = {m.name for m in manifest.marketplaces}

    for market in manifest.marketplaces:
        actual = seen.get(market.name)
        if not market.source.startswith("path:") and market.commit is None:
            differences.append(
                Difference("unpinned", market.name, None, actual.commit if actual else None)
            )
        if actual is None:
            differences.append(Difference("missing", market.name, market.source, None))
            continue
        if not _same_source(market.source, actual.source):
            differences.append(Difference("source", market.name, market.source, actual.source))
        if actual.source is None:
            continue
        if market.ref != actual.ref:
            differences.append(Difference("ref", market.name, market.ref, actual.ref))
        if market.commit is not None and market.commit != actual.commit:
            differences.append(Difference("commit", market.name, market.commit, actual.commit))

    for actual in observed.marketplaces:
        if actual.source is None:
            differences.append(Difference("unmanaged", actual.name, None, actual.kind))
        elif actual.name not in declared:
            differences.append(Difference("unlisted", actual.name, None, actual.source))

    unmanaged = {m.name for m in observed.marketplaces if m.source is None}
    installed = {p.id: p for p in observed.plugins}
    declared_ids = {p.id for p in manifest.plugins}
    for plugin in manifest.plugins:
        actual = installed.get(plugin.id)
        if actual is None:
            differences.append(Difference("missing", plugin.id, plugin.version, None))
            continue
        if plugin.version != actual.version:
            differences.append(Difference("version", plugin.id, plugin.version, actual.version))
        if plugin.enabled != actual.enabled:
            differences.append(Difference("enabled", plugin.id, plugin.enabled, actual.enabled))
    for actual in observed.plugins:
        if actual.id not in declared_ids and _market_of(actual.id) not in unmanaged:
            differences.append(Difference("unlisted", actual.id, None, actual.version))

    if manifest.account is not None:
        org = manifest.account.org_uuid
        if observed.guide != org:
            differences.append(Difference("guide", "account", org, observed.guide))
        if observed.signed_in_org is not None and observed.signed_in_org != org:
            differences.append(Difference("org", "account", org, observed.signed_in_org))
    return differences


def _market_of(plugin_id: str) -> str:
    return plugin_id.rpartition("@")[2]


@dataclass(frozen=True)
class Action:
    args: tuple[str, ...]
    """The arguments after `claude`, ready for `ClaudeCli.run`."""
    confirm: bool
    """True for every step of a re-pin or a prune, which need the data-loss confirmation."""


def plan(manifest: Manifest, observed: Observed, prune: bool) -> list[Action]:
    """The `claude` commands converging the profile to the manifest, in order.

    Version and commit differences plan nothing: the CLI cannot choose them.
    Unmanaged marketplaces and their plugins are never touched; a declared
    marketplace whose name an unmanaged one holds raises ClaudeSyncError.
    """
    seen = {m.name: m for m in observed.marketplaces}
    installed = {p.id: p for p in observed.plugins}
    unmanaged = {m.name for m in observed.marketplaces if m.source is None}
    declared = {m.name for m in manifest.marketplaces}
    clashes = sorted(declared & unmanaged)
    if clashes:
        name = clashes[0]
        raise ClaudeSyncError(
            f"marketplace {name!r} is declared, but the profile has a {seen[name].kind} "
            f"marketplace of that name, managed outside claude-sync: remove it or rename "
            f"the declared one"
        )
    repinned = {
        m.name
        for m in manifest.marketplaces
        if m.name in seen
        and (not _same_source(m.source, seen[m.name].source) or m.ref != seen[m.name].ref)
    }

    def action(operation: str, target: str, confirm: bool = False) -> Action:
        return Action(command(operation, target), confirm)

    def install(plugin: Plugin, confirm: bool) -> list[Action]:
        steps = [action("install", plugin.id, confirm)]
        if not plugin.enabled:
            steps.append(action("disable", plugin.id, confirm))
        return steps

    actions = [
        action("add_marketplace", source_spec(m))
        for m in manifest.marketplaces
        if m.name not in seen
    ]
    for market in manifest.marketplaces:
        if market.name in repinned:
            actions.append(action("remove_marketplace", market.name, confirm=True))
            actions.append(action("add_marketplace", source_spec(market), confirm=True))
            for plugin in manifest.plugins:
                if _market_of(plugin.id) == market.name:
                    actions.extend(install(plugin, confirm=True))

    for plugin in manifest.plugins:
        market = _market_of(plugin.id)
        if market in repinned:
            continue
        actual = installed.get(plugin.id)
        if actual is None:
            actions.extend(install(plugin, confirm=False))
        elif actual.enabled != plugin.enabled:
            actions.append(action("enable" if plugin.enabled else "disable", plugin.id))

    if prune:
        declared_ids = {p.id for p in manifest.plugins}
        # Plugins of a removed (re-pinned or unlisted) marketplace go with it.
        kept = declared - repinned
        for actual in observed.plugins:
            if actual.id not in declared_ids and _market_of(actual.id) in kept:
                actions.append(action("uninstall", actual.id, confirm=True))
        for actual in observed.marketplaces:
            if actual.name not in declared and actual.source is not None:
                actions.append(action("remove_marketplace", actual.name, confirm=True))
    return actions
