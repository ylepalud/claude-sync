"""User-scope MCP servers: observe a profile's, and converge them through `claude mcp`.

No value of `env` or `headers` ever leaves this module in a message, a
description or an exception: differences name field paths, and every command
shown masks those values as `***`.
"""

import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from claude_sync import manifest, secrets, settings
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, McpServer
from claude_sync.sync import Difference

STATE_FILE = ".claude.json"
_FIELDS = ("type", "command", "args", "url")
_TABLES = ("env", "headers")
_WHOLE_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}")
# The fields claude-sync models for each transport.
_MODELLED = {
    "stdio": ("type", "command", "args", "env"),
    "http": ("type", "url", "headers"),
    "sse": ("type", "url", "headers"),
}


def observe(profile_dir: Path) -> dict[str, dict]:
    """The top-level `mcpServers` of the profile's `.claude.json`, by name.

    Each entry gets its `type`: `stdio` when absent, `http` for `streamable-http`.
    """
    file = Path(profile_dir) / STATE_FILE
    servers = settings._load(file).get("mcpServers", {})
    if not isinstance(servers, dict) or not all(isinstance(e, dict) for e in servers.values()):
        raise ClaudeSyncError(f"{file}: mcpServers must be an object of server objects")
    observed = {}
    for name, entry in servers.items():
        kind = entry.get("type", "stdio")
        observed[name] = {**entry, "type": "http" if kind == "streamable-http" else kind}
    return observed


def _resolved(server: McpServer) -> tuple[dict, dict[str, str]]:
    """The JSON `desired` writes, without the keys that do not resolve, and the
    resolution error of each of them by field path (e.g. `headers.Authorization`)."""
    if server.transport == "stdio":
        entry = {"type": "stdio", "command": server.command, "args": list(server.args)}
        table = "env"
    else:
        entry = {"type": server.transport, "url": server.url}
        table = "headers"
    entry[table], failures = {}, {}
    for key, reference in getattr(server, table).items():
        try:
            entry[table][key] = secrets.resolve(reference)
        except ClaudeSyncError as error:
            failures[f"{table}.{key}"] = str(error)
    return entry, failures


def desired(server: McpServer) -> dict:
    """The JSON `claude mcp add-json` gets for `server`, references resolved, `type` always set.

    Raises ClaudeSyncError naming the server, the key and the reference when
    one does not resolve.
    """
    entry, failures = _resolved(server)
    if failures:
        path, problem = next(iter(failures.items()))
        raise ClaudeSyncError(f"MCP server {server.name!r}: {path}: {problem}")
    return entry


def _strings(value: object) -> bool:
    return isinstance(value, dict) and all(isinstance(v, str) for v in value.values())


def unmodelled(entry: dict) -> list[str]:
    """The fields of an observed entry claude-sync cannot record: unknown, or of
    another shape than a manifest table gives (an unknown `type` is one of them).
    A server with any is unmanaged."""
    kind = entry["type"]
    modelled = _MODELLED.get(kind) if isinstance(kind, str) else None
    if modelled is None:
        return ["type"]
    fields = [f for f in entry if f not in modelled]
    checks = {
        "command": lambda v: isinstance(v, str),
        "url": lambda v: isinstance(v, str),
        "args": lambda v: isinstance(v, list) and all(isinstance(a, str) for a in v),
        "env": _strings,
        "headers": _strings,
    }
    required = "command" if entry["type"] == "stdio" else "url"
    for name in modelled[1:]:
        present = name in entry
        if (present and not checks[name](entry[name])) or (name == required and not present):
            fields.append(name)
    return fields


def _changed_paths(wanted: dict, entry: dict) -> list[str]:
    """The fields of `entry` differing from `wanted`, `env` and `headers` key by key."""

    def get(item: dict, field: str):
        return item.get(field, [] if field == "args" else None)

    paths = [f for f in _FIELDS if get(wanted, f) != get(entry, f)]
    for table in _TABLES:
        mine, theirs = wanted.get(table, {}), entry.get(table, {})
        keys = [*mine, *(k for k in theirs if k not in mine)]
        paths += [f"{table}.{k}" for k in keys if mine.get(k) != theirs.get(k)]
    return paths


def diff(declared: Manifest, observed: dict[str, dict]) -> list[Difference]:
    """The differences between the declared servers and `observed` (from `observe`).

    Kinds: `mcp-missing`; `mcp-secret` per reference that does not resolve
    (expected: its field path, actual: the problem, naming the reference);
    `mcp-changed` with the differing field paths in `actual` (comparing
    resolved values, a Keychain reference by the value it resolves to);
    `mcp-unlisted`; `mcp-unmanaged` (information) for a server with
    unmodelled fields, named in `actual`, which a declared server of that
    name also reports as `mcp-changed`. No difference carries a value of
    `env` or `headers`.
    """
    differences = []
    names = {s.name for s in declared.mcp}
    for server in declared.mcp:
        entry = observed.get(server.name)
        if entry is None:
            differences.append(Difference("mcp-missing", server.name, server.transport, None))
            continue
        fields = unmodelled(entry)
        if fields:
            differences.append(Difference("mcp-changed", server.name, None, ", ".join(fields)))
            continue
        wanted, failures = _resolved(server)
        for path, problem in failures.items():
            differences.append(Difference("mcp-secret", server.name, path, problem))
        changed = [p for p in _changed_paths(wanted, entry) if p not in failures]
        if changed:
            differences.append(Difference("mcp-changed", server.name, None, ", ".join(changed)))
    for name, entry in observed.items():
        fields = unmodelled(entry)
        if fields:
            differences.append(Difference("mcp-unmanaged", name, None, ", ".join(fields)))
        elif name not in names:
            differences.append(Difference("mcp-unlisted", name, None, entry["type"]))
    return differences


@dataclass(frozen=True)
class McpAction:
    description: str
    """What the action does, to print after `would ` in a dry run and in a
    confirmation: `run: <shown>`; the removal of an http or sse server appends
    `  (removes an <type> server: drops its OAuth sign-in)`."""
    confirm: bool
    args: tuple[str, ...] = field(repr=False)
    """The arguments after `claude`; they hold resolved values: never print them
    (left out of the repr)."""
    shown: str
    """The command line with every `env` and `headers` value as `***`, for dry
    runs, confirmations and the error of a failing command."""


def _masked(entry: dict) -> dict:
    return {k: dict.fromkeys(v, "***") if k in _TABLES else v for k, v in entry.items()}


def _add(name: str, entry: dict, confirm: bool = False) -> McpAction:
    def args(json_entry: dict) -> tuple[str, ...]:
        return ("mcp", "add-json", name, json.dumps(json_entry), "--scope", "user")

    shown = "claude " + shlex.join(args(_masked(entry)))
    return McpAction(f"run: {shown}", confirm, args(entry), shown)


def _remove(name: str, kind: str, confirm: bool) -> McpAction:
    args = ("mcp", "remove", name, "-s", "user")
    shown = "claude " + shlex.join(args)
    note = f"  (removes an {kind} server: drops its OAuth sign-in)" if kind != "stdio" else ""
    return McpAction(f"run: {shown}{note}", confirm, args, shown)


def plan(declared: Manifest, observed: dict[str, dict], prune: bool) -> list[McpAction]:
    """The `claude mcp` commands converging the profile's servers, in order.

    Per declared server: add when missing; remove then add again when it
    differs (confirmed when the removed server is http or sse: that drops its
    OAuth sign-in). With `prune`, a confirmed removal per unlisted server.
    Unmanaged servers are never replaced or removed.

    Raises ClaudeSyncError, before returning any action, for a reference that
    does not resolve (see `desired`) and for a declared server whose observed
    entry is unmanaged.
    """
    actions = []
    for server in declared.mcp:
        entry = desired(server)
        actual = observed.get(server.name)
        fields = unmodelled(actual) if actual is not None else []
        if fields:
            raise ClaudeSyncError(
                f"MCP server {server.name!r} is declared, but the profile's entry has fields "
                f"claude-sync does not manage ({', '.join(fields)}): remove the server with "
                f"`claude mcp remove {server.name} -s user`, or remove it from the manifest"
            )
        if actual is None:
            actions.append(_add(server.name, entry))
        elif _changed_paths(entry, actual):
            # Removing a remote server drops its OAuth sign-in: that needs a confirmation.
            confirm = actual["type"] != "stdio"
            actions.append(_remove(server.name, actual["type"], confirm))
            actions.append(_add(server.name, entry, confirm))
    if prune:
        names = {s.name for s in declared.mcp}
        for name, actual in observed.items():
            if name not in names and not unmodelled(actual):
                actions.append(_remove(name, actual["type"], True))
    return actions


def _warn(message: str) -> None:
    print(f"claude-sync: warning: {message}", file=sys.stderr)


def _kept(before: McpServer | None, table: str, key: str, value: str) -> str | None:
    """The previous reference of this server's key when it still produces `value`;
    a Keychain one that does not resolve is kept with a warning."""
    reference = getattr(before, table).get(key) if before is not None else None
    if reference is None:
        return None
    try:
        return reference if secrets.resolve(reference) == value else None
    except ClaudeSyncError as error:
        _warn(f"MCP server {before.name!r}: {table}.{key}: kept {reference}, unresolved: {error}")
        return reference


def _variable(server: str, key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", f"{server}_{key}").upper()


def _reference(name: str, table: str, key: str, value: str) -> tuple[str, str | None]:
    """The reference recording an observed value, and the variable to export, if any."""
    whole = _WHOLE_PLACEHOLDER.fullmatch(value)
    if whole:
        return f"env:{whole.group(1)}", None
    if _PLACEHOLDER.search(value):
        return f"value:{value}", None
    variable = _variable(name, key)
    if variable[0].isdigit():
        raise ClaudeSyncError(
            f"MCP server {name!r}: {table}.{key} would become {variable}, "
            f"which starts with a digit: rename the server"
        )
    return f"env:{variable}", variable


def _imported(name: str, entry: dict, references: dict[str, str]) -> McpServer:
    if entry["type"] == "stdio":
        args = tuple(entry.get("args", []))
        return McpServer(name, "stdio", entry["command"], args, env=references)
    return McpServer(name, entry["type"], url=entry["url"], headers=references)


def import_servers(
    profile_dir: Path, previous: Manifest | None = None
) -> tuple[tuple[McpServer, ...], list[str]]:
    """The servers of the profile's `.claude.json` as manifest tables, and the
    environment variables to export (names only) for the references it made.

    Each `env` or `headers` value becomes `env:NAME` when it is exactly
    `${NAME}`, `value:<text>` when it holds another placeholder, else
    `env:<SERVER>_<KEY>` (upper case, non-alphanumerics as `_`), listed in the
    exports.

    Raises ClaudeSyncError naming the servers and keys, aborting the whole
    import (even for a server the manifest rules would then reject), when a
    made variable starts with a digit, when two servers' keys would make the
    same variable, or when a made variable is also used by another key of the
    same server (an exact `${NAME}` or a kept `env:` reference). Servers may
    share a variable through their placeholders.

    `previous`, the manifest being replaced: a reference it declares for the
    same server, table and key is kept when it resolves to the observed value
    (a `keychain:` one that does not resolve is kept with a warning).

    Left out with a warning on stderr: unmanaged servers (naming their
    unmodelled fields), and, once the checks above pass, servers the manifest
    rules would reject (an invalid name, an empty command or url).
    """
    file = Path(profile_dir) / STATE_FILE
    servers, exports = [], []
    taken: dict[str, str] = {}
    before = {s.name: s for s in previous.mcp} if previous is not None else {}
    for name, entry in sorted(observe(profile_dir).items()):
        fields = unmodelled(entry)
        if fields:
            _warn(
                f"skipped MCP server {name!r}: fields claude-sync does not manage: "
                f"{', '.join(fields)}"
            )
            continue
        table = "env" if entry["type"] == "stdio" else "headers"
        references, made = {}, {}
        # Every variable a key of this server uses, with its path and whether import made it.
        named: dict[str, tuple[str, bool]] = {}
        for key, value in entry.get(table, {}).items():
            kept = _kept(before.get(name), table, key, value)
            variable = None
            if kept is None:
                kept, variable = _reference(name, table, key, value)
            references[key] = kept
            if not kept.startswith("env:"):
                continue
            used, path, generated = (
                kept.removeprefix("env:"),
                f"{table}.{key} of {name!r}",
                variable is not None,
            )
            if generated and used in taken:
                other = taken[used]
            elif used in named and (generated or named[used][1]):
                other = named[used][0]
            else:
                other = None
            if other is not None:
                raise ClaudeSyncError(
                    f"MCP server {name!r}: {path} and {other} would both use "
                    f"{used}: rename one of the keys"
                )
            named.setdefault(used, (path, generated))
            if generated:
                made[used] = path
        server = _imported(name, entry, references)
        try:
            tables = manifest.Manifest((), (), None, mcp=(server,))
            manifest._parse(tomllib.loads(manifest.render(tables)), file)
        except manifest.ManifestError as error:
            _warn(f"skipped MCP server {name!r}: {error}")
            continue
        servers.append(server)
        taken.update(made)
        exports += made
    return tuple(servers), exports
