"""The profile manifest: the plugins and marketplaces a profile declares."""

import re
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from claude_sync import fileio, paths
from claude_sync.config import toml_string
from claude_sync.errors import ClaudeSyncError

MANIFEST_FILE = "profile.toml"

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_GITHUB = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


class ManifestError(ClaudeSyncError):
    """The manifest is invalid."""


@dataclass(frozen=True)
class Marketplace:
    name: str
    source: str
    ref: str | None
    commit: str | None


@dataclass(frozen=True)
class Plugin:
    id: str
    version: str
    enabled: bool


@dataclass(frozen=True)
class Account:
    org_uuid: str


@dataclass(frozen=True)
class Manifest:
    marketplaces: tuple[Marketplace, ...]
    plugins: tuple[Plugin, ...]
    account: Account | None


def load(path: Path) -> Manifest:
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise ManifestError(f"{path}: cannot read: {error.strerror}") from error
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ManifestError(f"{path}: invalid TOML: {error}") from error
    return _parse(data, path)


def _tables(data: dict, key: str, fail) -> list[dict]:
    tables = data.get(key, [])
    if not isinstance(tables, list) or not all(isinstance(t, dict) for t in tables):
        raise fail(f"{key!r} must be an array of tables")
    return tables


def _check_keys(table: dict, required: set[str], optional: set[str], label: str, fail) -> None:
    unknown = set(table) - required - optional
    if unknown:
        raise fail(f"unknown key {sorted(unknown)[0]!r} in {label}")
    for field in sorted(required - set(table)):
        raise fail(f"missing field {field!r} in {label}")


def _parse(data: dict, file: Path) -> Manifest:
    def fail(problem: str) -> ManifestError:
        return ManifestError(f"{file}: {problem}")

    unknown = set(data) - {"marketplace", "plugin", "account"}
    if unknown:
        raise fail(f"unknown key {sorted(unknown)[0]!r}")

    marketplaces = []
    names: set[str] = set()
    for table in _tables(data, "marketplace", fail):
        _check_keys(table, {"name", "source"}, {"ref", "commit"}, "a marketplace", fail)
        market = _marketplace(table, fail)
        if market.name in names:
            raise fail(f"duplicate marketplace {market.name!r}")
        names.add(market.name)
        marketplaces.append(market)

    plugins = []
    ids: set[str] = set()
    for table in _tables(data, "plugin", fail):
        _check_keys(table, {"id", "version", "enabled"}, set(), "a plugin", fail)
        plugin = _plugin(table, fail)
        if plugin.id in ids:
            raise fail(f"duplicate plugin {plugin.id!r}")
        ids.add(plugin.id)
        market = plugin.id.rpartition("@")[2]
        if market not in names:
            raise fail(f"plugin {plugin.id!r} uses undeclared marketplace {market!r}")
        plugins.append(plugin)

    account = None
    if "account" in data:
        table = data["account"]
        if not isinstance(table, dict):
            raise fail("'account' must be a table")
        _check_keys(table, {"org_uuid"}, set(), "account", fail)
        account = Account(_uuid(table["org_uuid"], fail))
    return Manifest(tuple(marketplaces), tuple(plugins), account)


def _string(value: object, label: str, fail) -> str:
    if not isinstance(value, str) or not value:
        raise fail(f"{label} must be a non-empty string")
    return value


def _marketplace(table: dict, fail) -> Marketplace:
    name = _string(table["name"], "marketplace name", fail)
    if not _NAME.fullmatch(name):
        raise fail(f"invalid marketplace name {name!r}")
    source = _string(table["source"], f"source of {name!r}", fail)
    kind, _, rest = source.partition(":")
    if kind not in ("github", "git", "url", "path") or not rest:
        raise fail(f"invalid source {source!r} for {name!r} (github:, git:, url: or path:)")
    if kind == "github" and not _GITHUB.fullmatch(rest):
        raise fail(f"invalid source {source!r} for {name!r} (expected github:<owner>/<repo>)")
    ref = table.get("ref")
    if "ref" in table:
        ref = _string(ref, f"ref of {name!r}", fail)
    commit = table.get("commit")
    if "commit" in table:
        if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
            raise fail(f"commit of {name!r} must be 40 lowercase hex characters")
    if kind == "path" and (ref is not None or commit is not None):
        raise fail(f"a path source cannot have a ref or commit ({name!r})")
    return Marketplace(name, source, ref, commit)


def _plugin(table: dict, fail) -> Plugin:
    id_ = _string(table["id"], "plugin id", fail)
    plugin, at, market = id_.rpartition("@")
    if not at or not plugin or not market:
        raise fail(f"invalid plugin id {id_!r} (expected <plugin>@<marketplace>)")
    version = _string(table["version"], f"version of {id_!r}", fail)
    enabled = table["enabled"]
    if not isinstance(enabled, bool):
        raise fail(f"enabled of {id_!r} must be true or false")
    return Plugin(id_, version, enabled)


def _uuid(value: object, fail) -> str:
    try:
        if isinstance(value, str) and str(uuid.UUID(value)) == value.lower():
            return value
    except ValueError:
        pass
    raise fail(f"org_uuid {value!r} is not a UUID")


def render(manifest: Manifest) -> str:
    blocks = []
    for market in sorted(manifest.marketplaces, key=lambda m: m.name):
        lines = [
            "[[marketplace]]",
            f"name = {toml_string(market.name)}",
            f"source = {toml_string(market.source)}",
        ]
        if market.ref is not None:
            lines.append(f"ref = {toml_string(market.ref)}")
        if market.commit is not None:
            lines.append(f"commit = {toml_string(market.commit)}")
        blocks.append("\n".join(lines))
    for plugin in sorted(manifest.plugins, key=lambda p: p.id):
        enabled = "true" if plugin.enabled else "false"
        blocks.append(
            "\n".join(
                [
                    "[[plugin]]",
                    f"id = {toml_string(plugin.id)}",
                    f"version = {toml_string(plugin.version)}",
                    f"enabled = {enabled}",
                ]
            )
        )
    if manifest.account is not None:
        blocks.append(f"[account]\norg_uuid = {toml_string(manifest.account.org_uuid)}")
    return "\n\n".join(blocks) + "\n" if blocks else ""


def save(path: Path, manifest: Manifest) -> None:
    fileio.write_private(path, render(manifest))


def source_spec(marketplace: Marketplace) -> str:
    """The argument of `claude plugin marketplace add` for this marketplace."""
    kind, _, rest = marketplace.source.partition(":")
    if kind == "path":
        return str(paths.normalize(rest))
    return rest if marketplace.ref is None else f"{rest}#{marketplace.ref}"
