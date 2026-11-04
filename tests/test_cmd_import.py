from pathlib import Path

import pytest

from claude_sync import manifest, paths
from claude_sync.cli import main

ORG = "00000000-0000-0000-0000-000000000000"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def source(fake_claude, tmp_path):
    """A configuration directory with a GitHub marketplace at a known commit."""
    repo, commit = fake_claude.make_upstream("tools", {"lint": "1.0.0"})
    directory = tmp_path / "source"
    fake_claude.seed(
        directory,
        {
            "marketplaces": [
                {
                    "name": "tools",
                    "source": "github",
                    "repo": "acme/tools",
                    "ref": "main",
                    "installLocation": str(repo),
                }
            ],
            "plugins": [
                {"id": "lint@tools", "version": "1.0.0", "scope": "user", "enabled": True},
                {"id": "fmt@tools", "version": "2.0.0", "scope": "user", "enabled": False},
            ],
        },
    )
    return directory, commit


def state_of(fake_claude, directory, **extra):
    state = fake_claude.state(directory)
    state.update(extra)
    fake_claude.seed(directory, state)


def test_output_dash_prints_only_the_manifest(capsys, source):
    directory, commit = source
    code, out, err = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert code == 0
    assert err == ""
    assert out == (
        '[[marketplace]]\nname = "tools"\nsource = "github:acme/tools"\n'
        f'ref = "main"\ncommit = "{commit}"\n\n'
        '[[plugin]]\nid = "fmt@tools"\nversion = "2.0.0"\nenabled = false\n\n'
        '[[plugin]]\nid = "lint@tools"\nversion = "1.0.0"\nenabled = true\n'
    )


def test_import_before_migration_creates_nothing(capsys, source):
    directory, _ = source
    code, _, _ = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert code == 0
    assert not paths.config_home().exists()


def test_a_marketplace_without_a_ref_has_none(capsys, source, fake_claude):
    directory, _ = source
    state = fake_claude.state(directory)
    del state["marketplaces"][0]["ref"]
    fake_claude.seed(directory, state)
    _, out, _ = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert "ref" not in out


def test_a_copy_that_is_not_a_repository_has_no_commit(capsys, source, fake_claude, tmp_path):
    directory, _ = source
    plain = tmp_path / "plain"
    plain.mkdir()
    state = fake_claude.state(directory)
    state["marketplaces"][0]["installLocation"] = str(plain)
    fake_claude.seed(directory, state)
    _, out, _ = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert "commit" not in out


def test_a_path_source_uses_tilde_and_never_a_commit(capsys, fake_claude, tmp_path):
    local = paths.normalize("~/Dev/local-market")
    local.mkdir(parents=True)
    directory = tmp_path / "source"
    fake_claude.seed(
        directory,
        {
            "marketplaces": [
                {
                    "name": "local",
                    "source": "directory",
                    "path": str(local),
                    "installLocation": str(local),
                }
            ],
            "plugins": [],
        },
    )
    _, out, _ = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert 'source = "path:~/Dev/local-market"' in out
    assert "commit" not in out


def test_a_path_source_outside_home_stays_absolute(capsys, fake_claude, tmp_path):
    local = tmp_path / "elsewhere"
    local.mkdir()
    directory = tmp_path / "source"
    fake_claude.seed(
        directory,
        {
            "marketplaces": [
                {
                    "name": "local",
                    "source": "directory",
                    "path": str(local),
                    "installLocation": str(local),
                }
            ],
            "plugins": [],
        },
    )
    _, out, _ = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert f'source = "path:{local}"' in out


def test_file_and_claude_ai_sources_are_skipped_with_a_warning(capsys, source, fake_claude):
    directory, _ = source
    state = fake_claude.state(directory)
    state["marketplaces"] += [
        {"name": "single", "source": "file", "path": "/x/m.json", "installLocation": "/x"},
        {"name": "hosted", "source": "claudeai", "installLocation": "/y"},
    ]
    state["plugins"].append({"id": "p@single", "version": "1", "scope": "user", "enabled": True})
    fake_claude.seed(directory, state)
    code, out, err = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert code == 0
    assert "single" in err and "hosted" in err
    assert "single" not in out and "hosted" not in out
    parsed = tmp_manifest(out)
    assert [m.name for m in parsed.marketplaces] == ["tools"]
    assert [p.id for p in parsed.plugins] == ["fmt@tools", "lint@tools"]


def tmp_manifest(text):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "profile.toml"
        file.write_text(text)
        return manifest.load(file)


def test_output_file_is_written_privately(capsys, source, tmp_path):
    directory, commit = source
    target = tmp_path / "out" / "m.toml"
    code, out, _ = run(capsys, "import", "--source", str(directory), "--output", str(target))
    assert code == 0
    assert str(target) in out
    assert manifest.load(target).marketplaces[0].commit == commit
    assert target.stat().st_mode & 0o777 == 0o600


def test_overwriting_a_file_needs_a_confirmation(capsys, source, tmp_path):
    directory, _ = source
    target = tmp_path / "m.toml"
    target.write_text("# mine\n")
    code, _, err = run(capsys, "import", "--source", str(directory), "--output", str(target))
    assert code == 3
    assert target.read_text() == "# mine\n"
    assert str(target) in err


def test_yes_overwrites(capsys, source, tmp_path):
    directory, _ = source
    target = tmp_path / "m.toml"
    target.write_text("")
    code, _, _ = run(capsys, "import", "--source", str(directory), "--output", str(target), "--yes")
    assert code == 0
    assert manifest.load(target).plugins


def test_an_existing_account_is_kept(capsys, source, tmp_path):
    directory, _ = source
    target = tmp_path / "m.toml"
    target.write_text(f'[account]\norg_uuid = "{ORG}"\n')
    run(capsys, "import", "--source", str(directory), "--output", str(target), "--yes")
    assert manifest.load(target).account == manifest.Account(ORG)


def test_dry_run_writes_nothing_and_does_not_ask(capsys, source, tmp_path):
    directory, _ = source
    target = tmp_path / "m.toml"
    target.write_text("# mine\n")
    code, out, _ = run(
        capsys, "import", "--source", str(directory), "--output", str(target), "--dry-run"
    )
    assert code == 0
    assert str(target) in out
    assert target.read_text() == "# mine\n"


def test_default_output_is_the_profile_manifest_read_from_the_profile(capsys, fake_claude):
    profile = paths.profile_dir("work")
    repo, commit = fake_claude.make_upstream("tools", {"lint": "1.0.0"})
    fake_claude.seed(
        profile,
        {
            "marketplaces": [
                {
                    "name": "tools",
                    "source": "github",
                    "repo": "acme/tools",
                    "installLocation": str(repo),
                }
            ],
            "plugins": [{"id": "lint@tools", "version": "1.0.0", "scope": "user", "enabled": True}],
        },
    )
    code, _, _ = run(capsys, "import", "--profile", "work")
    loaded = manifest.load(profile / "profile.toml")
    assert code == 0
    assert loaded.marketplaces[0].commit == commit
    assert [p.id for p in loaded.plugins] == ["lint@tools"]


def test_without_a_profile_the_current_directory_decides(capsys, fake_claude, monkeypatch):
    work = paths.normalize("~/Dev/work")
    work.mkdir(parents=True)
    paths.config_home().mkdir(parents=True)
    paths.config_file().write_text(
        f'default = "perso"\n\n[[match]]\npath = "{paths.display(work)}"\nprofile = "work"\n'
    )
    profile = paths.profile_dir("work")
    fake_claude.seed(profile, {"marketplaces": [], "plugins": []})
    monkeypatch.chdir(work)
    code, _, _ = run(capsys, "import")
    assert code == 0
    assert (profile / "profile.toml").is_file()
    assert not paths.profile_dir("perso").exists()


def test_a_missing_profile_directory_is_refused_with_the_create_hint(capsys, fake_claude):
    code, _, err = run(capsys, "import", "--profile", "work")
    assert code == 1
    assert "claude-sync profile create work" in err
    assert not paths.profile_dir("work").exists()


def test_a_source_with_an_output_file_needs_no_profile(capsys, source, tmp_path):
    directory, _ = source
    target = tmp_path / "m.toml"
    code, _, _ = run(capsys, "import", "--source", str(directory), "--output", str(target))
    assert code == 0
    assert not paths.config_home().exists()


def test_a_source_without_output_writes_to_the_profile(capsys, source):
    directory, _ = source
    profile = paths.profile_dir("work")
    profile.mkdir(parents=True)
    code, _, _ = run(capsys, "import", "--source", str(directory), "--profile", "work")
    assert code == 0
    assert manifest.load(profile / "profile.toml").marketplaces


def test_a_failing_claude_exits_1(capsys, source, fake_claude):
    directory, _ = source
    state_of(fake_claude, directory, fail={"plugin list": "boom"})
    code, _, err = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert code == 1
    assert "boom" in err


def test_declining_the_confirmation_leaves_the_file(capsys, source, tmp_path, monkeypatch):
    directory, _ = source
    target = tmp_path / "m.toml"
    target.write_text("# mine\n")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    code, out, err = run(capsys, "import", "--source", str(directory), "--output", str(target))
    assert code == 0
    assert "wrote" not in out
    assert "cancelled" in err
    assert target.read_text() == "# mine\n"


def test_import_records_the_skills_linked_through_the_lock_file(capsys, source, skill_lock):
    directory, _ = source
    skill_lock(
        {
            "tdd": {
                "source": "acme/skills",
                "sourceType": "github",
                "skillPath": "skills/engineering/tdd/SKILL.md",
                "skillFolderHash": "a" * 40,
            }
        }
    )
    (directory / "skills").mkdir()
    (directory / "skills" / "tdd").symlink_to(Path.home() / ".agents/skills/tdd")
    code, out, _ = run(capsys, "import", "--source", str(directory), "--output", "-")
    assert code == 0
    assert out.endswith(
        '[[skill_source]]\nname = "acme-skills"\nsource = "github:acme/skills"\n\n'
        '[[skill]]\nid = "tdd@acme-skills"\npath = "skills/engineering/tdd"\n'
        f'tree = "{"a" * 40}"\n'
    )


def test_apply_then_import_then_status_is_stable(capsys, fake_claude, skills_upstream):
    directory = paths.profile_dir("perso")
    declared = manifest.Manifest(
        (),
        (),
        None,
        (manifest.SkillSource("kit", skills_upstream.source, "main", skills_upstream.first),),
        (manifest.Skill("alpha@kit", "skills/alpha", None),),
    )
    file = directory / manifest.MANIFEST_FILE
    manifest.save(file, declared)
    before = file.read_text()
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    assert run(capsys, "import", "--profile", "perso", "--yes")[0] == 0
    assert file.read_text() == before
    assert run(capsys, "status", "--profile", "perso")[0] == 0
