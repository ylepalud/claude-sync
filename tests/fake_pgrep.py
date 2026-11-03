#!/usr/bin/env python3
"""A stand-in for `pgrep`, for tests.

Prints the process ids listed (space separated) in `FAKE_PGREP_PIDS_<name>`,
`<name>` being the last argument (`pgrep -x claude`), or else in
`FAKE_PGREP_PIDS`, one per line, and exits 1 when the list is empty. Every call is appended to
`$HOME/.fake-system.log` as one JSON line `{"argv": ["pgrep", ...]}`.
"""

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    with (Path(os.environ["HOME"]) / ".fake-system.log").open("a") as log:
        log.write(json.dumps({"argv": ["pgrep", *argv]}) + "\n")
    name = argv[-1] if argv else ""
    pids = os.environ.get(f"FAKE_PGREP_PIDS_{name}", os.environ.get("FAKE_PGREP_PIDS", "")).split()
    for pid in pids:
        print(pid)
    return 0 if pids else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
