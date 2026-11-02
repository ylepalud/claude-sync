from pathlib import Path

import pytest

from claude_sync import paths


def test_xdg_config_home_is_honoured(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert paths.config_home() == tmp_path / "xdg" / "claude-sync"
    assert paths.config_file() == tmp_path / "xdg" / "claude-sync" / "config.toml"
    assert paths.profiles_root() == tmp_path / "xdg" / "claude-sync" / "profiles"
    assert paths.profile_dir("work") == tmp_path / "xdg" / "claude-sync" / "profiles" / "work"


def test_default_config_home_is_under_home(isolated_environment):
    assert paths.config_home() == isolated_environment / ".config" / "claude-sync"


def test_normalize_expands_tilde_and_resolves_symlink(isolated_environment):
    real = isolated_environment / "real"
    real.mkdir()
    (isolated_environment / "link").symlink_to(real)
    assert paths.normalize("~/link/x") == real.resolve() / "x"


def test_normalize_makes_relative_paths_absolute(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert paths.normalize("sub") == tmp_path.resolve() / "sub"


def test_display_abbreviates_under_home(isolated_environment):
    assert paths.display(isolated_environment / "Dev" / "work") == "~/Dev/work"


def test_display_keeps_absolute_path_elsewhere(tmp_path):
    assert paths.display(Path("/opt/elsewhere")) == "/opt/elsewhere"


def test_display_of_home_itself(isolated_environment):
    assert paths.display(isolated_environment) == "~"


def test_display_abbreviates_with_symlinked_home(isolated_environment, tmp_path, monkeypatch):
    link = tmp_path / "homelink"
    link.symlink_to(isolated_environment)
    monkeypatch.setenv("HOME", str(link))
    assert paths.display(isolated_environment.resolve() / "a") == "~/a"


def test_on_disk_keeps_the_exact_spelling(tmp_path):
    (tmp_path / "Dev" / "work").mkdir(parents=True)
    target = tmp_path.resolve() / "Dev" / "work"
    assert paths.on_disk(target) == target


def test_on_disk_leaves_a_missing_component_unchanged(tmp_path):
    target = tmp_path.resolve() / "nope" / "Deeper"
    assert paths.on_disk(target) == target


def test_on_disk_corrects_the_letter_case(tmp_path):
    (tmp_path / "A").mkdir()
    if not (tmp_path / "a").exists():
        pytest.skip("the file system of tmp_path is case-sensitive")
    (tmp_path / "Dev").mkdir()
    root = tmp_path.resolve()
    assert paths.on_disk(root / "dev") == root / "Dev"


def test_on_disk_prefers_the_exact_spelling(tmp_path, case_sensitive_fs):
    (tmp_path / "a").mkdir()
    (tmp_path / "A").mkdir()
    root = tmp_path.resolve()
    assert paths.on_disk(root / "a") == root / "a"
    assert paths.on_disk(root / "A") == root / "A"


def test_key_is_the_normalized_on_disk_path(isolated_environment, case_insensitive_fs):
    (isolated_environment / "Dev" / "work").mkdir(parents=True)
    assert paths.key("~/dev/work") == paths.normalize("~") / "Dev" / "work"
