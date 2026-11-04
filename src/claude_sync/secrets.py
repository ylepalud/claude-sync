"""Resolve the references of an MCP server's `env` and `headers` to values."""

import subprocess

from claude_sync.errors import ClaudeSyncError

_NOT_FOUND = 44


def resolve(reference: str) -> str:
    """The text to write for `env:NAME`, `value:<text>` or `keychain:<service>[/<account>]`.

    Errors name the reference, never the tool's output or a value.
    """
    kind, _, rest = reference.partition(":")
    if kind == "env" and rest:
        return "${" + rest + "}"
    if kind == "value" and rest:
        return rest
    if kind == "keychain" and rest:
        service, _, account = rest.partition("/")
        if "/" in account:
            raise ClaudeSyncError(f"{reference}: keychain account must not contain /")
        try:
            return keychain_value(service, account or None)
        except ClaudeSyncError as error:
            raise ClaudeSyncError(f"{reference}: {error}") from None
    raise ClaudeSyncError(f"invalid reference {reference!r}")


def keychain_value(service: str, account: str | None) -> str:
    """The Keychain password of `service` (and `account`), without its final newline."""
    command = ["security", "find-generic-password", "-s", service]
    if account is not None:
        command += ["-a", account]
    command.append("-w")
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except OSError:
        raise ClaudeSyncError("cannot run the `security` tool") from None
    if result.returncode == _NOT_FOUND:
        raise ClaudeSyncError("Keychain item not found")
    if result.returncode != 0:
        raise ClaudeSyncError(f"the `security` tool failed (exit {result.returncode})")
    try:
        return result.stdout.decode("utf-8").removesuffix("\n")
    except UnicodeDecodeError:
        raise ClaudeSyncError("the `security` tool did not answer in UTF-8") from None
