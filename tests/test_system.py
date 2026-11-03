import os
import shutil
from types import SimpleNamespace

import pytest

from claude_sync import system
from claude_sync.errors import ClaudeSyncError


def test_no_claude_process(fake_system):
    assert system.running_claude() == []
    assert fake_system.calls() == [["pgrep", "-x", "claude"], ["pgrep", "-x", "Claude"]]


def test_cli_and_desktop_processes_are_reported_with_their_names(fake_system, monkeypatch):
    monkeypatch.setenv("FAKE_PGREP_PIDS_claude", "101 102")
    monkeypatch.setenv("FAKE_PGREP_PIDS_Claude", "201")
    assert system.running_claude() == [("claude", 101), ("claude", 102), ("Claude", 201)]


def test_a_failing_pgrep_raises_rather_than_reporting_no_process():
    # The autouse guard's pgrep exits 2.
    with pytest.raises(ClaudeSyncError, match="real pgrep blocked in tests"):
        system.running_claude()


def test_launchctl_passes_its_arguments(fake_system):
    system.launchctl("bootstrap", "gui/501", "/tmp/x.plist")
    assert fake_system.calls() == [["launchctl", "bootstrap", "gui/501", "/tmp/x.plist"]]


def test_a_launchctl_failure_raises_with_its_stderr(fake_system, monkeypatch):
    monkeypatch.setenv("FAKE_LAUNCHCTL_EXIT", "5")
    with pytest.raises(ClaudeSyncError, match="fake launchctl: unsetenv CLAUDE_CONFIG_DIR failed"):
        system.launchctl("unsetenv", "CLAUDE_CONFIG_DIR")


def test_uid_is_the_process_uid():
    assert system.uid() == os.getuid()


@pytest.fixture
def mounts(tmp_path, monkeypatch):
    """`tmp_path/a` and `tmp_path` on devices 7 and 9; `os.stat` reports them."""
    (tmp_path / "a").mkdir()
    devices = {str(tmp_path.resolve() / "a"): 7, str(tmp_path.resolve()): 9}
    real_stat = os.stat

    def stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path) in devices:
            return SimpleNamespace(st_dev=devices[str(path)], st_mode=result.st_mode)
        return result

    monkeypatch.setattr(os, "stat", stat)
    return tmp_path


def test_device_of_a_missing_path_is_that_of_its_nearest_existing_ancestor(mounts):
    assert system.device(mounts / "a" / "b" / "c") == 7
    assert system.device(mounts / "x" / "y") == 9
    assert system.device(mounts / "a") == 7


def test_free_bytes_of_a_missing_path_is_that_of_its_nearest_existing_ancestor(
    tmp_path, monkeypatch
):
    (tmp_path / "a").mkdir()
    asked = []

    def usage(path):
        asked.append(path)
        return SimpleNamespace(free=42)

    monkeypatch.setattr(shutil, "disk_usage", usage)
    assert system.free_bytes(tmp_path / "a" / "b" / "c") == 42
    assert asked == [(tmp_path / "a").resolve()]


def test_refuse_if_claude_runs_lists_every_process(fake_system, monkeypatch):
    monkeypatch.setenv("FAKE_PGREP_PIDS_claude", "101")
    monkeypatch.setenv("FAKE_PGREP_PIDS_Claude", "201")
    with pytest.raises(ClaudeSyncError, match=r"Claude is running \(claude 101, Claude 201\)"):
        system.refuse_if_claude_runs()


def test_refuse_if_claude_runs_passes_when_nothing_runs(fake_system):
    system.refuse_if_claude_runs()
