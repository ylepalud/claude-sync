import json
import subprocess

from claude_sync import manifest, paths
from claude_sync.cli import main

ORG = "00000000-0000-0000-0000-000000000000"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def mode(path):
    return path.stat().st_mode & 0o777


def test_create_makes_a_private_git_repository_with_an_empty_manifest(capsys):
    code, _, _ = run(capsys, "profile", "create", "work")
    directory = paths.profile_dir("work")
    assert code == 0
    assert mode(paths.profiles_root()) == 0o700
    assert mode(directory) == 0o700
    assert (directory / ".git").is_dir()
    assert (directory / ".gitignore").read_text() == "/*\n!/.gitignore\n!/profile.toml\n"
    assert (directory / "profile.toml").read_text() == ""
    loaded = manifest.load(directory / "profile.toml")
    assert (loaded.marketplaces, loaded.plugins, loaded.account) == ((), (), None)


def test_create_makes_no_commit(capsys):
    run(capsys, "profile", "create", "work")
    log = subprocess.run(
        ["git", "-C", str(paths.profile_dir("work")), "log"], capture_output=True, text=True
    )
    assert log.returncode != 0


def test_only_the_manifest_and_gitignore_are_tracked(capsys):
    run(capsys, "profile", "create", "work")
    directory = paths.profile_dir("work")
    (directory / "settings.json").write_text("{}")
    status = subprocess.run(
        ["git", "-C", str(directory), "status", "--porcelain", "-uall"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert sorted(line[3:] for line in status.splitlines()) == [".gitignore", "profile.toml"]


def test_create_with_an_org_uuid_writes_the_account(capsys):
    code, _, _ = run(capsys, "profile", "create", "work", "--org-uuid", ORG)
    loaded = manifest.load(paths.profile_dir("work") / "profile.toml")
    assert code == 0
    assert loaded.account == manifest.Account(ORG)


def test_a_directory_mapped_to_the_created_profile_is_initialized(capsys):
    work = paths.normalize("~/Dev/work")
    work.mkdir(parents=True)
    run(capsys, "map", str(work), "work")
    run(capsys, "profile", "create", "work")
    _, out, _ = run(capsys, "which", str(work), "--json")
    assert json.loads(out)["initialized"] is True


def test_an_existing_profile_fails_and_changes_nothing(capsys):
    directory = paths.profile_dir("work")
    directory.mkdir(parents=True)
    (directory / "keep").write_text("x")
    code, _, err = run(capsys, "profile", "create", "work")
    assert code == 1
    assert "work" in err
    assert sorted(p.name for p in directory.iterdir()) == ["keep"]


def test_an_invalid_name_fails_and_creates_nothing(capsys):
    code, _, err = run(capsys, "profile", "create", "Bad_Name")
    assert code == 1
    assert "Bad_Name" in err
    assert not paths.profiles_root().exists()


def test_an_invalid_uuid_fails_and_creates_nothing(capsys):
    code, _, err = run(capsys, "profile", "create", "work", "--org-uuid", "nope")
    assert code == 1
    assert "nope" in err
    assert not paths.profiles_root().exists()


def test_dry_run_creates_nothing_and_says_what_it_would_create(capsys):
    code, out, _ = run(capsys, "profile", "create", "work", "--org-uuid", ORG, "--dry-run")
    assert code == 0
    assert str(paths.profile_dir("work")) in out
    assert ORG in out
    assert not paths.profiles_root().exists()


def test_dry_run_still_refuses_an_existing_profile(capsys):
    paths.profile_dir("work").mkdir(parents=True)
    assert run(capsys, "profile", "create", "work", "--dry-run")[0] == 1


def test_another_action_is_a_usage_error(capsys):
    code, _, _ = run(capsys, "profile", "delete", "work")
    assert code == 2


def test_a_git_failure_leaves_no_half_created_profile(capsys, monkeypatch, tmp_path):
    empty = tmp_path / "no-git"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    code, _, err = run(capsys, "profile", "create", "work")
    assert code == 1
    assert "git" in err
    assert not paths.profile_dir("work").exists()


def test_an_existing_profiles_root_keeps_its_mode(capsys):
    paths.profiles_root().mkdir(parents=True, mode=0o755)
    paths.profiles_root().chmod(0o755)
    run(capsys, "profile", "create", "work")
    assert mode(paths.profiles_root()) == 0o755
    assert mode(paths.profile_dir("work")) == 0o700
