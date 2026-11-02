import os
from pathlib import Path


def test_home_is_a_temporary_directory(tmp_path):
    assert Path(os.environ["HOME"]).is_relative_to(tmp_path)


def test_config_locations_are_unset():
    for name in ("XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "DENYLIST"):
        assert name not in os.environ


def test_shell_integration_variables_are_unset():
    for name in (
        "CLAUDE_SYNC_PROFILE",
        "CLAUDE_SYNC_OVERRIDE",
        "CLAUDE_SYNC_PROMPT",
        "CLAUDE_SYNC_USER_CONFIG_DIR",
    ):
        assert name not in os.environ


def test_git_global_and_system_config_are_disabled():
    assert os.environ["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert os.environ["GIT_CONFIG_SYSTEM"] == "/dev/null"
