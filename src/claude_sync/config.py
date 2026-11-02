"""The claude-sync configuration file: default profile and path mappings."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from claude_sync import fileio, paths
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
    seen: dict[Path, str] = {}
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
        normalized = paths.key(path)
        if normalized == Path("/"):
            raise fail(f"match path {path!r} maps the root directory")
        if normalized in seen:
            raise fail(f"match path {path!r} duplicates {seen[normalized]!r}")
        seen[normalized] = path
        matches.append(Match(path, _profile(table["profile"], fail, "match profile")))
    return Config(default, tuple(matches))


def _profile(value: object, fail, label: str) -> str:
    if not isinstance(value, str) or not PROFILE_NAME.fullmatch(value):
        raise fail(f"invalid profile name {value!r} for {label} (expected [a-z0-9][a-z0-9-]*)")
    return value


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    for code in range(0x20):
        escaped = escaped.replace(chr(code), f"\\u{code:04x}")
    escaped = escaped.replace(chr(0x7F), "\\u007f")
    return f'"{escaped}"'


def _render(config: Config) -> str:
    lines = [f"default = {toml_string(config.default)}"]
    for match in config.matches:
        lines += [
            "",
            "[[match]]",
            f"path = {toml_string(match.path)}",
            f"profile = {toml_string(match.profile)}",
        ]
    return "\n".join(lines) + "\n"


def save(config: Config) -> None:
    fileio.write_private(paths.config_file(), _render(config))
