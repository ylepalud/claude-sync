#!/usr/bin/env python3
"""A stand-in for a command-line tool (`fakejq`, `faketool`), for tests.

Invoked as `fake_tool.py <name> [args...]` by the wrapper a fixture writes
under the tool's name. Prints what `$HOME/.fake-tools.json` configures for
`<name>`: a string (printed with a newline, exit 0) or an object
`{"output": str, "exit": int, "sleep": seconds, "read_stdin": bool,
"requires_arg": str}`: `read_stdin` appends what the tool reads on its standard
input to the output; with `requires_arg`, any call without that argument exits 2.
A name absent from that file exits 127 with "command not found", as a shell would.
"""

import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    name = argv[0]
    file = Path(os.environ["HOME"]) / ".fake-tools.json"
    config = json.loads(file.read_text()) if file.exists() else {}
    if name not in config:
        print(f"fake tool: {name}: command not found", file=sys.stderr)
        return 127
    entry = config[name]
    if isinstance(entry, str):
        entry = {"output": entry}
    required = entry.get("requires_arg")
    if required is not None and required not in argv[1:]:
        print(f"fake tool: {name}: expected {required}", file=sys.stderr)
        return 2
    time.sleep(entry.get("sleep", 0))
    output = entry.get("output", "")
    if entry.get("read_stdin"):
        output += sys.stdin.read()
    print(output)
    return entry.get("exit", 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
