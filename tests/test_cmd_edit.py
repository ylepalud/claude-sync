import stat

import pytest

from claude_sync import config, paths
from claude_sync.cli import main

RELOAD = "run claude-sync-reload in open shells to apply"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def make_dirs(*names):
    for name in names:
        (paths.normalize("~") / name).mkdir(parents=True, exist_ok=True)


def write_config(text):
    paths.config_home().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(text)


WORK = 'default = "perso"\n\n[[match]]\npath = "~/Dev/work"\nprofile = "work"\n'


# map


def test_map_creates_the_file_with_mode_600(capsys):
    make_dirs("Dev/work")
    code, _, err = run(capsys, "map", "~/Dev/work", "work")
    assert code == 0
    assert stat.S_IMODE(paths.config_file().stat().st_mode) == 0o600
    assert paths.config_file().read_text() == WORK
    assert RELOAD in err


def test_map_stores_a_home_path_with_a_tilde(capsys):
    make_dirs("Dev/work")
    run(capsys, "map", str(paths.normalize("~/Dev/work")), "work")
    assert config.load().matches[0].path == "~/Dev/work"


def test_identical_map_is_a_noop(capsys):
    make_dirs("Dev/work")
    write_config(WORK)
    before = paths.config_file().stat().st_mtime_ns
    code, out, err = run(capsys, "map", "~/Dev/work", "work")
    assert (code, out) == (0, "already mapped: ~/Dev/work -> work\n")
    assert paths.config_file().stat().st_mtime_ns == before
    assert RELOAD not in err


def test_identical_map_under_dry_run_says_already_mapped(capsys):
    make_dirs("Dev/work")
    write_config(WORK)
    code, out, err = run(capsys, "map", "~/Dev/work", "work", "--dry-run")
    assert (code, out) == (0, "already mapped: ~/Dev/work -> work\n")
    assert RELOAD not in err


def test_map_refuses_a_missing_directory(capsys):
    code, out, err = run(capsys, "map", "~/Dev/missing", "work", "--yes")
    assert (code, out) == (1, "")
    assert "~/Dev/missing" in err
    assert not paths.config_file().exists()


def test_map_refuses_a_file(capsys):
    make_dirs("Dev")
    (paths.normalize("~") / "Dev" / "file").write_text("x")
    code, _, _ = run(capsys, "map", "~/Dev/file", "work", "--yes")
    assert code == 1
    assert not paths.config_file().exists()


def test_map_refuses_the_root(capsys):
    code, _, err = run(capsys, "map", "/", "work", "--yes")
    assert code == 1
    assert "/" in err
    assert not paths.config_file().exists()


def test_map_stores_the_on_disk_spelling(capsys):
    make_dirs("Dev")
    (paths.normalize("~") / "Dev" / "Work").mkdir()
    if not (paths.normalize("~") / "dev" / "work").exists():
        pytest.skip("the file system of the home directory is case-sensitive")
    code, _, _ = run(capsys, "map", "~/dev/work", "work", "--yes")
    assert code == 0
    assert config.load().matches[0].path == "~/Dev/Work"


def test_replace_without_yes_and_without_tty_exits_3(capsys, monkeypatch):
    make_dirs("Dev/work")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    write_config(WORK)
    code, _, _ = run(capsys, "map", "~/Dev/work", "other")
    assert code == 3
    assert paths.config_file().read_text() == WORK


def test_replace_with_yes_replaces_and_keeps_other_entries(capsys):
    make_dirs("Dev/work")
    write_config(WORK + '\n[[match]]\npath = "~/Dev/oss"\nprofile = "perso"\n')
    code, _, err = run(capsys, "map", "~/Dev/work", "other", "--yes")
    assert code == 0
    assert [(m.path, m.profile) for m in config.load().matches] == [
        ("~/Dev/work", "other"),
        ("~/Dev/oss", "perso"),
    ]
    assert RELOAD in err


def test_map_dry_run_writes_nothing(capsys):
    make_dirs("Dev/work")
    code, out, err = run(capsys, "map", "~/Dev/work", "work", "--dry-run")
    assert code == 0
    assert out == "would map ~/Dev/work -> work\n"
    assert not paths.config_file().exists()
    assert RELOAD not in err


def test_map_replace_dry_run_says_would_replace(capsys):
    make_dirs("Dev/work")
    write_config(WORK)
    code, out, _ = run(capsys, "map", "~/Dev/work", "other", "--dry-run")
    assert code == 0
    assert out == "would replace ~/Dev/work -> other\n"
    assert paths.config_file().read_text() == WORK


def test_map_rejects_an_invalid_profile_name(capsys):
    make_dirs("Dev/work")
    code, _, err = run(capsys, "map", "~/Dev/work", "Bad!")
    assert code == 1
    assert "Bad!" in err
    assert not paths.config_file().exists()


def test_map_with_an_invalid_existing_config_leaves_it_untouched(capsys):
    make_dirs("Dev/work")
    write_config("nope = 1\n")
    code, _, _ = run(capsys, "map", "~/Dev/work", "work", "--yes")
    assert code == 1
    assert paths.config_file().read_text() == "nope = 1\n"


# unmap


def test_unmap_removes_the_mapping(capsys):
    write_config(WORK + '\n[[match]]\npath = "~/Dev/oss"\nprofile = "perso"\n')
    code, _, err = run(capsys, "unmap", "~/Dev/work")
    assert code == 0
    assert [m.path for m in config.load().matches] == ["~/Dev/oss"]
    assert RELOAD in err


def test_unmap_of_an_unknown_path_exits_1(capsys):
    write_config(WORK)
    code, _, err = run(capsys, "unmap", "~/Dev/other")
    assert code == 1
    assert "~/Dev/other" in err
    assert paths.config_file().read_text() == WORK


def test_unmap_dry_run_writes_nothing(capsys):
    write_config(WORK)
    code, out, err = run(capsys, "unmap", "~/Dev/work", "--dry-run")
    assert (code, out) == (0, "would unmap ~/Dev/work\n")
    assert paths.config_file().read_text() == WORK
    assert RELOAD not in err


# set-default


def test_set_default_writes_the_default(capsys):
    write_config(WORK)
    code, _, err = run(capsys, "set-default", "work")
    assert code == 0
    cfg = config.load()
    assert cfg.default == "work"
    assert [m.path for m in cfg.matches] == ["~/Dev/work"]
    assert RELOAD in err


def test_set_default_validates_the_name(capsys):
    code, _, err = run(capsys, "set-default", "Bad!")
    assert code == 1
    assert "Bad!" in err
    assert not paths.config_file().exists()


def test_set_default_dry_run_writes_nothing(capsys):
    code, out, err = run(capsys, "set-default", "work", "--dry-run")
    assert (code, out) == (0, "would set default to work\n")
    assert not paths.config_file().exists()
    assert RELOAD not in err


def test_declining_the_replacement_at_a_tty_changes_nothing(capsys, monkeypatch):
    make_dirs("Dev/work")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    write_config(WORK)
    code, _, err = run(capsys, "map", "~/Dev/work", "other")
    assert code == 0
    assert paths.config_file().read_text() == WORK
    assert RELOAD not in err


def test_a_stored_path_with_the_wrong_case_counts_as_the_same_mapping(capsys):
    make_dirs("Dev/Work")
    if not (paths.normalize("~") / "dev" / "work").exists():
        pytest.skip("the file system of the home directory is case-sensitive")
    write_config(WORK.replace("~/Dev/work", "~/dev/work"))
    code, out, _ = run(capsys, "map", "~/Dev/Work", "work")
    assert (code, out) == (0, "already mapped: ~/Dev/Work -> work\n")
    assert len(config.load().matches) == 1


def test_unmap_matches_a_wrong_case_stored_path(capsys, case_insensitive_fs):
    make_dirs("Dev/work")
    write_config(WORK.replace("~/Dev/work", "~/dev/work"))
    code, _, _ = run(capsys, "unmap", "~/Dev/work")
    assert code == 0
    assert config.load().matches == ()


def test_unmap_matches_a_wrong_case_path(capsys, case_insensitive_fs):
    make_dirs("Dev/work")
    write_config(WORK)
    code, _, _ = run(capsys, "unmap", "~/dev/work")
    assert code == 0
    assert config.load().matches == ()
