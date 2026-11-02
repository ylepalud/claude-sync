"""The claude-sync configuration file: default profile and path mappings."""

import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from claude_sync import paths
from claude_sync.errors import ClaudeSyncError

PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
DEFAULT_PROFILE = "perso"


class ConfigError(ClaudeSyncError):
    """The configuration file is invalid."""


@dataclass(frozen=True)
class Match:
    path: str
    profile: str


@dataclass(frozen=True)
class Config:
    default: str
    matches: tuple[Match, ...]


def load() -> Config:
    file = paths.config_file()
    try:
        raw = file.read_bytes()
    except FileNotFoundError:
        return Config(DEFAULT_PROFILE, ())
    except OSError as error:
        raise ConfigError(f"{file}: cannot read: {error.strerror}") from error
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ConfigError(f"{file}: invalid TOML: {error}") from error
    return _parse(data, file)


def _parse(data: dict, file: Path) -> Config:
    def fail(problem: str) -> ConfigError:
        return ConfigError(f"{file}: {problem}")

    unknown = set(data) - {"default", "match"}
    if unknown:
        raise fail(f"unknown key {sorted(unknown)[0]!r}")
    if "default" not in data:
        raise fail("missing field 'default'")
    default = _profile(data["default"], fail, "default")
    tables = data.get("match", [])
    if not isinstance(tables, list):
        raise fail("'match' must be an array of tables")
    matches = []
    for table in tables:
        if not isinstance(table, dict):
            raise fail("'match' must be an array of tables")
        unknown = set(table) - {"path", "profile"}
        if unknown:
            raise fail(f"unknown key {sorted(unknown)[0]!r} in a match")
        for field in ("path", "profile"):
            if field not in table:
                raise fail(f"missing field {field!r} in a match")
        path = table["path"]
        if not isinstance(path, str) or not path:
            raise fail("match path must be a non-empty string")
        matches.append(Match(path, _profile(table["profile"], fail, "match profile")))
    return Config(default, tuple(matches))


def _profile(value: object, fail, label: str) -> str:
    if not isinstance(value, str) or not PROFILE_NAME.fullmatch(value):
        raise fail(f"invalid profile name {value!r} for {label} (expected [a-z0-9][a-z0-9-]*)")
    return value


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    for code in range(0x20):
        escaped = escaped.replace(chr(code), f"\\u{code:04x}")
    escaped = escaped.replace(chr(0x7F), "\\u007f")
    return f'"{escaped}"'


def _render(config: Config) -> str:
    lines = [f"default = {_quote(config.default)}"]
    for match in config.matches:
        lines += [
            "",
            "[[match]]",
            f"path = {_quote(match.path)}",
            f"profile = {_quote(match.profile)}",
        ]
    return "\n".join(lines) + "\n"


def save(config: Config) -> None:
    directory = paths.config_home()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_render(config))
        os.chmod(temp, 0o600)
        os.replace(temp, paths.config_file())
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
