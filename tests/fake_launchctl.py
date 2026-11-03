#!/usr/bin/env python3
"""A stand-in for `launchctl`, for tests.

Exits with `FAKE_LAUNCHCTL_EXIT` (default 0), printing an error on stderr when
that is not 0. Every call is appended to `$HOME/.fake-system.log` as one JSON
line `{"argv": ["launchctl", ...]}`.
"""

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    with (Path(os.environ["HOME"]) / ".fake-system.log").open("a") as log:
        log.write(json.dumps({"argv": ["launchctl", *argv]}) + "\n")
    code = int(os.environ.get("FAKE_LAUNCHCTL_EXIT", "0"))
    if code:
        print(f"fake launchctl: {' '.join(argv)} failed", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
