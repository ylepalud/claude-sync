import json
import os
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_sync import converge, manifest, migration, paths, system
from claude_sync.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# The stubs' call logs, checked on their own.
STUB_LOGS = {".fake-system.log", "fake-claude.log"}


def snapshot(home: Path) -> dict:
    """Every entry under `home` but the stub logs: its kind and its content or link text."""
    entries = {}
    for directory, dirnames, filenames in os.walk(home):
        for name in dirnames + filenames:
            path = Path(directory) / name
            if name in STUB_LOGS:
                continue
            key = str(path.relative_to(home))
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


def test_init_refuses_while_the_claude_cli_runs(capsys, monkeypatch, legacy):
    monkeypatch.setenv("FAKE_PGREP_PIDS_claude", "4242 4343")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "claude 4242" in err and "claude 4343" in err
    assert snapshot(legacy.home) == before


def test_init_refuses_while_the_desktop_app_runs(capsys, monkeypatch, legacy):
    monkeypatch.setenv("FAKE_PGREP_PIDS_Claude", "77")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "Claude 77" in err
    assert snapshot(legacy.home) == before


def test_init_refuses_without_a_claude_directory(capsys, isolated_environment, fake_system):
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "~/.claude does not exist" in err
    assert not (isolated_environment / ".config").exists()


def test_init_refuses_a_symlinked_claude_directory(capsys, isolated_environment, fake_system):
    real = isolated_environment / "dotfiles" / "claude"
    real.mkdir(parents=True)
    (isolated_environment / ".claude").symlink_to(real)
    before = snapshot(isolated_environment)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "~/.claude is a symbolic link" in err
    assert snapshot(isolated_environment) == before


def test_init_refuses_when_the_default_profile_exists(capsys, legacy):
    run(capsys, "set-default", "work", "--yes")
    paths.profile_dir("work").mkdir(parents=True)
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "profile 'work' already exists" in err
    assert snapshot(legacy.home) == before


def test_init_refuses_when_the_claude_directory_has_its_own_state_file(capsys, legacy):
    (legacy.root / ".claude.json").write_text("{}\n")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "~/.claude/.claude.json exists" in err
    assert snapshot(legacy.home) == before


def test_init_refuses_across_file_systems(capsys, monkeypatch, legacy):
    claude_dir = legacy.root
    monkeypatch.setattr(system, "device", lambda path: 1 if Path(path) == claude_dir else 2)
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "not on the same file system" in err
    assert snapshot(legacy.home) == before


def test_init_refuses_without_room_for_the_backup(capsys, monkeypatch, legacy):
    (legacy.root / "projects" / "p" / "big.jsonl").write_bytes(b"x" * 10_000_000)
    monkeypatch.setattr(system, "free_bytes", lambda path: 5_000_000)
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "not enough free space" in err
    assert snapshot(legacy.home) == before


def test_init_refuses_a_plugin_it_cannot_rebuild(capsys, legacy):
    state = legacy.fake_claude.state(legacy.root)
    state["plugins"].append(
        {"id": "local@tools", "version": "1.0.0", "scope": "project", "enabled": True}
    )
    legacy.fake_claude.seed(legacy.root, state)
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "local@tools (installed at project scope)" in err
    assert "helper@tools" not in err
    assert snapshot(legacy.home) == before


def test_init_dry_run_prints_every_step_and_changes_nothing(capsys, legacy, fake_system):
    before = snapshot(legacy.home)
    code, out, _ = run(capsys, "init", "--dry-run")
    assert code == 0
    for step in (
        "back up ~/.claude and ~/.claude.json to ~/.config/claude-sync/backups/",
        "read the plugins and marketplaces of ~/.claude",
        "rename ~/.claude to ~/.config/claude-sync/profiles/perso",
        "rename ~/.claude.json to ~/.config/claude-sync/profiles/perso/.claude.json",
        "write the migration record",
        "make the relative symbolic links that point outside ~/.claude absolute",
        "settings.json",
        "!/profile.toml",
        "~/.zshrc",
        "~/Library/LaunchAgents/io.github.ylepalud.claude-sync.env.plist",
        "remove the plugin caches and lists",
        "claude-sync apply",
        "Markdown",
    ):
        assert step in out
    assert snapshot(legacy.home) == before
    assert fake_system.calls() == []
    assert legacy.fake_claude.calls(legacy.root) == []


def test_init_dry_run_refuses_what_a_real_run_refuses(capsys, legacy):
    paths.profile_dir("perso").mkdir(parents=True)
    code, out, err = run(capsys, "init", "--dry-run")
    assert code == 1
    assert "profile 'perso' already exists" in err
    assert out == ""


migration_steps = [
    "backup",
    "import",
    "rename-claude",
    "rename-claude-json",
    "symlinks",
    "settings",
    "gitignore",
    "zshrc",
    "launch-agent",
    "plugin-caches",
    "manifest",
]


@pytest.fixture
def reset_on_cache_removal(monkeypatch, legacy):
    """Make the fake claude forget its plugins when init removes the caches, as the real one would.

    The fake claude log is emptied at that point, so it then holds the rebuild only;
    `.before` keeps the entries logged up to then. `.fail` is merged into the reset state.
    """
    real = migration.remove_plugin_caches
    reset = SimpleNamespace(fail={}, before=[])

    def remove(profile_dir):
        real(profile_dir)
        reset.before = legacy.fake_claude.log(profile_dir)
        upstream = legacy.fake_claude.state(profile_dir)["upstream"]
        legacy.fake_claude.seed(profile_dir, {"upstream": upstream, "fail": reset.fail})
        (profile_dir / "fake-claude.log").unlink()

    monkeypatch.setattr(migration, "remove_plugin_caches", remove)
    return reset


def test_init_migrates_the_configuration_into_the_default_profile(
    capsys, legacy, fake_system, reset_on_cache_removal
):
    home = legacy.home
    profile = paths.profile_dir("perso")
    rule = (legacy.root / "rules" / "r.md").read_text()
    code, out, err = run(capsys, "init", "--yes")
    assert (code, err) == (0, "")
    assert not os.path.lexists(home / ".claude")
    assert not os.path.lexists(home / ".claude.json")
    assert (profile / ".claude.json").read_text() == '{"numStartups": 3}\n'
    settings = json.loads((profile / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == f"{profile}/hooks/x.sh"
    assert settings["env"]["STATE_FILE"] == f"{home}/.claude.json"
    assert os.readlink(profile / "skills" / "out") == str(home / ".agents" / "skills" / "out")
    assert (profile / "skills" / "out" / "SKILL.md").is_file()
    assert os.readlink(profile / "skills" / "in") == "../rules"
    assert (profile / "rules" / "r.md").read_text() == rule
    assert (home / ".zshrc").read_text().count(migration.ZSHRC_BEGIN) == 1
    plist = migration.launch_agent_path()
    agent = plistlib.loads(plist.read_bytes())
    assert agent["ProgramArguments"][-1] == str(profile)
    domain = f"gui/{os.getuid()}"
    assert [c for c in fake_system.calls() if c[0] == "launchctl"] == [
        ["launchctl", "bootout", f"{domain}/{migration.LAUNCH_AGENT_LABEL}"],
        ["launchctl", "bootstrap", domain, str(plist)],
    ]
    assert [p.name for p in (paths.config_home() / "backups").iterdir()][0].endswith(".tar.gz")
    calls = legacy.fake_claude.calls(profile)
    assert ["plugin", "marketplace", "add", "perso/tools"] in calls
    assert ["plugin", "install", "helper@tools", "--scope", "user"] in calls
    assert [p["id"] for p in legacy.fake_claude.state(profile)["plugins"]] == ["helper@tools"]
    assert manifest.load(profile / manifest.MANIFEST_FILE).plugins == (
        manifest.Plugin("helper@tools", "1.0.0", True),
    )
    tracked = subprocess.run(
        ["git", "-C", str(profile), "check-ignore", "-q", "profile.toml"], check=False
    )
    assert tracked.returncode == 1
    assert "  ~/.config/claude-sync/profiles/perso/rules/r.md\n" in out
    assert "/login" in out
    record = migration.Record.load(profile)
    assert record.old_root == str(home / ".claude")
    assert record.steps == [*migration_steps, "apply"]
    assert record.settings_keys == ["/hooks/PreToolUse/0/hooks/0/command"]
    assert record.links == [(Path("skills/out"), "../../.agents/skills/out")]
    assert record.plist == str(plist)


def test_a_failing_plugin_rebuild_is_a_warning_with_exit_4(
    capsys, legacy, fake_system, reset_on_cache_removal
):
    reset_on_cache_removal.fail["plugin install"] = "network is unreachable"
    profile = paths.profile_dir("perso")
    code, out, err = run(capsys, "init", "--yes")
    assert code == 4
    assert "network is unreachable" in err
    assert "run claude-sync apply" in err
    assert ["plugin", "install", "helper@tools", "--scope", "user"] in (
        legacy.fake_claude.calls(profile)
    )
    assert not os.path.lexists(legacy.home / ".claude")
    assert (profile / ".claude.json").is_file()
    assert manifest.load(profile / manifest.MANIFEST_FILE).plugins
    assert migration.Record.load(profile).steps == migration_steps
    assert "/login" in out


@pytest.fixture
def failing_second_rename(monkeypatch, legacy):
    """Make the rename of ~/.claude.json fail, right after ~/.claude was moved.

    Returns a dict; set its "on" key to False to stop failing.
    """
    real = os.rename
    state_file = legacy.home / ".claude.json"
    switch = {"on": True}

    def rename(source, destination, *args, **kwargs):
        if switch["on"] and Path(source) == state_file:
            raise OSError(5, "Input/output error", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    return switch


def test_a_failure_after_the_first_rename_exits_1_with_the_uninstall_recovery(
    capsys, legacy, fake_system, failing_second_rename
):
    profile = paths.profile_dir("perso")
    code, out, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "Input/output error" in err
    assert "run `claude-sync uninstall` to move it back" in err
    assert "--from-backup" in err
    assert not os.path.lexists(legacy.home / ".claude")
    assert (legacy.home / ".claude.json").is_file()
    assert migration.Record.load(profile) == migration.Record(
        str(legacy.home / ".claude"), steps=["backup", "import", "rename-claude"]
    )
    assert not (legacy.home / ".zshrc").exists()
    assert [c for c in fake_system.calls() if c[0] == "launchctl"] == []


def test_a_failure_before_the_first_rename_says_nothing_was_moved(capsys, legacy, fake_system):
    backups = paths.config_home() / "backups"
    backups.parent.mkdir(parents=True)
    backups.write_text("not a directory\n")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "init stopped before moving anything: ~/.claude and ~/.claude.json are unchanged" in err
    assert snapshot(legacy.home) == before


@pytest.mark.parametrize("flag", ["--yes", "--dry-run"])
def test_init_refuses_without_a_claude_state_file(capsys, legacy, fake_system, flag):
    (legacy.home / ".claude.json").unlink()
    before = snapshot(legacy.home)
    code, out, err = run(capsys, "init", flag)
    assert code == 1
    assert "~/.claude.json does not exist" in err
    assert out == ""
    assert snapshot(legacy.home) == before


def test_a_failing_launch_agent_load_is_recorded_for_uninstall(
    capsys, monkeypatch, legacy, fake_system
):
    monkeypatch.setenv("FAKE_LAUNCHCTL_EXIT", "5")
    profile = paths.profile_dir("perso")
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "launchctl bootstrap" in err and "claude-sync uninstall" in err
    assert [c[1] for c in fake_system.calls() if c[0] == "launchctl"] == ["bootout", "bootstrap"]
    record = migration.Record.load(profile)
    assert record.plist == str(migration.launch_agent_path())
    assert record.steps == migration_steps[: migration_steps.index("launch-agent")]


def test_uninstall_recovers_from_a_failure_after_the_first_rename(
    capsys, legacy, fake_system, failing_second_rename
):
    before = snapshot(legacy.home / ".claude")
    assert run(capsys, "init", "--yes")[0] == 1
    failing_second_rename["on"] = False
    code, _, err = run(capsys, "uninstall", "--yes")
    assert (code, err) == (0, "")
    assert snapshot(legacy.home / ".claude") == before
    assert (legacy.home / ".claude.json").read_text() == '{"numStartups": 3}\n'
    assert not paths.profile_dir("perso").exists()


def test_init_without_yes_and_without_a_tty_exits_3_and_changes_nothing(
    capsys, monkeypatch, legacy, fake_system
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    before = snapshot(legacy.home)
    code, out, err = run(capsys, "init")
    assert code == 3
    assert "rename ~/.claude to ~/.config/claude-sync/profiles/perso" in out
    assert "rerun with --yes" in err
    assert snapshot(legacy.home) == before


def test_init_declined_changes_nothing(capsys, monkeypatch, legacy, fake_system):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init")
    assert code == 0
    assert "cancelled" in err
    assert snapshot(legacy.home) == before


def test_init_reads_claude_with_the_config_dir_unset_and_creates_no_inner_state_file(
    capsys, monkeypatch, legacy, fake_system, reset_on_cache_removal
):
    monkeypatch.setenv("FAKE_CLAUDE_WRITES_STATE", "1")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert run(capsys, "init", "--dry-run")[0] == 0
    assert run(capsys, "init")[0] == 0
    assert not os.path.lexists(legacy.root / ".claude.json")
    entries = legacy.fake_claude.log(legacy.root)
    assert entries and all(entry["config_dir_env"] is None for entry in entries)
    assert run(capsys, "init", "--yes")[0] == 0
    assert all(entry["config_dir_env"] is None for entry in reset_on_cache_removal.before)
    assert len(reset_on_cache_removal.before) > len(entries)


def test_a_failure_before_the_first_record_moves_the_configuration_back(
    capsys, monkeypatch, legacy, fake_system
):
    def save(record, profile_dir):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(migration.Record, "save", save)
    before = snapshot(legacy.root)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "No space left on device" in err
    assert "init stopped before moving anything: ~/.claude and ~/.claude.json are unchanged" in err
    assert snapshot(legacy.root) == before
    assert not os.path.lexists(paths.profile_dir("perso"))


def test_a_configuration_that_cannot_be_moved_back_points_to_the_backup(
    capsys, monkeypatch, legacy, fake_system
):
    def save(record, profile_dir):
        raise OSError(28, "No space left on device")

    real = os.rename
    profile = paths.profile_dir("perso")

    def rename(source, destination, *args, **kwargs):
        if Path(source) == profile:
            raise OSError(16, "Resource busy", str(source))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(migration.Record, "save", save)
    monkeypatch.setattr(os, "rename", rename)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "could not rename it back" in err and "uninstall --from-backup" in err
    assert profile.is_dir() and not os.path.lexists(legacy.root)


def test_links_rewritten_before_a_failure_are_recorded(capsys, monkeypatch, legacy, fake_system):
    other = legacy.home / ".agents" / "skills" / "other"
    other.mkdir()
    (legacy.root / "skills" / "other").symlink_to("../../.agents/skills/other")
    profile = paths.profile_dir("perso")
    real = os.replace
    rewritten = []

    def replace(source, destination, *args, **kwargs):
        if Path(destination).parent == profile / "skills":
            if rewritten:
                raise OSError(5, "Input/output error", str(destination))
            rewritten.append(Path(destination).name)
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "claude-sync uninstall" in err
    record = migration.Record.load(profile)
    assert record.steps[-1] == "rename-claude-json"
    name = rewritten[0]
    assert os.readlink(profile / "skills" / name).startswith("/")
    assert (Path("skills") / name, f"../../.agents/skills/{name}") in record.links


def interrupt(*args, **kwargs):
    raise KeyboardInterrupt


def test_an_interrupt_after_the_renames_exits_130_with_the_uninstall_recovery(
    capsys, monkeypatch, legacy, fake_system
):
    monkeypatch.setattr(migration, "rewrite_settings", interrupt)
    profile = paths.profile_dir("perso")
    code, _, err = run(capsys, "init", "--yes")
    assert code == 130
    assert "run `claude-sync uninstall` to move it back" in err
    assert migration.Record.load(profile).steps[-1] == "symlinks"


def test_an_interrupt_during_the_rebuild_exits_130_with_the_apply_hint(
    capsys, monkeypatch, legacy, fake_system, reset_on_cache_removal
):
    monkeypatch.setattr(converge, "converge", interrupt)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 130
    assert "run claude-sync apply" in err
    assert migration.Record.load(paths.profile_dir("perso")).steps == migration_steps


def test_a_shell_block_the_user_already_had_is_not_recorded(
    capsys, legacy, fake_system, reset_on_cache_removal
):
    zshrc = legacy.home / ".zshrc"
    zshrc.write_text("export A=1\n" + migration.ZSHRC_BLOCK)
    before = zshrc.read_text()
    assert run(capsys, "init", "--yes")[0] == 0
    assert zshrc.read_text() == before
    steps = migration.Record.load(paths.profile_dir("perso")).steps
    assert "zshrc" not in steps and "launch-agent" in steps


def test_init_refuses_unreadable_plugin_list_output(capsys, legacy, fake_system):
    state = legacy.fake_claude.state(legacy.root)
    state["output"] = {"plugin list": "Update available!"}
    legacy.fake_claude.seed(legacy.root, state)
    before = snapshot(legacy.home)
    code, _, err = run(capsys, "init", "--yes")
    assert code == 1
    assert "`claude plugin list --json` printed invalid JSON" in err
    assert snapshot(legacy.home) == before


def test_a_manifest_rule_the_user_already_had_is_not_recorded(
    capsys, legacy, fake_system, reset_on_cache_removal
):
    gitignore = legacy.root / ".gitignore"
    gitignore.write_text(gitignore.read_text() + migration.MANIFEST_RULE + "\n")
    before = gitignore.read_text()
    assert run(capsys, "init", "--yes")[0] == 0
    profile = paths.profile_dir("perso")
    assert (profile / ".gitignore").read_text() == before
    steps = migration.Record.load(profile).steps
    assert "gitignore" not in steps and "zshrc" in steps
