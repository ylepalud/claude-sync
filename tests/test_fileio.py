import os
import stat

import pytest

from claude_sync import fileio


def test_write_private_creates_a_mode_600_file(tmp_path):
    file = tmp_path / "sub" / "f.txt"
    fileio.write_private(file, "hello\n")
    assert file.read_text() == "hello\n"
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert [p.name for p in file.parent.iterdir()] == ["f.txt"]


def test_write_private_creates_a_missing_parent_with_mode_700(tmp_path):
    file = tmp_path / "a" / "b" / "f.txt"
    fileio.write_private(file, "x")
    assert stat.S_IMODE(file.parent.stat().st_mode) == 0o700


def test_write_private_replaces_an_existing_file(tmp_path):
    file = tmp_path / "f.txt"
    file.write_text("old")
    os.chmod(file, 0o644)
    fileio.write_private(file, "new")
    assert file.read_text() == "new"
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_write_private_removes_the_temp_file_when_replace_fails(tmp_path, monkeypatch):
    file = tmp_path / "f.txt"
    file.write_text("old")

    def boom(*args):
        raise OSError("boom")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="boom"):
        fileio.write_private(file, "new")
    assert file.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir() if p.name != "home"] == ["f.txt"]
