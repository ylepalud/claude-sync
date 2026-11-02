from claude_sync.errors import ClaudeSyncError, ConfirmationRequired
from claude_sync.exit_codes import ExitCode


def test_exit_code_values_are_the_documented_ones():
    assert {c.name: int(c) for c in ExitCode} == {
        "OK": 0,
        "ERROR": 1,
        "USAGE": 2,
        "CONFIRMATION_REQUIRED": 3,
        "DRIFT": 4,
    }


def test_every_exit_code_has_a_one_line_description():
    for code in ExitCode:
        assert code.description and "\n" not in code.description


def test_confirmation_required_is_a_claude_sync_error():
    assert issubclass(ConfirmationRequired, ClaudeSyncError)
