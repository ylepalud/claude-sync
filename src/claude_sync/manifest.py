"""The profile manifest: the plugins and marketplaces a profile declares."""

import re
import shlex
import tomllib
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from claude_sync import fileio, paths
from claude_sync.config import PROFILE_NAME, toml_string
from claude_sync.errors import ClaudeSyncError

MANIFEST_FILE = "profile.toml"

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_GITHUB = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KEYCHAIN = re.compile(r"[^/]+(/[^/]+)?")
_DOTTED = re.compile(r"[0-9]+(\.[0-9]+)+")
_PACKAGE = re.compile(r"[A-Za-z0-9@][A-Za-z0-9@._/+-]*")
RECIPE_KINDS = ("brew", "npm", "uv", "cargo", "script")


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
class SkillSource:
    name: str
    source: str
    ref: str | None
    commit: str | None


@dataclass(frozen=True)
class Skill:
    id: str
    path: str
    tree: str | None


@dataclass(frozen=True)
class McpServer:
    """A user-scope MCP server; `env` and `headers` hold references, never secrets."""

    name: str
    transport: str
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    env: dict[str, str] = dataclass_field(default_factory=dict)
    headers: dict[str, str] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    """A command-line tool a profile needs: `version` is a minimum, `install` a recipe."""

    name: str
    version: str | None = None
    check: str | None = None
    install: str | None = None


@dataclass(frozen=True)
class Manifest:
    marketplaces: tuple[Marketplace, ...]
    plugins: tuple[Plugin, ...]
    account: Account | None
    skill_sources: tuple[SkillSource, ...] = ()
    skills: tuple[Skill, ...] = ()
    mcp: tuple[McpServer, ...] = ()
    tools: tuple[Tool, ...] = ()


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

    unknown = set(data) - {
        "marketplace",
        "plugin",
        "account",
        "skill_source",
        "skill",
        "mcp",
        "tool",
    }
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

    sources = []
    source_names: set[str] = set()
    for table in _tables(data, "skill_source", fail):
        _check_keys(table, {"name", "source"}, {"ref", "commit"}, "a skill source", fail)
        source = _skill_source(table, fail)
        if source.name in source_names:
            raise fail(f"duplicate skill source {source.name!r}")
        source_names.add(source.name)
        sources.append(source)

    skills = []
    skill_ids: set[str] = set()
    for table in _tables(data, "skill", fail):
        _check_keys(table, {"id", "path"}, {"tree"}, "a skill", fail)
        skill = _skill(table, fail)
        if skill.id in skill_ids:
            raise fail(f"duplicate skill {skill.id!r}")
        skill_ids.add(skill.id)
        origin = skill.id.partition("@")[2]
        if origin not in source_names:
            raise fail(f"skill {skill.id!r} uses undeclared skill source {origin!r}")
        skills.append(skill)

    servers = []
    server_names: set[str] = set()
    for table in _tables(data, "mcp", fail):
        server = _mcp(table, fail)
        if server.name in server_names:
            raise fail(f"duplicate MCP server {server.name!r}")
        server_names.add(server.name)
        servers.append(server)

    tools = []
    tool_names: set[str] = set()
    for table in _tables(data, "tool", fail):
        _check_keys(table, {"name"}, {"version", "check", "install"}, "a tool", fail)
        tool = _tool(table, fail)
        if tool.name in tool_names:
            raise fail(f"duplicate tool {tool.name!r}")
        tool_names.add(tool.name)
        tools.append(tool)

    account = None
    if "account" in data:
        table = data["account"]
        if not isinstance(table, dict):
            raise fail("'account' must be a table")
        _check_keys(table, {"org_uuid"}, set(), "account", fail)
        account = Account(_uuid(table["org_uuid"], fail))
    return Manifest(
        tuple(marketplaces),
        tuple(plugins),
        account,
        tuple(sources),
        tuple(skills),
        tuple(servers),
        tuple(tools),
    )


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


def _skill_source(table: dict, fail) -> SkillSource:
    name = _string(table["name"], "skill source name", fail)
    if not _NAME.fullmatch(name):
        raise fail(f"invalid skill source name {name!r}")
    source = _string(table["source"], f"source of {name!r}", fail)
    kind, _, rest = source.partition(":")
    if kind not in ("github", "git") or not rest:
        raise fail(f"invalid source {source!r} for {name!r} (github: or git:)")
    if kind == "github" and not _GITHUB.fullmatch(rest):
        raise fail(f"invalid source {source!r} for {name!r} (expected github:<owner>/<repo>)")
    ref = table.get("ref")
    if "ref" in table:
        ref = _string(ref, f"ref of {name!r}", fail)
    commit = table.get("commit")
    if "commit" in table:
        if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
            raise fail(f"commit of {name!r} must be 40 lowercase hex characters")
    return SkillSource(name, source, ref, commit)


def _skill(table: dict, fail) -> Skill:
    id_ = _string(table["id"], "skill id", fail)
    name, at, origin = id_.partition("@")
    if not at:
        raise fail(f"skill id {id_!r} must be <skill>@<source name>")
    if not PROFILE_NAME.fullmatch(name) or not origin:
        raise fail(f"invalid skill id {id_!r} (expected <skill>@<source name>)")
    path = _string(table["path"], f"path of {id_!r}", fail)
    if path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
        raise fail(
            f"path of {id_!r} must be a clean relative path, "
            f"without '.', '..' or empty segments ({path!r})"
        )
    tree = table.get("tree")
    if "tree" in table:
        if not isinstance(tree, str) or not _COMMIT.fullmatch(tree):
            raise fail(f"tree of {id_!r} must be 40 lowercase hex characters")
    return Skill(id_, path, tree)


_REFERENCE_FORMS = "env:<NAME>, keychain:<service>[/<account>] or value:<text>"


def _reference(value: object, label: str, fail) -> str:
    """Validate a reference; errors name `label` (e.g. `env.TOKEN`), never the text."""
    kind, _, rest = value.partition(":") if isinstance(value, str) else ("", "", "")
    if kind == "env" and _ENV_NAME.fullmatch(rest):
        return value
    if kind == "keychain" and _KEYCHAIN.fullmatch(rest):
        return value
    if kind == "keychain" and rest.count("/") > 1:
        raise fail(f"invalid reference for {label}: keychain account must not contain /")
    if kind == "value" and rest:
        return value
    if kind in ("env", "keychain", "value"):
        raise fail(f"invalid reference for {label}: expected {_REFERENCE_FORMS}")
    raise fail(f"{label} must be env:, keychain: or value: ({_REFERENCE_FORMS})")


def _references(table: dict, key: str, owner: str, fail) -> dict[str, str]:
    mapping = table.get(key, {})
    if not isinstance(mapping, dict):
        raise fail(f"{key} of {owner!r} must be a table")
    result = {}
    for name, value in mapping.items():
        if not name:
            raise fail(f"empty {key} key in {owner!r}")
        result[name] = _reference(value, f"{key}.{name} of {owner!r}", fail)
    return result


def _mcp(table: dict, fail) -> McpServer:
    _check_keys(
        table,
        {"name", "transport"},
        {"command", "args", "url", "env", "headers"},
        "an MCP server",
        fail,
    )
    name = _string(table["name"], "MCP server name", fail)
    if not _NAME.fullmatch(name):
        raise fail(f"invalid MCP server name {name!r}")
    transport = table["transport"]
    if transport not in ("stdio", "http", "sse"):
        raise fail(f"invalid transport {transport!r} for {name!r} (stdio, http or sse)")
    if transport == "stdio":
        for forbidden in ("url", "headers"):
            if forbidden in table:
                raise fail(f"{forbidden} is not allowed on stdio server {name!r}")
        command = _string(table.get("command"), f"command of {name!r}", fail)
        args = table.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise fail(f"args of {name!r} must be a list of strings")
        url = None
    else:
        for forbidden in ("command", "args", "env"):
            if forbidden in table:
                raise fail(f"{forbidden} is not allowed on {transport} server {name!r}")
        url = _string(table.get("url"), f"url of {name!r}", fail)
        command, args = None, []
    return McpServer(
        name,
        transport,
        command,
        tuple(args),
        url,
        _references(table, "env", name, fail),
        _references(table, "headers", name, fail),
    )


def _tool(table: dict, fail) -> Tool:
    name = _string(table["name"], "tool name", fail)
    if not _NAME.fullmatch(name):
        raise fail(f"invalid tool name {name!r}")
    version = table.get("version")
    if "version" in table:
        version = _string(version, f"version of {name!r}", fail)
        if not _DOTTED.fullmatch(version):
            raise fail(f"version of {name!r} must be dotted numbers such as 1.2 ({version!r})")
    check = table.get("check")
    if "check" in table:
        check = _string(check, f"check of {name!r}", fail)
        try:
            words = shlex.split(check)
        except ValueError as error:
            raise fail(f"check of {name!r} is not a valid command line: {error}") from error
        if not words or words[0] != name:
            raise fail(f"the first word of the check of {name!r} must be {name!r}")
    install = table.get("install")
    if "install" in table:
        install = _recipe(_string(install, f"install of {name!r}", fail), name, fail)
    return Tool(name, version, check, install)


def _recipe(recipe: str, name: str, fail) -> str:
    kind, _, rest = recipe.partition(":")
    if kind not in RECIPE_KINDS:
        raise fail(f"invalid install {recipe!r} for {name!r} (brew:, npm:, uv:, cargo: or script:)")
    if not rest.strip():
        raise fail(f"install of {name!r} has an empty {kind}: recipe")
    if kind != "script":
        if not _PACKAGE.fullmatch(rest):
            raise fail(f"invalid package {rest!r} in the install of {name!r}")
    elif "\n" in rest:
        raise fail(f"the script of {name!r} must be a single line")
    elif any(ord(c) < 32 or ord(c) == 127 for c in rest):
        raise fail(f"the script of {name!r} must not contain a control character")
    return recipe


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
    for source in sorted(manifest.skill_sources, key=lambda s: s.name):
        lines = [
            "[[skill_source]]",
            f"name = {toml_string(source.name)}",
            f"source = {toml_string(source.source)}",
        ]
        if source.ref is not None:
            lines.append(f"ref = {toml_string(source.ref)}")
        if source.commit is not None:
            lines.append(f"commit = {toml_string(source.commit)}")
        blocks.append("\n".join(lines))
    for skill in sorted(manifest.skills, key=lambda s: s.id):
        lines = ["[[skill]]", f"id = {toml_string(skill.id)}", f"path = {toml_string(skill.path)}"]
        if skill.tree is not None:
            lines.append(f"tree = {toml_string(skill.tree)}")
        blocks.append("\n".join(lines))
    for server in sorted(manifest.mcp, key=lambda m: m.name):
        lines = [
            "[[mcp]]",
            f"name = {toml_string(server.name)}",
            f"transport = {toml_string(server.transport)}",
        ]
        if server.command is not None:
            lines.append(f"command = {toml_string(server.command)}")
        if server.args:
            lines.append(f"args = [{', '.join(toml_string(a) for a in server.args)}]")
        if server.url is not None:
            lines.append(f"url = {toml_string(server.url)}")
        for key, mapping in (("env", server.env), ("headers", server.headers)):
            if mapping:
                lines.append(f"[mcp.{key}]")
                lines += [f"{toml_string(k)} = {toml_string(v)}" for k, v in mapping.items()]
        blocks.append("\n".join(lines))
    for tool in sorted(manifest.tools, key=lambda t: t.name):
        lines = ["[[tool]]", f"name = {toml_string(tool.name)}"]
        for key in ("version", "check", "install"):
            if getattr(tool, key) is not None:
                lines.append(f"{key} = {toml_string(getattr(tool, key))}")
        blocks.append("\n".join(lines))
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
