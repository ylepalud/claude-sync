import pytest

from claude_sync import paths
from claude_sync.errors import ClaudeSyncError
from claude_sync.target import Target, resolve_target


def write_config(text):
    paths.config_home().mkdir(parents=True)
    paths.config_file().write_text(text)


WORK = 'default = "perso"\n\n[[match]]\npath = "~/Dev/work"\nprofile = "work"\n'


def test_an_explicit_profile_names_its_directory():
    paths.profile_dir("work").mkdir(parents=True)
    assert resolve_target("work") == Target("work", paths.profile_dir("work"))


def test_an_explicit_profile_wins_over_the_current_directory(monkeypatch):
    write_config(WORK)
    work = paths.normalize("~/Dev/work")
    work.mkdir(parents=True)
    monkeypatch.chdir(work)
    paths.profile_dir("other").mkdir(parents=True)
    assert resolve_target("other").name == "other"


def test_without_a_profile_the_current_directory_decides(monkeypatch):
    write_config(WORK)
    work = paths.normalize("~/Dev/work")
    work.mkdir(parents=True)
    monkeypatch.chdir(work)
    paths.profile_dir("work").mkdir(parents=True)
    assert resolve_target(None) == Target("work", paths.profile_dir("work"))


def test_the_override_variable_applies_without_a_profile(monkeypatch):
    monkeypatch.setenv("CLAUDE_SYNC_OVERRIDE", "work")
    paths.profile_dir("work").mkdir(parents=True)
    assert resolve_target(None).name == "work"


def test_a_missing_profile_directory_suggests_profile_create():
    with pytest.raises(ClaudeSyncError) as error:
        resolve_target("work")
    assert "claude-sync profile create work" in str(error.value)


def test_a_missing_directory_for_the_resolved_profile_suggests_profile_create():
    with pytest.raises(ClaudeSyncError) as error:
        resolve_target(None)
    assert "claude-sync profile create perso" in str(error.value)


def test_an_invalid_profile_name_is_refused():
    with pytest.raises(ClaudeSyncError, match="invalid profile name"):
        resolve_target("Bad_Name")
