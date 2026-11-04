"""A stand-in for the `claude` CLI's `plugin` and `mcp` commands, for tests.

The config dir is `$CLAUDE_CONFIG_DIR`, or `$HOME/.claude` when it is unset
(as for the real CLI). State lives in `<config dir>/fake-claude.json`:

    {"marketplaces": [{"name", "source", "repo" | "url" | "path", "ref"?,
                       "installLocation"}],
     "plugins": [{"id", "version", "scope", "enabled"}],
     "catalog": {"<marketplace>": {"<plugin>": "<version>"}},
     "upstream": {"<owner/repo or url>": "<local git repo path>"},
     "fail": {"<subcommand words>": "<stderr text>"},
     "output": {"<subcommand words>": "<stdout text replacing the normal output>"}}

`marketplace add X[#R]` clones `upstream[X]` with `git clone --branch R` and
reads the marketplace name and catalog from its `.claude-plugin/marketplace.json`.
Every call is appended to `<config dir>/fake-claude.log` as one JSON line
`{"argv": [...], "stdin": "devnull" | "other", "config_dir_env": <CLAUDE_CONFIG_DIR or null>}`.

`mcp add-json <name> <json> --scope user` stores the JSON verbatim (only
`streamable-http` becomes `http`; a remote entry without `type` is refused)
in the top-level `mcpServers` of the CLI's state file (below), written with
mode 600; an existing name fails. `mcp remove <name> -s user` removes it; an
unknown name fails. Any other scope fails. Both honour `fail`.

With `FAKE_CLAUDE_WRITES_STATE=1`, every call creates the CLI's state file
when it is missing, as the real CLI does at start: `<config dir>/.claude.json`
when `CLAUDE_CONFIG_DIR` is set, else `$HOME/.claude.json`.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE_FILE = "fake-claude.json"
LOG_FILE = "fake-claude.log"


class Exit(Exception):
    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message


def _stdin_kind() -> str:
    try:
        stdin, devnull = os.fstat(0), os.stat(os.devnull)
    except OSError:
        return "other"
    same = (stdin.st_dev, stdin.st_ino) == (devnull.st_dev, devnull.st_ino)
    return "devnull" if same else "other"


def _option(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def _positional(argv: list[str], skip: int, count: int = 1):
    """The one positional argument after `argv[:skip]`, or a list of `count` of them."""
    rest = argv[skip:]
    values = []
    index = 0
    while index < len(rest):
        if rest[index] in ("--scope", "-s"):
            index += 2
        elif rest[index].startswith("-"):
            index += 1
        else:
            values.append(rest[index])
            index += 1
    if len(values) != count:
        raise Exit(1, f"expected {count} argument(s), got {len(values)}")
    return values[0] if count == 1 else values


def _command_words(argv: list[str]) -> str:
    if argv[:2] == ["plugin", "marketplace"]:
        return " ".join(argv[:3])
    return " ".join(argv[:2])


def _source_of(key: str) -> dict:
    if key.startswith("/"):
        return {"source": "directory", "path": key}
    if key.endswith(".json"):
        return {"source": "url", "url": key}
    if "://" in key or "@" in key:
        return {"source": "git", "url": key}
    return {"source": "github", "repo": key}


def _read_catalog(location: Path) -> tuple[str, dict[str, str]]:
    file = location / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(file.read_text())
    except (OSError, ValueError) as error:
        raise Exit(1, f"no marketplace.json in {location}: {error}") from error
    return data["name"], {p["name"]: p["version"] for p in data.get("plugins", [])}


def _find_plugin(state: dict, plugin_id: str, scope: str | None) -> dict:
    for plugin in state["plugins"]:
        if plugin["id"] == plugin_id and scope in (None, plugin["scope"]):
            return plugin
    raise Exit(1, f'Plugin "{plugin_id}" is not installed')


def _marketplace_add(state: dict, argv: list[str], config: Path) -> str:
    spec = _positional(argv, 3)
    key, hash_, ref = spec.partition("#")
    entry = _source_of(key)
    if entry["source"] == "directory":
        location = Path(key)
    else:
        if key not in state["upstream"]:
            raise Exit(1, f"Failed to clone marketplace repository: {key} not found")
        clone = config / "plugins" / "marketplaces" / "_incoming"
        shutil.rmtree(clone, ignore_errors=True)
        command = ["git", "clone", "--quiet"]
        if hash_:
            command += ["--branch", ref]
        result = subprocess.run(
            [*command, state["upstream"][key], str(clone)], capture_output=True, text=True
        )
        if result.returncode != 0:
            shutil.rmtree(clone, ignore_errors=True)
            raise Exit(1, result.stderr)
        location = clone
    name, catalog = _read_catalog(location)
    if any(m["name"] == name for m in state["marketplaces"]):
        if location.name == "_incoming":
            shutil.rmtree(location)
        raise Exit(1, f"Marketplace '{name}' is already installed")
    if location.name == "_incoming":
        final = location.with_name(name)
        location.rename(final)
        location = final
    if hash_:
        entry["ref"] = ref
    state["marketplaces"].append({"name": name, **entry, "installLocation": str(location)})
    state["catalog"][name] = catalog
    return f"Successfully added marketplace: {name}"


def _marketplace_remove(state: dict, argv: list[str], config: Path) -> str:
    name = _positional(argv, 3)
    market = next((m for m in state["marketplaces"] if m["name"] == name), None)
    if market is None:
        raise Exit(1, f"Marketplace '{name}' not found")
    state["marketplaces"].remove(market)
    state["plugins"] = [p for p in state["plugins"] if not p["id"].endswith(f"@{name}")]
    state["catalog"].pop(name, None)
    location = Path(market["installLocation"])
    if location.is_relative_to(config / "plugins" / "marketplaces"):
        shutil.rmtree(location, ignore_errors=True)
    return f"Successfully removed marketplace: {name}"


def _install(state: dict, argv: list[str]) -> str:
    plugin_id = _positional(argv, 2)
    name, _, market = plugin_id.rpartition("@")
    version = state["catalog"].get(market, {}).get(name)
    if version is None:
        raise Exit(1, f'Plugin "{plugin_id}" not found in any marketplace')
    scope = _option(argv, "--scope") or "user"
    if any(p["id"] == plugin_id and p["scope"] == scope for p in state["plugins"]):
        return f"Plugin {plugin_id} is already installed"
    state["plugins"].append({"id": plugin_id, "version": version, "scope": scope, "enabled": True})
    return f"Successfully installed plugin: {plugin_id}"


def _uninstall(state: dict, argv: list[str]) -> str:
    plugin_id = _positional(argv, 2)
    state["plugins"].remove(_find_plugin(state, plugin_id, _option(argv, "--scope")))
    return f"Successfully uninstalled plugin: {plugin_id}"


def _set_enabled(state: dict, argv: list[str], enabled: bool) -> str:
    plugin_id = _positional(argv, 2)
    plugin = _find_plugin(state, plugin_id, _option(argv, "--scope"))
    word = "enabled" if enabled else "disabled"
    if plugin["enabled"] == enabled:
        raise Exit(1, f'Plugin "{plugin_id}" is already {word}')
    plugin["enabled"] = enabled
    return f"Successfully {word} plugin: {plugin_id}"


def _cli_state(file: Path) -> dict:
    return json.loads(file.read_text()) if file.exists() else {}


def _write_cli_state(file: Path, data: dict) -> None:
    file.write_text(json.dumps(data, indent=2))
    file.chmod(0o600)


def _mcp_add_json(argv: list[str], cli_state: Path) -> str:
    if _option(argv, "--scope") != "user":
        raise Exit(1, "fake claude: mcp add-json supports the user scope only")
    name, entry = _positional(argv, 2, count=2)
    entry = json.loads(entry)
    if "type" not in entry and "command" not in entry:
        raise Exit(1, "Invalid configuration: type is required for a remote server")
    if entry.get("type") == "streamable-http":
        entry["type"] = "http"
    data = _cli_state(cli_state)
    servers = data.setdefault("mcpServers", {})
    if name in servers:
        raise Exit(1, f"MCP server {name} already exists in user config")
    servers[name] = entry
    _write_cli_state(cli_state, data)
    return f"Added MCP server {name} to user config"


def _mcp_remove(argv: list[str], cli_state: Path) -> str:
    if _option(argv, "-s") != "user":
        raise Exit(1, "fake claude: mcp remove supports the user scope only")
    name = _positional(argv, 2)
    data = _cli_state(cli_state)
    if name not in data.get("mcpServers", {}):
        raise Exit(1, f"No user-scoped MCP server found with name: {name}")
    del data["mcpServers"][name]
    _write_cli_state(cli_state, data)
    return f"Removed MCP server {name} from user config"


def run(argv: list[str], config: Path, cli_state: Path) -> str:
    state_file = config / STATE_FILE
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    for key, empty in (("marketplaces", []), ("plugins", []), ("catalog", {})):
        state.setdefault(key, empty)
    state.setdefault("upstream", {})
    state.setdefault("fail", {})

    words = _command_words(argv)
    if words in state["fail"]:
        raise Exit(1, state["fail"][words])
    if words in state.get("output", {}):
        return state["output"][words]
    if words == "mcp add-json":
        return _mcp_add_json(argv, cli_state)
    if words == "mcp remove":
        return _mcp_remove(argv, cli_state)
    if words == "plugin list":
        return json.dumps(state["plugins"], indent=2)
    if words == "plugin marketplace list":
        return json.dumps(state["marketplaces"], indent=2)
    if words == "plugin marketplace add":
        output = _marketplace_add(state, argv, config)
    elif words == "plugin marketplace remove":
        output = _marketplace_remove(state, argv, config)
    elif words == "plugin install":
        output = _install(state, argv)
    elif words == "plugin uninstall":
        output = _uninstall(state, argv)
    elif words in ("plugin enable", "plugin disable"):
        output = _set_enabled(state, argv, words == "plugin enable")
    else:
        raise Exit(1, f"fake claude: unsupported command {argv}")
    state_file.write_text(json.dumps(state, indent=2))
    return output


def main(argv: list[str]) -> int:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or None
    home = Path(os.environ["HOME"])
    config = Path(config_dir) if config_dir else home / ".claude"
    config.mkdir(parents=True, exist_ok=True)
    state_file = config / ".claude.json" if config_dir else home / ".claude.json"
    if os.environ.get("FAKE_CLAUDE_WRITES_STATE") == "1":
        if not state_file.exists():
            state_file.write_text("{}\n")
    entry = {"argv": argv, "stdin": _stdin_kind(), "config_dir_env": config_dir}
    with (config / LOG_FILE).open("a") as log:
        log.write(json.dumps(entry) + "\n")
    try:
        output = run(argv, config, state_file)
    except Exit as error:
        print(error.message, file=sys.stderr)
        return error.code
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
