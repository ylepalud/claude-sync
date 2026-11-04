import json
import os
import re
import tarfile
from pathlib import Path

import pytest

from claude_sync import migration, paths, system
from claude_sync.cli import main
from claude_sync.commands import uninstall
from claude_sync.context import Context
from claude_sync.errors import ClaudeSyncError


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# The stubs' call logs and the fake claude's state, checked on their own.
STUB_FILES = {".fake-system.log", "fake-claude.log", "fake-claude.json"}


def snapshot(root: Path, skip=()) -> dict:
    """Every entry under `root` but the stub files and `skip` (relative paths, with their
    content): its kind and its content or link text."""
    entries = {}
    for directory, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(directory) / name
            key = str(path.relative_to(root))
            if name in STUB_FILES or any(key == s or key.startswith(s + "/") for s in skip):
                continue
            if path.is_symlink():
                entries[key] = ("link", os.readlink(path))
            elif path.is_dir():
                entries[key] = ("dir", oct(path.stat().st_mode))
            else:
                entries[key] = ("file", path.read_bytes(), oct(path.stat().st_mode))
    return entries


@pytest.fixture
def legacy(legacy_claude, fake_system):
    return legacy_claude


def test_uninstall_refuses_without_a_migration_record(capsys, legacy):
    before = snapshot(legacy.home)
    code, out, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "no migration record" in err
    assert out == ""
    assert snapshot(legacy.home) == before


@pytest.fixture
def reset_on_cache_removal(monkeypatch, legacy):
    """Make the fake claude forget its plugins when the caches are removed, as the real one would.

    The fake claude log is emptied at that point, so it then holds the rebuild only.
    The returned dict is merged into the reset state as its `fail` key.
    """
    real = migration.remove_plugin_caches
    fail = {}

    def remove(profile_dir):
        real(profile_dir)
        upstream = legacy.fake_claude.state(profile_dir)["upstream"]
        legacy.fake_claude.seed(profile_dir, {"upstream": upstream, "fail": fail})
        (profile_dir / "fake-claude.log").unlink(missing_ok=True)

    monkeypatch.setattr(migration, "remove_plugin_caches", remove)
    return fail


@pytest.fixture
def migrated(capsys, legacy, reset_on_cache_removal):
    """The legacy configuration after a successful `init --yes`."""
    assert run(capsys, "init", "--yes")[0] == 0
    return legacy


def test_uninstall_refuses_when_claude_directory_exists(capsys, migrated):
    (migrated.home / ".claude").mkdir()
    before = snapshot(migrated.home)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "~/.claude exists" in err
    assert snapshot(migrated.home) == before


@pytest.mark.parametrize("recorded", [True, False], ids=["recorded", "unrecorded"])
def test_uninstall_refuses_when_both_state_files_exist(capsys, migrated, recorded):
    profile = paths.profile_dir("perso")
    if not recorded:  # an interrupt can leave the second rename unrecorded
        record = migration.Record.load(profile)
        record.steps.remove("rename-claude-json")
        record.save(profile)
    (migrated.home / ".claude.json").write_text('{"numStartups": 1}\n')
    before = snapshot(migrated.home)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "~/.claude.json exists" in err
    assert snapshot(migrated.home) == before


def test_uninstall_refuses_when_the_record_says_the_state_file_was_moved(capsys, migrated):
    (paths.profile_dir("perso") / ".claude.json").unlink()
    (migrated.home / ".claude.json").write_text('{"numStartups": 1}\n')
    before = snapshot(migrated.home)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "~/.claude.json exists" in err
    assert snapshot(migrated.home) == before


def test_uninstall_refuses_while_claude_runs(capsys, monkeypatch, migrated):
    monkeypatch.setenv("FAKE_PGREP_PIDS_Claude", "77")
    before = snapshot(migrated.home)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "Claude 77" in err
    assert snapshot(migrated.home) == before


def test_uninstall_after_init_gives_the_configuration_back(
    capsys, legacy, fake_system, reset_on_cache_removal
):
    home, root = legacy.home, legacy.root
    skip = migration.PLUGIN_CACHES
    before = snapshot(root, skip)
    assert run(capsys, "init", "--yes")[0] == 0
    code, out, err = run(capsys, "uninstall", "--yes")
    assert (code, err) == (0, "")
    assert snapshot(root, skip) == before
    assert os.readlink(root / "skills" / "out") == "../../.agents/skills/out"
    settings = json.loads((root / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == f"{home}/.claude/hooks/x.sh"
    assert (home / ".claude.json").read_text() == '{"numStartups": 3}\n'
    assert not os.path.lexists(root / ".claude.json")
    assert not os.path.lexists(root / migration.RECORD_FILE)
    assert not os.path.lexists(paths.profile_dir("perso"))
    assert migration.ZSHRC_BEGIN not in (home / ".zshrc").read_text()
    assert not os.path.lexists(migration.launch_agent_path())
    launchctl = [c for c in fake_system.calls() if c[0] == "launchctl"]
    assert launchctl[-2:] == [
        ["launchctl", "bootout", f"gui/{os.getuid()}/{migration.LAUNCH_AGENT_LABEL}"],
        ["launchctl", "unsetenv", "CLAUDE_CONFIG_DIR"],
    ]
    entries = legacy.fake_claude.log(root)
    assert ["plugin", "install", "helper@tools", "--scope", "user"] in [e["argv"] for e in entries]
    assert all(entry["config_dir_env"] is None for entry in entries)
    assert [p["id"] for p in legacy.fake_claude.state(root)["plugins"]] == ["helper@tools"]


def test_uninstall_dry_run_prints_every_step_and_changes_nothing(capsys, migrated, fake_system):
    before = snapshot(migrated.home)
    calls = fake_system.calls()
    code, out, err = run(capsys, "uninstall", "--dry-run")
    assert (code, err) == (0, "")
    for step in (
        "unload and delete ~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist",
        "launchctl unsetenv CLAUDE_CONFIG_DIR",
        "remove the claude-sync block from ~/.zshrc",
        "in the profile's settings.json",
        "give the symbolic links init made absolute (1) their relative text back",
        "rename ~/.config/claude-sync/profiles/perso to ~/.claude",
        "rename ~/.config/claude-sync/profiles/perso/.claude.json to ~/.claude.json",
        "delete the migration record",
        "rebuild them from profile.toml with CLAUDE_CONFIG_DIR unset (network), then delete "
        "profile.toml",
        "remove !/profile.toml from the profile's .gitignore",
        "other profiles and the backups stay in place",
    ):
        assert step in out
    assert snapshot(migrated.home) == before
    assert fake_system.calls() == calls


def test_uninstall_without_yes_and_without_a_tty_exits_3_and_changes_nothing(
    capsys, monkeypatch, migrated
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    before = snapshot(migrated.home)
    code, out, err = run(capsys, "uninstall")
    assert code == 3
    assert "rename ~/.config/claude-sync/profiles/perso to ~/.claude" in out
    assert snapshot(migrated.home) == before


def test_uninstall_declined_changes_nothing(capsys, monkeypatch, migrated):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    before = snapshot(migrated.home)
    code, _, err = run(capsys, "uninstall")
    assert code == 0
    assert "cancelled" in err
    assert snapshot(migrated.home) == before


def test_a_failing_plugin_rebuild_is_a_warning_with_exit_4(
    capsys, migrated, reset_on_cache_removal
):
    reset_on_cache_removal["plugin install"] = "network is unreachable"
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 4
    assert "network is unreachable" in err
    assert "claude plugin install" in err
    assert (migrated.root / "profile.toml").is_file()
    assert (migrated.root / "settings.json").is_file()
    assert (migrated.home / ".claude.json").is_file()
    assert not os.path.lexists(paths.profile_dir("perso"))


def test_a_failure_before_the_profile_moves_back_can_be_retried(capsys, monkeypatch, migrated):
    real = os.rename
    profile = paths.profile_dir("perso")

    def rename(source, destination, *args, **kwargs):
        if Path(source) == profile:
            raise OSError(16, "Resource busy", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "Resource busy" in err
    assert "rerun `claude-sync uninstall`" in err
    assert migration.Record.load(profile) is not None
    monkeypatch.setattr(os, "rename", real)
    assert run(capsys, "uninstall", "--yes")[0] == 0
    assert os.readlink(migrated.root / "skills" / "out") == "../../.agents/skills/out"
    assert not os.path.lexists(migrated.root / migration.RECORD_FILE)


def test_a_failure_after_the_profile_moved_back_says_what_is_left(capsys, monkeypatch, migrated):
    real = os.rename
    inner = migrated.root / ".claude.json"

    def rename(source, destination, *args, **kwargs):
        if Path(source) == inner:
            raise OSError(5, "Input/output error", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "Input/output error" in err
    assert "move ~/.claude/.claude.json to ~/.claude.json" in err
    assert "delete ~/.claude/.claude-sync-migration.json" in err
    assert inner.is_file()


@pytest.fixture
def half_migrated(capsys, monkeypatch, legacy):
    """A migration that failed after renaming ~/.claude, before moving ~/.claude.json.

    Returns the snapshot of ~/.claude taken before init.
    """
    before = snapshot(legacy.root)
    real = os.rename
    state_file = legacy.home / ".claude.json"

    def rename(source, destination, *args, **kwargs):
        if Path(source) == state_file:
            raise OSError(5, "Input/output error", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    assert run(capsys, "init", "--yes")[0] == 1
    monkeypatch.setattr(os, "rename", real)
    return before


def test_from_backup_moves_the_leftovers_aside_and_restores_the_backup(
    capsys, legacy, fake_system, half_migrated
):
    home = legacy.home
    profile = paths.profile_dir("perso")
    code, out, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert (code, err) == (0, "")
    assert snapshot(legacy.root) == half_migrated
    assert (home / ".claude.json").read_text() == '{"numStartups": 3}\n'
    [json_aside] = home.glob(".claude.json.failed-*")
    assert json_aside.read_text() == '{"numStartups": 3}\n'
    [profile_aside] = profile.parent.glob("perso.failed-*")
    assert (profile_aside / migration.RECORD_FILE).is_file()
    assert not os.path.lexists(profile)
    launchctl = [c for c in fake_system.calls() if c[0] == "launchctl"]
    assert launchctl == [
        ["launchctl", "bootout", f"gui/{os.getuid()}/{migration.LAUNCH_AGENT_LABEL}"],
        ["launchctl", "unsetenv", "CLAUDE_CONFIG_DIR"],
    ]


def test_from_backup_refuses_while_claude_runs(capsys, monkeypatch, legacy, half_migrated):
    monkeypatch.setenv("FAKE_PGREP_PIDS_claude", "4242")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "claude 4242" in err
    assert snapshot(legacy.home) == before


def test_from_backup_dry_run_prints_every_step_and_changes_nothing(
    capsys, legacy, fake_system, half_migrated
):
    before = snapshot(legacy.home)
    calls = fake_system.calls()
    code, out, err = run(capsys, "uninstall", "--from-backup", "--dry-run")
    assert (code, err) == (0, "")
    for step in (
        "launchctl unsetenv CLAUDE_CONFIG_DIR",
        "rename ~/.claude.json to ~/.claude.json.failed-",
        "rename ~/.config/claude-sync/profiles/perso to "
        "~/.config/claude-sync/profiles/perso.failed-",
        "extract ~/.config/claude-sync/backups/",
    ):
        assert step in out
    assert "rename ~/.claude to" not in out
    assert "~/.zshrc" not in out  # init never added the block
    assert snapshot(legacy.home) == before
    assert fake_system.calls() == calls


def test_from_backup_without_a_backup_refuses(capsys, legacy):
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "no backup in ~/.config/claude-sync/backups" in err
    assert snapshot(legacy.home) == before


def test_from_backup_restores_the_file_given(capsys, legacy, half_migrated):
    backups = paths.config_home() / "backups"
    [latest] = backups.iterdir()
    given = latest.rename(backups.parent / "chosen.tar.gz")
    (backups / "29991231T000000Z.tar.gz").write_bytes(b"not a tar archive")
    code, _, err = run(capsys, "uninstall", "--from-backup", str(given), "--yes")
    assert (code, err) == (0, "")
    assert snapshot(legacy.root) == half_migrated


def test_from_backup_refuses_an_unreadable_archive_before_moving_anything(
    capsys, legacy, half_migrated
):
    backups = paths.config_home() / "backups"
    (backups / "29991231T000000Z.tar.gz").write_bytes(b"not a tar archive")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "cannot read the backup ~/.config/claude-sync/backups/29991231T000000Z.tar.gz" in err
    assert snapshot(legacy.home) == before


def test_from_backup_refuses_an_escaping_member_before_moving_anything(
    capsys, legacy, half_migrated
):
    archive = paths.config_home() / "backups" / "29991231T000000Z.tar.gz"
    payload = legacy.home / "payload"
    payload.write_text("x\n")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload, arcname="../escaped")
    payload.unlink()
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "../escaped" in err
    assert snapshot(legacy.home) == before


def test_a_shell_block_the_user_already_had_stays(capsys, legacy, reset_on_cache_removal):
    zshrc = legacy.home / ".zshrc"
    zshrc.write_text("export A=1\n" + migration.ZSHRC_BLOCK)
    assert run(capsys, "init", "--yes")[0] == 0
    code, out, _ = run(capsys, "uninstall", "--yes")
    assert code == 0
    assert zshrc.read_text() == "export A=1\n" + migration.ZSHRC_BLOCK
    assert "~/.zshrc" not in out


def test_an_agent_that_is_not_loaded_does_not_stop_uninstall(capsys, monkeypatch, migrated):
    real = system.launchctl

    def launchctl(*args):
        if args[0] == "bootout":
            raise ClaudeSyncError("`launchctl bootout` failed: No such process")
        return real(*args)

    monkeypatch.setattr(system, "launchctl", launchctl)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert (code, err) == (0, "")
    assert not os.path.lexists(migration.launch_agent_path())


def test_from_backup_declined_changes_nothing(capsys, monkeypatch, legacy, half_migrated):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup")
    assert code == 0
    assert "cancelled" in err
    assert snapshot(legacy.home) == before


def test_from_backup_refuses_a_missing_file(capsys, legacy, half_migrated):
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup", str(legacy.home / "nope.tar.gz"))
    assert code == 1
    assert "cannot read the backup ~/nope.tar.gz" in err
    assert snapshot(legacy.home) == before


@pytest.mark.parametrize("name", [".claude", ".claude.json"])
def test_an_entry_created_during_the_prompt_is_never_replaced(capsys, monkeypatch, migrated, name):
    created = migrated.home / name

    def confirm(self, question):
        created.write_text("created while the prompt was open\n")
        return True

    monkeypatch.setattr(Context, "confirm", confirm)
    profile = paths.profile_dir("perso")
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert f"~/{name} exists" in err
    assert "rerun `claude-sync uninstall`" in err and "adopt" in err
    assert created.read_text() == "created while the prompt was open\n"
    assert (profile / ".claude.json").read_text() == '{"numStartups": 3}\n'
    assert migration.Record.load(profile) is not None


def interrupt(*args, **kwargs):
    raise KeyboardInterrupt


def test_an_interrupt_before_the_profile_moves_back_exits_130_with_the_rerun_text(
    capsys, monkeypatch, migrated
):
    monkeypatch.setattr(migration, "relativize_symlinks", interrupt)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 130
    assert "rerun `claude-sync uninstall`" in err
    assert migration.Record.load(paths.profile_dir("perso")) is not None


@pytest.fixture
def interrupted_after_the_profile_moved_back(capsys, monkeypatch, migrated):
    real = os.rename
    inner = migrated.root / ".claude.json"

    def rename(source, destination, *args, **kwargs):
        if Path(source) == inner:
            raise KeyboardInterrupt
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    code, _, err = run(capsys, "uninstall", "--yes")
    monkeypatch.setattr(os, "rename", real)
    return code, err


def test_an_interrupt_after_the_profile_moved_back_says_what_is_left(
    interrupted_after_the_profile_moved_back,
):
    code, err = interrupted_after_the_profile_moved_back
    assert code == 130
    assert "move ~/.claude/.claude.json to ~/.claude.json" in err


def test_a_rerun_after_an_interrupted_finish_says_the_profile_was_moved_back(
    capsys, migrated, interrupted_after_the_profile_moved_back
):
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "already moved back to ~/.claude" in err
    assert "move ~/.claude/.claude.json to ~/.claude.json" in err


def test_a_rerun_after_a_complete_uninstall_finds_no_record(capsys, migrated):
    assert run(capsys, "uninstall", "--yes")[0] == 0
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 1
    assert "no migration record" in err


def test_an_interrupt_during_the_rebuild_exits_130_with_the_plugin_hint(
    capsys, monkeypatch, migrated
):
    monkeypatch.setattr(uninstall.converge, "converge", interrupt)
    code, _, err = run(capsys, "uninstall", "--yes")
    assert code == 130
    assert "claude plugin install" in err
    assert (migrated.root / "profile.toml").is_file()


def test_from_backup_keeps_a_shell_block_init_did_not_add(capsys, legacy, half_migrated):
    zshrc = legacy.home / ".zshrc"
    zshrc.write_text("export A=1\n" + migration.ZSHRC_BLOCK)
    assert run(capsys, "uninstall", "--from-backup", "--yes")[0] == 0
    assert zshrc.read_text() == "export A=1\n" + migration.ZSHRC_BLOCK


def test_from_backup_removes_the_shell_block_init_added(capsys, migrated):
    (migrated.home / ".claude.json").unlink(missing_ok=True)
    code, out, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert (code, err) == (0, "")
    assert migration.ZSHRC_BEGIN not in (migrated.home / ".zshrc").read_text()
    assert "remove the claude-sync block from ~/.zshrc" in out


def test_from_backup_ignores_a_damaged_record(capsys, legacy, half_migrated):
    profile = paths.profile_dir("perso")
    (profile / migration.RECORD_FILE).write_text("{")
    zshrc = legacy.home / ".zshrc"
    zshrc.write_text(migration.ZSHRC_BLOCK)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert (code, err) == (0, "")
    assert snapshot(legacy.root) == half_migrated
    assert zshrc.read_text() == migration.ZSHRC_BLOCK


def test_a_from_backup_failure_after_moving_aside_lists_what_moved(
    capsys, monkeypatch, legacy, half_migrated
):
    def extract(archive, dest):
        raise ClaudeSyncError("disk full")

    monkeypatch.setattr(migration, "extract_backup", extract)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "disk full" in err
    [json_aside] = legacy.home.glob(".claude.json.failed-*")
    assert f"~/{json_aside.name}" in err
    assert "nothing was deleted" in err
    assert "rerun `claude-sync uninstall --from-backup`" in err


def test_from_backup_never_replaces_an_earlier_failed_copy(
    capsys, monkeypatch, legacy, half_migrated
):
    monkeypatch.setattr(uninstall, "_failed_suffix", lambda: ".failed-x")
    earlier = legacy.home / ".claude.json.failed-x"
    earlier.write_text("earlier\n")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "~/.claude.json.failed-x exists" in err
    assert snapshot(legacy.home) == before


def test_the_failed_suffix_has_microseconds():
    assert re.fullmatch(r"\.failed-\d{8}T\d{12}Z", uninstall._failed_suffix())


def test_a_manifest_rule_the_user_already_had_stays(capsys, legacy, reset_on_cache_removal):
    gitignore = legacy.root / ".gitignore"
    gitignore.write_text(gitignore.read_text() + migration.MANIFEST_RULE + "\n")
    before = gitignore.read_text()
    assert run(capsys, "init", "--yes")[0] == 0
    code, out, _ = run(capsys, "uninstall", "--yes")
    assert code == 0
    assert gitignore.read_text() == before
    assert "from the profile's .gitignore" not in out


def test_from_backup_restores_the_latest_of_two_backups(capsys, legacy, half_migrated):
    older = paths.backups_dir() / "19700101T000000Z.tar.gz"
    payload = legacy.home / "payload"
    payload.write_text('{"older": true}\n')
    with tarfile.open(older, "w:gz") as tar:
        tar.add(payload, arcname=".claude.json")
    payload.unlink()
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert (code, err) == (0, "")
    assert (legacy.home / ".claude.json").read_text() == '{"numStartups": 3}\n'
    assert snapshot(legacy.root) == half_migrated


def test_a_failing_rename_aside_lists_only_what_moved(capsys, monkeypatch, legacy, half_migrated):
    real = os.rename
    profile = paths.profile_dir("perso")

    def rename(source, destination, *args, **kwargs):
        if Path(source) == profile:
            raise OSError(16, "Resource busy", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    code, _, err = run(capsys, "uninstall", "--from-backup", "--yes")
    assert code == 1
    assert "Resource busy" in err
    [json_aside] = legacy.home.glob(".claude.json.failed-*")
    assert f"moved aside: ~/{json_aside.name}; nothing was deleted" in err
    assert "perso.failed-" not in err
    assert profile.is_dir()


def test_rebuild_drift_says_the_upstream_versions_were_kept(capsys, migrated):
    manifest_file = paths.profile_dir("perso") / "profile.toml"
    manifest_file.write_text(manifest_file.read_text().replace('"1.0.0"', '"0.9.0"'))
    code, out, err = run(capsys, "uninstall", "--yes")
    assert code == 4
    assert "accept with: claude-sync import" not in out + err
    assert "the plugins were rebuilt with the upstream versions" in out
    assert not os.path.lexists(migrated.root / "profile.toml")


def test_uninstall_never_clones_or_relinks_declared_skills(
    capsys, legacy, fake_system, skill_lock, reset_on_cache_removal
):
    skill_lock(
        {
            "out": {
                "source": "acme/skills",
                "sourceType": "github",
                "skillPath": "skills/out/SKILL.md",
                "skillFolderHash": "b" * 40,
            }
        }
    )
    assert run(capsys, "init", "--yes")[0] == 0
    code, _, err = run(capsys, "uninstall", "--yes")
    assert (code, err) == (0, "")
    assert os.readlink(legacy.root / "skills" / "out") == "../../.agents/skills/out"
    assert not (paths.config_home() / "sources").exists()


def test_uninstall_leaves_mcp_servers_alone(capsys, migrated, fake_keychain):
    from claude_sync import manifest

    file = paths.profile_dir("perso") / manifest.MANIFEST_FILE
    file.write_text(
        file.read_text()
        + '\n[[mcp]]\nname = "remote"\ntransport = "http"\nurl = "https://example.test/mcp"\n'
        + '[mcp.headers]\nAuthorization = "keychain:svc-x"\n'
    )
    code, _, _ = run(capsys, "uninstall", "--yes")
    assert code == 0
    argv = [e["argv"] for e in migrated.fake_claude.log(migrated.root)]
    assert not [a for a in argv if a[0] == "mcp"]
    assert fake_keychain.calls() == []
