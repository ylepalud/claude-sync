"""A stand-in for the `claude` CLI's `plugin` commands, for tests.

State lives in `$CLAUDE_CONFIG_DIR/fake-claude.json`:

    {"marketplaces": [{"name", "source", "repo" | "url" | "path", "ref"?,
                       "installLocation"}],
     "plugins": [{"id", "version", "scope", "enabled"}],
     "catalog": {"<marketplace>": {"<plugin>": "<version>"}},
     "upstream": {"<owner/repo or url>": "<local git repo path>"},
     "fail": {"<subcommand words>": "<stderr text>"}}

`marketplace add X[#R]` clones `upstream[X]` with `git clone --branch R` and
reads the marketplace name and catalog from its `.claude-plugin/marketplace.json`.
Every call is appended to `$CLAUDE_CONFIG_DIR/fake-claude.log` as one JSON line
`{"argv": [...], "stdin": "devnull" | "other"}`.
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


def _positional(argv: list[str], skip: int) -> str:
    rest = argv[skip:]
    values = []
    index = 0
    while index < len(rest):
        if rest[index] == "--scope":
            index += 2
        elif rest[index].startswith("-"):
            index += 1
        else:
            values.append(rest[index])
            index += 1
    if len(values) != 1:
        raise Exit(1, f"expected one argument, got {values}")
    return values[0]


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


def run(argv: list[str], config: Path) -> str:
    state_file = config / STATE_FILE
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    for key, empty in (("marketplaces", []), ("plugins", []), ("catalog", {})):
        state.setdefault(key, empty)
    state.setdefault("upstream", {})
    state.setdefault("fail", {})

    words = _command_words(argv)
    if words in state["fail"]:
        raise Exit(1, state["fail"][words])
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
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not config_dir:
        print("fake claude: CLAUDE_CONFIG_DIR is not set", file=sys.stderr)
        return 1
    config = Path(config_dir)
    config.mkdir(parents=True, exist_ok=True)
    with (config / LOG_FILE).open("a") as log:
        log.write(json.dumps({"argv": argv, "stdin": _stdin_kind()}) + "\n")
    try:
        output = run(argv, config)
    except Exit as error:
        print(error.message, file=sys.stderr)
        return error.code
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
