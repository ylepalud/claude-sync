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
    file = paths.config_file()
    exists = file.exists()
    lines = [f"file: {file}", f"exists: {'true' if exists else 'false'}", f"default: {cfg.default}"]
    lines += [f"{m.path} -> {m.profile}" for m in cfg.matches]
    ctx.emit(
        {
            "file": str(file),
            "exists": exists,
            "default": cfg.default,
            "matches": [{"path": m.path, "profile": m.profile} for m in cfg.matches],
        },
        "\n".join(lines),
    )
    return int(ExitCode.OK)


COMMAND = Command(
    name="config",
    summary="show the configuration file and its content",
    description=(
        "Show the configuration file path, whether it exists, the default profile\n"
        "and the path mappings. Without a file the defaults apply."
    ),
    examples=[
        ("claude-sync config", "print the file, the default and the mappings"),
        ("claude-sync config --json", "print the same as JSON"),
    ],
    exit_codes=[ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE],
    kind="read",
    configure=configure,
    run=run,
)
