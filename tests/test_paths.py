from pathlib import Path

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
