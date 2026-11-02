import pytest


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Keep every test away from the real home, git config and Keychain."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in (
        "XDG_CONFIG_HOME",
        "CLAUDE_CONFIG_DIR",
        "DENYLIST",
        "CLAUDE_SYNC_PROFILE",
        "CLAUDE_SYNC_OVERRIDE",
        "CLAUDE_SYNC_PROMPT",
        "CLAUDE_SYNC_USER_CONFIG_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    return home


def _is_case_sensitive(directory) -> bool:
    probe = directory / "CaseProbe"
    probe.mkdir()
    try:
        return not (directory / "caseprobe").exists()
    finally:
        probe.rmdir()


@pytest.fixture
def case_insensitive_fs(tmp_path):
    if _is_case_sensitive(tmp_path):
        pytest.skip("the file system of tmp_path is case-sensitive")


@pytest.fixture
def case_sensitive_fs(tmp_path):
    if not _is_case_sensitive(tmp_path):
        pytest.skip("the file system of tmp_path is case-insensitive")
