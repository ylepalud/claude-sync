from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes shared by every command."""

    description: str

    OK = (0, "success")
    ERROR = (1, "runtime error")
    USAGE = (2, "usage error")
    CONFIRMATION_REQUIRED = (3, "confirmation required but not given (rerun with --yes)")
    DRIFT = (4, "drift detected: state differs from what is declared")

    def __new__(cls, value: int, description: str) -> "ExitCode":
        member = int.__new__(cls, value)
        member._value_ = value
        member.description = description
        return member
