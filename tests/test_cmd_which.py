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


def test_which_text_is_the_profile_name(capsys):
    write_config(WORK)
    code, out, _ = run(capsys, "which", "~/Dev/work/api")
    assert (code, out) == (0, "work\n")


def test_which_defaults_to_the_current_directory(capsys, monkeypatch):
    write_config(WORK)
    work = paths.normalize("~/Dev/work")
    work.mkdir(parents=True)
    monkeypatch.chdir(work)
    assert run(capsys, "which")[1] == "work\n"


def test_which_without_a_file_is_the_default(capsys):
    assert run(capsys, "which")[1] == "perso\n"


def test_which_json_has_exactly_the_documented_keys(capsys):
    write_config(WORK)
    code, out, _ = run(capsys, "which", "~/Dev/work/api", "--json")
    data = json.loads(out)
    assert code == 0
    assert list(data) == ["profile", "source", "match", "config_dir", "initialized"]
    assert data["profile"] == "work"
    assert data["source"] == "match"
    assert data["match"] == "~/Dev/work"
    assert data["config_dir"].endswith("claude-sync/profiles/work")
    assert data["initialized"] is False


def test_which_honours_the_override_variable(capsys, monkeypatch):
    write_config(WORK)
    monkeypatch.setenv("CLAUDE_SYNC_OVERRIDE", "perso")
    _, out, _ = run(capsys, "which", "~/Dev/work", "--json")
    assert json.loads(out)["source"] == "override"
    assert json.loads(out)["profile"] == "perso"


def test_which_with_an_invalid_config_names_the_file_and_the_profile(capsys):
    write_config('default = "perso"\n\n[[match]]\npath = "~/x"\nprofile = "Work!"\n')
    code, out, err = run(capsys, "which")
    assert code == 1
    assert out == ""
    assert str(paths.config_file()) in err and "Work!" in err
