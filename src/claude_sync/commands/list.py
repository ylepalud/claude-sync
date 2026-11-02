from __future__ import annotations

import argparse

from claude_sync import config, paths
from claude_sync.context import Context
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def configure(parser: argparse.ArgumentParser) -> None:
    pass


def run(args: argparse.Namespace, ctx: Context) -> int:
    cfg = config.load()
    names = {cfg.default} | {m.profile for m in cfg.matches}
    root = paths.profiles_root()
    if root.is_dir():
        names |= {
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and config.PROFILE_NAME.fullmatch(entry.name)
        }
    profiles = [
        {
            "name": name,
            "default": name == cfg.default,
            "initialized": paths.profile_dir(name).is_dir(),
            "paths": [m.path for m in cfg.matches if m.profile == name],
        }
        for name in sorted(names)
    ]
    lines = []
    for profile in profiles:
        line = f"{'*' if profile['default'] else ' '} {profile['name']}"
        if not profile["initialized"]:
            line += " (not initialized)"
        if profile["paths"]:
            line += " " + " ".join(profile["paths"])
        lines.append(line)
    ctx.emit({"profiles": profiles}, "\n".join(lines))
    return int(ExitCode.OK)


COMMAND = Command(
    name="list",
    summary="list the known profiles",
    description=(
        "List every known profile: the default, every mapped profile and every\n"
        "directory under the profiles root. A star marks the default."
    ),
    examples=[
        ("claude-sync list", "one line per profile"),
        ("claude-sync list --json", "print the profiles as JSON"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="read",
    configure=configure,
    run=run,
)
