"""The `claude plugin ...` commands, run against one profile directory.

The JSON these commands print is undocumented: any shape this module does not
recognise raises rather than being guessed at.
"""

import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from claude_sync.errors import ClaudeSyncError


class ClaudeCliError(ClaudeSyncError):
    """A `claude` command failed or printed something unexpected."""

    def __init__(self, command: Sequence[str], stderr: str):
        self.command = list(command)
        self.stderr = stderr
        super().__init__(f"`{' '.join(self.command)}` failed: {stderr.strip()}")


@dataclass(frozen=True)
class InstalledPlugin:
    id: str
    version: str
    enabled: bool


@dataclass(frozen=True)
class InstalledMarketplace:
    name: str
    source: str
    """The CLI's source kind: github, git, url, directory, file or a claude.ai one."""
    target: str | None
    """Its `repo`, `url` or `path`; None for kinds that have none of them."""
    ref: str | None
    location: str


# The field holding the target of each source kind the CLI documents.
_TARGET_FIELD = {"github": "repo", "git": "url", "url": "url", "directory": "path", "file": "path"}


def _fields(item: dict, args: Sequence[str]):
    """A reader of `item`'s fields that raises on a missing or mistyped one."""

    def field(name: str, kind: type, required: bool = True):
        value = item.get(name)
        if value is None and not required:
            return None
        if not isinstance(value, kind):
            problem = f"field {name!r} missing or not {kind.__name__} in {json.dumps(item)}"
            raise ClaudeCliError(["claude", *args], problem)
        return value

    return field


# The `claude` arguments of each change a plan can hold, by operation.
_COMMANDS = {
    "add_marketplace": ("plugin", "marketplace", "add"),
    "remove_marketplace": ("plugin", "marketplace", "remove"),
    "install": ("plugin", "install"),
    "uninstall": ("plugin", "uninstall"),
    "enable": ("plugin", "enable"),
    "disable": ("plugin", "disable"),
}
# Plugin commands pin the user scope: enable and disable would otherwise auto-detect it.
_USER_SCOPE = ("--scope", "user")


def command(operation: str, target: str) -> tuple[str, ...]:
    """The `claude` arguments for `operation` (a ClaudeCli method name) on `target`.

    `install` never gets `--yes`: a marketplace-declared command is never
    approved on the user's behalf.
    """
    words = _COMMANDS[operation]
    scope = () if words[1] == "marketplace" else _USER_SCOPE
    return (*words, target, *scope)


class ClaudeCli:
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)

    def run(self, args: Sequence[str]) -> str:
        """Run `claude <args>` for this profile, stdin from /dev/null; its standard output."""
        command = ["claude", *args]
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config_dir)}
        try:
            result = subprocess.run(
                command, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True
            )
        except FileNotFoundError as error:
            raise ClaudeCliError(command, "claude not found on PATH") from error
        if result.returncode != 0:
            raise ClaudeCliError(command, result.stderr)
        return result.stdout

    def _json_list(self, args: Sequence[str]) -> list[dict]:
        output = self.run(args)
        try:
            data = json.loads(output)
        except ValueError as error:
            raise ClaudeCliError(["claude", *args], f"invalid JSON: {error}") from error
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ClaudeCliError(["claude", *args], "expected a JSON list of objects")
        return data

    def plugins(self) -> list[InstalledPlugin]:
        """The user-scope plugins of the profile.

        Project and local scope entries are ignored: a declared plugin installed
        only at another scope looks missing, and a plan installs it at user scope.
        """
        args = ["plugin", "list", "--json"]
        plugins = []
        for item in self._json_list(args):
            field = _fields(item, args)
            id_, version, scope = field("id", str), field("version", str), field("scope", str)
            enabled = field("enabled", bool)
            if scope == "user":
                plugins.append(InstalledPlugin(id_, version, enabled))
        return plugins

    def marketplaces(self) -> list[InstalledMarketplace]:
        args = ["plugin", "marketplace", "list", "--json"]
        markets = []
        for item in self._json_list(args):
            field = _fields(item, args)
            name, source = field("name", str), field("source", str)
            target_field = _TARGET_FIELD.get(source)
            target = field(target_field, str) if target_field else None
            ref = field("ref", str, required=False)
            markets.append(
                InstalledMarketplace(name, source, target, ref, field("installLocation", str))
            )
        return markets

    def add_marketplace(self, spec: str) -> None:
        self.run(command("add_marketplace", spec))

    def remove_marketplace(self, name: str) -> None:
        self.run(command("remove_marketplace", name))

    def install(self, plugin_id: str) -> None:
        self.run(command("install", plugin_id))

    def uninstall(self, plugin_id: str) -> None:
        self.run(command("uninstall", plugin_id))

    def enable(self, plugin_id: str) -> None:
        self.run(command("enable", plugin_id))

    def disable(self, plugin_id: str) -> None:
        self.run(command("disable", plugin_id))

    def marketplace_commit(self, location: str) -> str | None:
        """HEAD of the marketplace copy, only when the copy is its own git top level.

        Some copies are plain directories, or sit inside another repository (the
        official marketplace inside a versioned `~/.claude`): those have no commit.
        """

        def git(*args: str) -> str | None:
            result = subprocess.run(["git", "-C", location, *args], capture_output=True, text=True)
            return result.stdout.strip() if result.returncode == 0 else None

        top = git("rev-parse", "--show-toplevel")
        if top is None or Path(top).resolve() != Path(location).resolve():
            return None
        return git("rev-parse", "HEAD")
