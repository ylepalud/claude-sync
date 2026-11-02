import json

from claude_sync import paths
from claude_sync.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def write_config(text):
    paths.config_home().mkdir(parents=True)
    paths.config_file().write_text(text)


WORK = 'default = "perso"\n\n[[match]]\npath = "~/Dev/work"\nprofile = "work"\n'


def test_list_json_has_default_mapped_and_on_disk_profiles(capsys):
    write_config(WORK)
    paths.profile_dir("perso").mkdir(parents=True)
    paths.profile_dir("zeta").mkdir()
    (paths.profiles_root() / "Bad!").mkdir()
    code, out, _ = run(capsys, "list", "--json")
    assert code == 0
    assert json.loads(out) == {
        "profiles": [
            {"name": "perso", "default": True, "initialized": True, "paths": []},
            {"name": "work", "default": False, "initialized": False, "paths": ["~/Dev/work"]},
            {"name": "zeta", "default": False, "initialized": True, "paths": []},
        ]
    }


def test_list_text_marks_default_and_uninitialized(capsys):
    write_config(WORK)
    paths.profile_dir("perso").mkdir(parents=True)
    _, out, _ = run(capsys, "list")
    assert out.splitlines() == [
        "* perso",
        "  work (not initialized) ~/Dev/work",
    ]


def test_list_without_a_file_shows_the_uninitialized_default(capsys):
    _, out, _ = run(capsys, "list", "--json")
    assert json.loads(out)["profiles"] == [
        {"name": "perso", "default": True, "initialized": False, "paths": []}
    ]


def test_list_with_an_invalid_config_exits_1(capsys):
    write_config("nope = 1\n")
    assert run(capsys, "list")[0] == 1


def test_config_without_a_file_shows_defaults(capsys):
    code, out, _ = run(capsys, "config", "--json")
    assert code == 0
    assert json.loads(out) == {
        "file": str(paths.config_file()),
        "exists": False,
        "default": "perso",
        "matches": [],
    }


def test_config_with_a_file_shows_its_mappings(capsys):
    write_config(WORK)
    _, out, _ = run(capsys, "config", "--json")
    data = json.loads(out)
    assert data["exists"] is True
    assert data["matches"] == [{"path": "~/Dev/work", "profile": "work"}]


def test_config_text(capsys):
    write_config(WORK)
    _, out, _ = run(capsys, "config")
    assert out.splitlines() == [
        f"file: {paths.config_file()}",
        "exists: true",
        "default: perso",
        "~/Dev/work -> work",
    ]
