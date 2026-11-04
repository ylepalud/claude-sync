#!/usr/bin/env python3
"""A stand-in for `brew`, `npm`, `uv` and `cargo`, for tests.

Invoked as `fake_manager.py <manager> [args...]` by the wrapper a fixture
writes under each manager's name. Every call is appended to
`$HOME/.fake-managers.log` as one JSON line `{"argv": [manager, ...]}`.

`$HOME/.fake-managers.json` holds `{"packages": {"<manager>:<package>":
{"tool": name, "output": text}}, "listed": ["<formula>"], "failing":
["<manager>:<package>"]}`. An install or upgrade (any call but `brew list`)
of a configured package makes the tool present: it records the tool's output
in `$HOME/.fake-tools.json` and writes its wrapper into `$FAKE_TOOLS_BIN`;
a brew formula is then also listed. An unknown package exits 1 with "no such
package"; a failing one exits 1 with "forced failure". `brew list <formula>`
exits 0 when the formula is listed, 1 otherwise.
"""

import json
import os
import stat
import sys
from pathlib import Path

FAKE_TOOL = Path(__file__).with_name("fake_tool.py")


def main(argv: list[str]) -> int:
    manager, args = argv[0], argv[1:]
    home = Path(os.environ["HOME"])
    with (home / ".fake-managers.log").open("a") as log:
        log.write(json.dumps({"argv": argv}) + "\n")
    config_file = home / ".fake-managers.json"
    config = json.loads(config_file.read_text()) if config_file.exists() else {}
    package = args[-1] if args else ""
    if manager == "npm" and package.endswith("@latest"):
        package = package[: -len("@latest")]
    if manager == "brew" and args[:1] == ["list"]:
        return 0 if package in config.get("listed", []) else 1
    key = f"{manager}:{package}"
    if key in config.get("failing", []):
        print(f"fake {manager}: forced failure for {package}", file=sys.stderr)
        return 1
    provided = config.get("packages", {}).get(key)
    if provided is None:
        print(f"fake {manager}: no such package {package}", file=sys.stderr)
        return 1
    tools_file = home / ".fake-tools.json"
    tools = json.loads(tools_file.read_text()) if tools_file.exists() else {}
    tools[provided["tool"]] = provided["output"]
    tools_file.write_text(json.dumps(tools))
    wrapper = Path(os.environ["FAKE_TOOLS_BIN"]) / provided["tool"]
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_TOOL}" "{wrapper.name}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    if manager == "brew":
        config.setdefault("listed", []).append(package)
        config_file.write_text(json.dumps(config))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
