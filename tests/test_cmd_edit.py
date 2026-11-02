import stat

from claude_sync import config, paths
from claude_sync.cli import main

RELOAD = "run claude-sync-reload in open shells to apply"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def write_config(text):
    paths.config_home().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(text)


WORK = 'default = "perso"\n\n[[match]]\npath = "~/Dev/work"\nprofile = "work"\n'


# map


def test_map_creates_the_file_with_mode_600(capsys):
    code, _, err = run(capsys, "map", "~/Dev/work", "work")
    assert code == 0
    assert stat.S_IMODE(paths.config_file().stat().st_mode) == 0o600
    assert paths.config_file().read_text() == WORK
    assert RELOAD in err


def test_map_stores_a_home_path_with_a_tilde(capsys):
    run(capsys, "map", str(paths.normalize("~/Dev/work")), "work")
    assert config.load().matches[0].path == "~/Dev/work"


def test_identical_map_is_a_noop(capsys):
    write_config(WORK)
    before = paths.config_file().stat().st_mtime_ns
    code, _, err = run(capsys, "map", "~/Dev/work", "work")
    assert code == 0
    assert paths.config_file().stat().st_mtime_ns == before
    assert RELOAD not in err


def test_replace_without_yes_and_without_tty_exits_3(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    write_config(WORK)
    code, _, _ = run(capsys, "map", "~/Dev/work", "other")
    assert code == 3
    assert paths.config_file().read_text() == WORK


def test_replace_with_yes_replaces_and_keeps_other_entries(capsys):
    write_config(WORK + '\n[[match]]\npath = "~/Dev/oss"\nprofile = "perso"\n')
    code, _, err = run(capsys, "map", "~/Dev/work", "other", "--yes")
    assert code == 0
    assert [(m.path, m.profile) for m in config.load().matches] == [
        ("~/Dev/work", "other"),
        ("~/Dev/oss", "perso"),
    ]
    assert RELOAD in err


def test_map_dry_run_writes_nothing(capsys):
    code, out, err = run(capsys, "map", "~/Dev/work", "work", "--dry-run")
    assert code == 0
    assert out == "would map ~/Dev/work -> work\n"
    assert not paths.config_file().exists()
    assert RELOAD not in err


def test_map_replace_dry_run_says_would_replace(capsys):
    write_config(WORK)
    code, out, _ = run(capsys, "map", "~/Dev/work", "other", "--dry-run")
    assert code == 0
    assert out == "would replace ~/Dev/work -> other\n"
    assert paths.config_file().read_text() == WORK


def test_map_rejects_an_invalid_profile_name(capsys):
    code, _, err = run(capsys, "map", "~/Dev/work", "Bad!")
    assert code == 1
    assert "Bad!" in err
    assert not paths.config_file().exists()


def test_map_with_an_invalid_existing_config_leaves_it_untouched(capsys):
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
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    write_config(WORK)
    code, _, err = run(capsys, "map", "~/Dev/work", "other")
    assert code == 0
    assert paths.config_file().read_text() == WORK
    assert RELOAD not in err
