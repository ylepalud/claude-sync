import os
from pathlib import Path

import pytest

from claude_sync import paths
from claude_sync.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def snapshot(root: Path) -> dict:
    """Every entry under `root` but the stub log: its kind and its content or link text."""
    entries = {}
    for directory, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(directory) / name
            if name == ".fake-system.log":
                continue
            key = str(path.relative_to(root))
            if path.is_symlink():
                entries[key] = ("link", os.readlink(path))
            elif path.is_dir():
                entries[key] = ("dir",)
            else:
                entries[key] = ("file", path.read_bytes())
    return entries


@pytest.fixture
def profile(fake_system):
    """The initialized default profile, with a skill and a settings file."""
    directory = paths.profile_dir("perso")
    (directory / "skills" / "old-skill").mkdir(parents=True)
    (directory / "skills" / "old-skill" / "SKILL.md").write_text("# old\n")
    (directory / "settings.json").write_text('{"profile": true}\n')
    (directory / ".claude.json").write_text('{"numStartups": 9}\n')
    return directory


@pytest.fixture
def stray(isolated_environment):
    """`~/.claude`, recreated after the migration."""
    return isolated_environment / ".claude"


def test_adopt_moves_a_new_skill_and_removes_the_empty_directory(capsys, profile, stray):
    (stray / "skills" / "new-skill").mkdir(parents=True)
    (stray / "skills" / "new-skill" / "SKILL.md").write_text("# new\n")
    code, out, err = run(capsys, "adopt", "--yes")
    assert (code, err) == (0, "")
    assert (profile / "skills" / "new-skill" / "SKILL.md").read_text() == "# new\n"
    assert (profile / "skills" / "old-skill" / "SKILL.md").read_text() == "# old\n"
    assert not os.path.lexists(stray)
    assert "~/.claude/skills/new-skill" in out


def test_adopt_reports_a_conflict_and_keeps_both_files(capsys, profile, stray):
    stray.mkdir()
    (stray / "settings.json").write_text('{"stray": true}\n')
    code, out, err = run(capsys, "adopt", "--yes")
    assert code == 0
    assert "conflict: ~/.claude/settings.json" in out
    assert (stray / "settings.json").read_text() == '{"stray": true}\n'
    assert (profile / "settings.json").read_text() == '{"profile": true}\n'
    assert "~/.claude is kept" in out


def test_nothing_to_adopt_exits_0_with_a_message(capsys, monkeypatch, profile):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # no confirmation asked
    before = snapshot(Path.home())
    code, out, err = run(capsys, "adopt")
    assert (code, err) == (0, "")
    assert out == "nothing to adopt: neither ~/.claude nor ~/.claude.json exists\n"
    assert snapshot(Path.home()) == before


def test_adopt_moves_the_state_file_when_the_profile_has_none(capsys, profile, stray):
    (profile / ".claude.json").unlink()
    (Path.home() / ".claude.json").write_text('{"numStartups": 1}\n')
    code, out, err = run(capsys, "adopt", "--yes")
    assert (code, err) == (0, "")
    assert (profile / ".claude.json").read_text() == '{"numStartups": 1}\n'
    assert not os.path.lexists(Path.home() / ".claude.json")
    assert "move ~/.claude.json to ~/.config/claude-sync/profiles/perso/.claude.json" in out


def test_adopt_keeps_the_state_file_when_the_profile_has_one(capsys, profile, stray):
    (Path.home() / ".claude.json").write_text('{"numStartups": 1}\n')
    code, out, err = run(capsys, "adopt", "--yes")
    assert code == 0
    assert "conflict: ~/.claude.json" in out
    assert (Path.home() / ".claude.json").read_text() == '{"numStartups": 1}\n'
    assert (profile / ".claude.json").read_text() == '{"numStartups": 9}\n'
    assert "nothing moved: merge or remove the conflicting entries by hand" in out


def test_two_state_files_never_replace_each_other(capsys, profile, stray):
    (profile / ".claude.json").unlink()
    stray.mkdir()
    (stray / ".claude.json").write_text('{"inner": true}\n')
    (Path.home() / ".claude.json").write_text('{"outer": true}\n')
    code, out, _ = run(capsys, "adopt", "--yes")
    assert code == 0
    assert (profile / ".claude.json").read_text() == '{"inner": true}\n'
    assert (Path.home() / ".claude.json").read_text() == '{"outer": true}\n'
    assert "conflict: ~/.claude.json" in out


def test_adopt_refuses_while_claude_runs(capsys, monkeypatch, profile, stray):
    (stray / "skills" / "new-skill").mkdir(parents=True)
    monkeypatch.setenv("FAKE_PGREP_PIDS_claude", "4242")
    before = snapshot(Path.home())
    code, _, err = run(capsys, "adopt", "--yes")
    assert code == 1
    assert "claude 4242" in err
    assert snapshot(Path.home()) == before


def test_adopt_dry_run_prints_the_moves_and_changes_nothing(capsys, profile, stray, fake_system):
    (stray / "skills" / "new-skill").mkdir(parents=True)
    (stray / "settings.json").write_text("{}\n")
    before = snapshot(Path.home())
    code, out, err = run(capsys, "adopt", "--dry-run")
    assert (code, err) == (0, "")
    assert (
        "move ~/.claude/skills/new-skill to ~/.config/claude-sync/profiles/perso/skills/new-skill"
        in out
    )
    assert "conflict: ~/.claude/settings.json" in out
    assert snapshot(Path.home()) == before
    assert fake_system.calls() == []


def test_adopt_refuses_a_symlinked_claude_directory(capsys, profile, stray):
    elsewhere = Path.home() / "dotfiles" / "claude"
    (elsewhere / "skills" / "x").mkdir(parents=True)
    stray.symlink_to(elsewhere)
    before = snapshot(Path.home())
    code, _, err = run(capsys, "adopt", "--yes")
    assert code == 1
    assert "~/.claude is a symbolic link" in err
    assert snapshot(Path.home()) == before


def test_adopt_into_another_profile(capsys, profile, stray):
    work = paths.profile_dir("work")
    work.mkdir()
    (stray / "rules").mkdir(parents=True)
    code, _, err = run(capsys, "adopt", "--profile", "work", "--yes")
    assert (code, err) == (0, "")
    assert (work / "rules").is_dir() and not (profile / "rules").exists()


def test_adopt_refuses_a_missing_profile(capsys, isolated_environment, fake_system, stray):
    (stray / "rules").mkdir(parents=True)
    code, _, err = run(capsys, "adopt", "--yes")
    assert code == 1
    assert "profile 'perso' does not exist" in err
    assert (stray / "rules").is_dir()


def test_adopt_declined_changes_nothing(capsys, monkeypatch, profile, stray):
    (stray / "rules").mkdir(parents=True)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    before = snapshot(Path.home())
    code, _, err = run(capsys, "adopt")
    assert code == 0
    assert "cancelled" in err
    assert snapshot(Path.home()) == before


def test_adopt_asks_nothing_when_only_conflicts_remain(capsys, monkeypatch, profile, stray):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    stray.mkdir()
    (stray / "settings.json").write_text("{}\n")
    code, out, _ = run(capsys, "adopt")
    assert code == 0
    assert "~/.claude is kept" in out


def test_adopt_without_yes_and_without_a_tty_exits_3_and_changes_nothing(
    capsys, monkeypatch, profile, stray
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    (stray / "rules").mkdir(parents=True)
    before = snapshot(Path.home())
    code, _, err = run(capsys, "adopt")
    assert code == 3
    assert snapshot(Path.home()) == before


def test_a_failing_move_says_what_moved_and_to_rerun(capsys, monkeypatch, profile, stray):
    (stray / "a").mkdir(parents=True)
    (stray / "b").mkdir()
    real = os.rename

    def rename(source, destination, *args, **kwargs):
        if Path(source).name == "b":
            raise OSError(18, "Cross-device link", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    code, _, err = run(capsys, "adopt", "--yes")
    assert code == 1
    assert "Cross-device link" in err
    assert "rerun claude-sync adopt" in err
    assert (profile / "a").is_dir() and (stray / "b").is_dir()


def test_a_linked_directory_in_conflict_is_kept(capsys, profile, stray):
    empty = Path.home() / "empty"
    empty.mkdir()
    (stray / "skills").mkdir(parents=True)
    (stray / "skills" / "old-skill").symlink_to(empty)
    code, out, _ = run(capsys, "adopt", "--yes")
    assert code == 0
    assert "conflict: ~/.claude/skills/old-skill" in out
    assert os.readlink(stray / "skills" / "old-skill") == str(empty)


@pytest.mark.parametrize("conflict", [False, True], ids=["empty-only", "with-conflict"])
def test_empty_directories_are_not_removed_without_a_confirmation(
    capsys, monkeypatch, profile, stray, conflict
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    (stray / "skills").mkdir(parents=True)
    if conflict:
        (stray / "settings.json").write_text("{}\n")
    before = snapshot(Path.home())
    code, out, err = run(capsys, "adopt")
    assert code == 3
    assert "remove the empty directory ~/.claude/skills" in out
    assert snapshot(Path.home()) == before


def test_adopt_lists_the_directories_it_removes(capsys, profile, stray):
    (stray / "skills" / "new-skill").mkdir(parents=True)
    (stray / "settings.json").write_text("{}\n")
    code, out, _ = run(capsys, "adopt", "--dry-run")
    assert code == 0
    assert "remove the empty directory ~/.claude/skills" in out
    assert "remove the empty directory ~/.claude\n" not in out


def test_adopt_removes_the_claude_directory_only_when_it_ends_empty(capsys, profile, stray):
    (stray / "skills" / "new-skill").mkdir(parents=True)
    code, out, _ = run(capsys, "adopt", "--dry-run")
    assert "remove the empty directory ~/.claude/skills\n" in out
    assert "remove the empty directory ~/.claude\n" in out


def test_adopt_refuses_a_claude_file(capsys, profile, stray):
    stray.write_text("not a directory\n")
    code, _, err = run(capsys, "adopt", "--yes")
    assert code == 1
    assert "~/.claude is not a directory" in err
    assert stray.read_text() == "not a directory\n"
