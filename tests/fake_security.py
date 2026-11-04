#!/usr/bin/env python3
"""A stand-in for the macOS `security` tool, for tests.

Answers `find-generic-password -s <service> [-a <account>] -w` from the JSON
object in `$HOME/.fake-keychain.json`, whose keys are `<service>` or
`<service>/<account>`. A missing item exits 44 with the real tool's message.
`FAKE_SECURITY_RAW=<hex>` answers those raw bytes to any call.
`FAKE_SECURITY_EXIT=<code>` makes every call fail with that code instead, after
printing a line on stderr that a caller must never show. Every call is appended
to `$HOME/.fake-keychain.log` as one JSON line `{"argv": [...]}`.
"""

import json
import os
import sys
from pathlib import Path

NOT_FOUND = (
    "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain."
)


def main(argv: list[str]) -> int:
    home = Path(os.environ["HOME"])
    with (home / ".fake-keychain.log").open("a") as log:
        log.write(json.dumps({"argv": argv}) + "\n")
    forced = os.environ.get("FAKE_SECURITY_EXIT")
    if forced:
        print("fake security: forced failure, tool output must not be shown", file=sys.stderr)
        return int(forced)
    raw = os.environ.get("FAKE_SECURITY_RAW")
    if raw:
        sys.stdout.buffer.write(bytes.fromhex(raw.replace(" ", "")))
        return 0
    if argv[:1] != ["find-generic-password"] or "-w" not in argv:
        print("fake security: unsupported call", file=sys.stderr)
        return 2
    options = dict(zip(argv[1:], argv[2:], strict=False))
    service, account = options.get("-s"), options.get("-a")
    store_file = home / ".fake-keychain.json"
    store = json.loads(store_file.read_text()) if store_file.exists() else {}
    key = service if account is None else f"{service}/{account}"
    if key not in store:
        print(NOT_FOUND, file=sys.stderr)
        return 44
    sys.stdout.buffer.write((store[key] + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
