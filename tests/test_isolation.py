import os
import subprocess
import sys
from pathlib import Path

# Read at import, before the fixtures change them.
ORIGINAL_PATH = os.environ["PATH"]


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


def test_real_claude_is_blocked():
    result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
    assert result.returncode == 1
    assert "real claude blocked in tests" in result.stderr


def test_e2e_switch_is_cleared():
    assert "CLAUDE_SYNC_E2E" not in os.environ


def test_fake_claude_replaces_the_guard(fake_claude, tmp_path):
    profile = tmp_path / "profile"
    fake_claude.seed(profile, {})
    result = subprocess.run(
        ["claude", "plugin", "list", "--json"],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_CONFIG_DIR": str(profile)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
    assert fake_claude.calls(profile) == [["plugin", "list", "--json"]]


def test_e2e_switch_keeps_the_guard_outside_the_e2e_module(tmp_path):
    """With CLAUDE_SYNC_E2E=1, a non-e2e test still gets the blocking claude."""
    stand_in = tmp_path / "real-bin"
    stand_in.mkdir()
    (stand_in / "claude").write_text("#!/bin/sh\necho real claude ran\n")
    (stand_in / "claude").chmod(0o755)
    env = {
        **os.environ,
        "CLAUDE_SYNC_E2E": "1",
        "PATH": f"{stand_in}{os.pathsep}{ORIGINAL_PATH}",
    }
    test = f"{Path(__file__)}::test_real_claude_is_blocked"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout
    assert "1 passed" in result.stdout
