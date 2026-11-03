import io
import json
import os
import plistlib
import socket
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

from claude_sync import migration
from claude_sync.claude_cli import ClaudeCli
from claude_sync.errors import ClaudeSyncError
from claude_sync.sync import Observed, ObservedMarketplace, observe


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def test_legacy_claude_is_a_realistic_configuration(legacy_claude):
    root, home = legacy_claude.root, legacy_claude.home
    assert root == home / ".claude"
    assert git(root, "ls-files").split() == [
        ".gitignore",
        "plugins/installed_plugins.json",
        "plugins/known_marketplaces.json",
        "rules/r.md",
        "settings.json",
        "skills/in",
        "skills/out",
    ]
    assert git(root, "status", "--porcelain") == ""
    assert os.readlink(root / "skills" / "out") == "../../.agents/skills/out"
    assert (root / "skills" / "out" / "SKILL.md").is_file()
    assert os.readlink(root / "skills" / "in") == "../rules"
    settings = (root / "settings.json").read_text()
    assert f"{home}/.claude/hooks/x.sh" in settings
    assert f"{home}/.claude.json" in settings
    assert (root / "hooks" / "x.sh").is_file()
    assert "~/.claude/hooks" in (root / "rules" / "r.md").read_text()
    assert (root / "projects" / "p" / "s.jsonl").is_file()
    assert (home / ".claude.json").is_file()
    cli = ClaudeCli(root)
    assert [p.id for p in cli.plugins()] == ["helper@tools"]
    assert [m.name for m in cli.marketplaces()] == ["tools"]
    installed = json.loads((root / "plugins" / "installed_plugins.json").read_text())
    assert list(installed["plugins"]) == ["helper@tools"]
    known = json.loads((root / "plugins" / "known_marketplaces.json").read_text())
    assert list(known) == ["tools"]
    assert cli.marketplace_commit(str(root / "plugins" / "marketplaces" / "tools")) == (
        legacy_claude.commit
    )


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_backup_contains_both_inputs_with_mode_600(legacy_claude, tmp_path):
    home = legacy_claude.home
    archive = migration.backup([home / ".claude", home / ".claude.json"], tmp_path / "backups")
    assert archive.parent == tmp_path / "backups"
    assert archive.name.endswith(".tar.gz")
    assert mode(archive) == 0o600
    assert mode(archive.parent) == 0o700
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert ".claude.json" in names
        assert ".claude/settings.json" in names
        assert ".claude/projects/p/s.jsonl" in names
        assert not any(name.startswith("/") for name in names)
        link = tar.getmember(".claude/skills/out")
        assert link.issym() and link.linkname == "../../.agents/skills/out"
        assert tar.extractfile(".claude.json").read() == b'{"numStartups": 3}\n'


def test_backup_reports_progress_every_1000_members(tmp_path, capsys):
    tree = tmp_path / "tree"
    tree.mkdir()
    for index in range(1000):
        (tree / f"f{index}").touch()
    migration.backup([tree], tmp_path / "backups")
    assert capsys.readouterr().err.splitlines() == ["backup: 1000 entries"]


def test_backup_refuses_an_unlistable_archive(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()

    def broken(*args, **kwargs):
        raise tarfile.ReadError("truncated")

    monkeypatch.setattr(migration, "_list", broken)
    with pytest.raises(ClaudeSyncError, match="cannot be listed"):
        migration.backup([tree], tmp_path / "backups")


def test_extract_backup_restores_files_and_links(legacy_claude, tmp_path):
    home = legacy_claude.home
    archive = migration.backup([home / ".claude", home / ".claude.json"], tmp_path / "backups")
    target = tmp_path / "restore"
    target.mkdir()
    migration.extract_backup(archive, target)
    assert (target / ".claude.json").read_text() == '{"numStartups": 3}\n'
    assert os.readlink(target / ".claude" / "skills" / "out") == "../../.agents/skills/out"
    assert (target / ".claude" / "settings.json").read_bytes() == (
        (home / ".claude" / "settings.json").read_bytes()
    )


def test_extract_backup_keeps_an_absolute_symlink(tmp_path):
    tree = tmp_path / ".claude"
    tree.mkdir()
    (tree / "abs").symlink_to("/usr/bin")
    archive = migration.backup([tree], tmp_path / "backups")
    target = tmp_path / "restore"
    target.mkdir()
    migration.extract_backup(archive, target)
    assert os.readlink(target / ".claude" / "abs") == "/usr/bin"


def crafted(tmp_path, *members):
    """An archive of `members`: (name, kind, payload[, mode]), kind file, dir, sym, hard or char."""
    archive = tmp_path / "crafted.tar.gz"
    kinds = {
        "dir": tarfile.DIRTYPE,
        "sym": tarfile.SYMTYPE,
        "hard": tarfile.LNKTYPE,
        "char": tarfile.CHRTYPE,
    }
    with tarfile.open(archive, "w:gz") as tar:
        for name, kind, payload, *mode in members:
            info = tarfile.TarInfo(name)
            if mode:
                info.mode = mode[0]
            if kind == "file":
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            else:
                info.type = kinds[kind]
                info.linkname = payload or ""
                tar.addfile(info)
    return archive


@pytest.fixture
def victim(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim").write_bytes(b"original")
    target = tmp_path / "restore"
    target.mkdir()
    return outside, target


def assert_refused(archive, outside, target, member, reason):
    with pytest.raises(ClaudeSyncError) as raised:
        migration.extract_backup(archive, target)
    assert f"backup member {member!r} refused: " in str(raised.value)
    assert reason in str(raised.value)
    assert list(target.iterdir()) == []
    assert sorted(p.name for p in outside.iterdir()) == ["victim"]
    assert (outside / "victim").read_bytes() == b"original"


def test_extract_backup_refuses_a_hard_link_through_a_symlink(tmp_path, victim):
    outside, target = victim
    archive = crafted(
        tmp_path,
        (".claude", "dir", None),
        (".claude/x", "sym", str(outside)),
        (".claude/h", "hard", ".claude/x/victim"),
        (".claude/h", "file", b"pwn"),
    )
    assert_refused(archive, outside, target, ".claude/h", "no earlier file")


@pytest.mark.parametrize("link", ["outside", "../../outside"])
def test_extract_backup_refuses_a_member_under_a_symlink(tmp_path, victim, link):
    outside, target = victim
    text = str(outside) if link == "outside" else link
    archive = crafted(
        tmp_path,
        (".claude", "dir", None),
        (".claude/good", "file", b"good"),
        (".claude/x", "sym", text),
        (".claude/x/evil", "file", b"pwn"),
    )
    assert_refused(archive, outside, target, ".claude/x/evil", "outside the destination")


def test_extract_backup_refuses_a_duplicate_name(tmp_path, victim):
    outside, target = victim
    archive = crafted(
        tmp_path,
        (".claude/v", "sym", str(outside / "victim")),
        (".claude/./v", "file", b"pwn"),
    )
    assert_refused(archive, outside, target, ".claude/./v", "duplicate name")


@pytest.mark.parametrize("name", ["/etc/evil", "/.claude/x", "../evil", ".claude/../../evil"])
def test_extract_backup_refuses_an_absolute_or_escaping_member(tmp_path, victim, name):
    outside, target = victim
    archive = crafted(tmp_path, (name, "file", b"x"))
    assert_refused(archive, outside, target, name, "absolute or escaping name")


@pytest.mark.parametrize("name", [".zshenv", ".claude.json/x", ".claude-other/x", "x/.claude"])
def test_extract_backup_refuses_a_member_outside_the_two_entries(tmp_path, victim, name):
    outside, target = victim
    archive = crafted(tmp_path, (".claude/ok", "file", b"x"), (name, "file", b"x"))
    assert_refused(archive, outside, target, name, "not under .claude or .claude.json")


def test_extract_backup_refuses_a_device(tmp_path, victim):
    outside, target = victim
    archive = crafted(tmp_path, (".claude/ok", "file", b"x"), (".claude/tty", "char", None))
    assert_refused(archive, outside, target, ".claude/tty", "not a file, directory or link")


@pytest.mark.parametrize(
    "linkname", ["/etc/passwd", "../outside", ".claude/later", ".claude/dir", ".claude/sym"]
)
def test_extract_backup_refuses_a_hard_link_to_no_earlier_file(tmp_path, victim, linkname):
    outside, target = victim
    archive = crafted(
        tmp_path,
        (".claude/dir", "dir", None, 0o755),
        (".claude/sym", "sym", "dir"),
        (".claude/h", "hard", linkname),
        (".claude/later", "file", b"x"),
    )
    assert_refused(archive, outside, target, ".claude/h", "no earlier file")


def test_extract_backup_refuses_an_entry_the_destination_has(tmp_path, victim):
    outside, target = victim
    (target / ".claude").mkdir()
    (target / ".claude" / "mine").write_text("keep")
    archive = crafted(
        tmp_path,
        (".claude.json", "file", b"{}"),
        (".claude/locked", "dir", None),  # TarInfo's default mode, 644: not traversable
        (".claude/locked/f", "file", b"x"),
    )
    with pytest.raises(ClaudeSyncError, match=r"\.claude.*exists"):
        migration.extract_backup(archive, target)
    assert sorted(p.name for p in target.iterdir()) == [".claude"]
    assert [p.name for p in (target / ".claude").iterdir()] == ["mine"]


def test_a_refused_restore_removes_unreadable_staging_directories(tmp_path, victim):
    outside, target = victim
    (target / ".claude.json").write_text("mine")
    archive = crafted(
        tmp_path,
        (".claude", "dir", None, 0o500),
        (".claude/d", "dir", None, 0o000),
        (".claude/d/e", "dir", None, 0o000),
        (".claude.json", "file", b"{}"),
    )
    with pytest.raises(ClaudeSyncError, match="exists"):
        migration.extract_backup(archive, target)
    assert sorted(p.name for p in target.iterdir()) == [".claude.json"]


def test_a_refused_restore_leaves_the_mode_of_a_linked_directory(tmp_path, victim):
    outside, target = victim
    outside.chmod(0o555)
    (target / ".claude.json").write_text("mine")
    archive = crafted(
        tmp_path,
        (".claude", "dir", None, 0o700),
        (".claude/link", "sym", str(outside)),
        (".claude.json", "file", b"{}"),
    )
    try:
        with pytest.raises(ClaudeSyncError, match="exists"):
            migration.extract_backup(archive, target)
        assert mode(outside) == 0o555
    finally:
        outside.chmod(0o755)


def test_extract_backup_reports_a_failing_member(tmp_path, victim):
    outside, target = victim
    archive = crafted(tmp_path, (".claude/d/f", "file", b"x"), (".claude/d", "sym", "elsewhere"))
    assert_refused(archive, outside, target, ".claude/d", "File exists")


def test_extract_backup_restores_hard_links_and_modes(tmp_path):
    tree = tmp_path / ".claude"
    (tree / "locked").mkdir(parents=True)
    (tree / "run.sh").write_text("#!/bin/sh\n")
    (tree / "run.sh").chmod(0o755)
    os.link(tree / "run.sh", tree / "twin.sh")
    (tree / "locked" / "f").write_text("x")
    (tree / "locked").chmod(0o500)
    try:
        archive = migration.backup([tree], tmp_path / "backups")
    finally:
        (tree / "locked").chmod(0o700)
    target = tmp_path / "restore"
    target.mkdir()
    migration.extract_backup(archive, target)
    restored = target / ".claude"
    assert mode(restored / "run.sh") == 0o755
    assert os.stat(restored / "twin.sh").st_ino == os.stat(restored / "run.sh").st_ino
    assert mode(restored / "locked") == 0o500
    assert (restored / "locked" / "f").read_text() == "x"
    assert os.stat(restored / "run.sh").st_mtime == os.stat(tree / "run.sh").st_mtime
    (restored / "locked").chmod(0o700)


def test_backup_lists_skipped_special_files(tmp_path, monkeypatch, capsys):
    tree = tmp_path / ".claude"
    tree.mkdir()
    os.mkfifo(tree / "fifo")
    monkeypatch.chdir(tree)
    server = socket.socket(socket.AF_UNIX)
    server.bind("sock")
    try:
        archive = migration.backup([tree], tmp_path / "backups")
    finally:
        server.close()
    assert sorted(capsys.readouterr().err.splitlines()) == [
        f"backup: skipped special file {tree / 'fifo'}",
        f"backup: skipped special file {tree / 'sock'}",
    ]
    with tarfile.open(archive) as tar:
        assert tar.getnames() == [".claude"]


def test_backup_makes_an_existing_backups_directory_private(tmp_path):
    (tmp_path / "backups").mkdir(mode=0o755)
    (tmp_path / "tree").mkdir()
    migration.backup([tmp_path / "tree"], tmp_path / "backups")
    assert mode(tmp_path / "backups") == 0o700


def test_a_failed_backup_leaves_no_archive(tmp_path):
    with pytest.raises(FileNotFoundError):
        migration.backup([tmp_path / "missing"], tmp_path / "backups")
    assert list((tmp_path / "backups").iterdir()) == []


def test_remove_plugin_caches_removes_exactly_the_four_entries(legacy_claude):
    plugins = legacy_claude.root / "plugins"
    (plugins / "other.json").write_text("{}")
    migration.remove_plugin_caches(legacy_claude.root)
    assert sorted(p.name for p in plugins.iterdir()) == ["data", "other.json"]


def test_remove_plugin_caches_tolerates_missing_entries(tmp_path):
    (tmp_path / "plugins" / "cache").mkdir(parents=True)
    migration.remove_plugin_caches(tmp_path)
    migration.remove_plugin_caches(tmp_path / "nothing")
    assert list((tmp_path / "plugins").iterdir()) == []


def test_remove_plugin_caches_removes_a_link_and_not_its_target(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep").touch()
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "cache").symlink_to(elsewhere)
    migration.remove_plugin_caches(tmp_path)
    assert not os.path.lexists(tmp_path / "plugins" / "cache")
    assert (elsewhere / "keep").exists()


@pytest.fixture
def moved(legacy_claude):
    """The legacy `~/.claude` renamed to a profile directory, with extra edge-case links."""
    old = legacy_claude.root
    (old / "abs").symlink_to("/usr/bin")
    (old / "dangling").symlink_to("../nowhere/at-all")
    (old / ".git" / "out").symlink_to("../../.agents/skills/out")
    profile = legacy_claude.home / "profiles" / "perso"
    profile.parent.mkdir()
    os.rename(old, profile)
    return old, profile


def test_absolutize_symlinks_rewrites_only_relative_links_leaving_the_root(moved, legacy_claude):
    old, profile = moved
    links = migration.absolutize_symlinks(profile, old)
    target = legacy_claude.home / ".agents" / "skills" / "out"
    assert links == [(Path("skills/out"), "../../.agents/skills/out")]
    assert os.readlink(profile / "skills" / "out") == str(target)
    assert (profile / "skills" / "out" / "SKILL.md").is_file()
    assert os.readlink(profile / "skills" / "in") == "../rules"
    assert os.readlink(profile / "abs") == "/usr/bin"
    assert os.readlink(profile / "dangling") == "../nowhere/at-all"
    assert os.readlink(profile / ".git" / "out") == "../../.agents/skills/out"


def test_absolutize_symlinks_keeps_an_inside_link_whose_old_target_exists_again(moved):
    old, profile = moved
    (old / "rules").mkdir(parents=True)  # a tool recreated ~/.claude/rules
    migration.absolutize_symlinks(profile, old)
    assert os.readlink(profile / "skills" / "in") == "../rules"


def test_absolutize_symlinks_repoints_a_link_reentering_the_root_by_name(moved):
    old, profile = moved
    (profile / "back").symlink_to("../.claude/rules")  # broken once .claude is renamed
    links = migration.absolutize_symlinks(profile, old)
    assert (Path("back"), "../.claude/rules") in links
    assert os.readlink(profile / "back") == "rules"
    assert (profile / "back").is_dir()
    migration.relativize_symlinks(links, profile)
    assert os.readlink(profile / "back") == "../.claude/rules"


def test_absolutize_symlinks_rewrites_a_resolving_directory_link_in_a_nested_directory(moved):
    old, profile = moved
    deep = profile / "skills" / "deep"
    deep.mkdir()
    text = "../" * 40 + "usr"  # clamped at /: resolves before and after the move
    (deep / "usr").symlink_to(text)
    links = migration.absolutize_symlinks(profile, old)
    assert (Path("skills/deep/usr"), text) in links
    assert os.readlink(deep / "usr") == "/usr"


def test_relativize_symlinks_restores_the_original_link_text(moved):
    old, profile = moved
    links = migration.absolutize_symlinks(profile, old)
    migration.relativize_symlinks(links, profile)
    assert os.readlink(profile / "skills" / "out") == "../../.agents/skills/out"
    os.rename(profile, old)
    assert (old / "skills" / "out" / "SKILL.md").is_file()


def test_relativize_symlinks_skips_a_link_removed_since(moved):
    old, profile = moved
    links = migration.absolutize_symlinks(profile, old)
    (profile / "skills" / "out").unlink()
    migration.relativize_symlinks(links, profile)
    assert not os.path.lexists(profile / "skills" / "out")


def test_rewrite_settings_replaces_only_the_old_root_and_is_reversible(tmp_path):
    old, new = "/home/u/.claude", "/home/u/profiles/perso"
    original = {
        "hooks": {"PreToolUse": [{"hooks": [{"command": f"{old}/hooks/x.sh"}, {"command": "ls"}]}]},
        "statusLine": {"command": old},
        "env": {"STATE": f"{old}.json", "OTHER": f"{old}-code-config/x", "NOTE": "café"},
        "args": [[f"{old}/a", 3, True, None]],
    }
    (tmp_path / "settings.json").write_text(json.dumps(original))
    keys = migration.rewrite_settings(tmp_path, old, new)
    assert keys == ["/hooks/PreToolUse/0/hooks/0/command", "/statusLine/command", "/args/0/0"]
    text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert text.endswith("}\n") and '\n  "hooks": {' in text and "café" in text
    data = json.loads(text)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == f"{new}/hooks/x.sh"
    assert data["statusLine"]["command"] == new
    assert data["env"] == original["env"]
    assert data["args"] == [[f"{new}/a", 3, True, None]]
    assert migration.rewrite_settings(tmp_path, new, old) == keys
    assert json.loads((tmp_path / "settings.json").read_text()) == original


def test_rewrite_settings_replaces_the_old_root_inside_a_value(tmp_path):
    old, new = "/home/u/.claude", "/home/u/profiles/perso"
    values = {
        "flag": f"python3 {old}/hooks/x.py --flag",
        "twice": f"{old}/a:{old}/b;{old}",
        "quoted": f"bash -c '{old}/s.sh' \"{old}\" {old}\t{old}",
        "equal": old,
        "json": f"cat {old}.json",
        "code": f"ls {old}-code-config/x",
        "longer": f"ls {old}x {old}_y",
        "other": f"ls /backup{old}/x",
    }
    (tmp_path / "settings.json").write_text(json.dumps(values))
    keys = migration.rewrite_settings(tmp_path, old, new)
    assert keys == ["/flag", "/twice", "/quoted", "/equal"]
    data = json.loads((tmp_path / "settings.json").read_text())
    assert data["flag"] == f"python3 {new}/hooks/x.py --flag"
    assert data["twice"] == f"{new}/a:{new}/b;{new}"
    assert data["quoted"] == f"bash -c '{new}/s.sh' \"{new}\" {new}\t{new}"
    assert data["equal"] == new
    for key in ("json", "code", "longer", "other"):
        assert data[key] == values[key]
    assert migration.rewrite_settings(tmp_path, new, old) == keys
    assert json.loads((tmp_path / "settings.json").read_text()) == values


def test_rewrite_settings_boundaries(tmp_path):
    old, new = "/home/u/.claude", "/home/u/profiles/perso"
    values = {
        "sub": f"echo $(ls {old})",
        "pipe": f"a|{old}/x",
        "comma": f"x,{old}",
        "brace": f"{{{old}}}",
        "slash": f"ls /{old}/a",
        "dot": f"ls .{old}/a",
        "tilde": f"ls ~{old}/a",
        "dash": f"ls x-{old}/a",
        "word": f"ls x{old}/a",
    }
    (tmp_path / "settings.json").write_text(json.dumps(values))
    assert migration.rewrite_settings(tmp_path, old, new) == ["/sub", "/pipe", "/comma", "/brace"]
    data = json.loads((tmp_path / "settings.json").read_text())
    assert data["sub"] == f"echo $(ls {new})"
    assert data["pipe"] == f"a|{new}/x"
    assert data["comma"] == f"x,{new}"
    assert data["brace"] == f"{{{new}}}"
    for key in ("slash", "dot", "tilde", "dash", "word"):
        assert data[key] == values[key]


def test_rewrite_settings_rewrites_the_home_relative_forms(isolated_environment, tmp_path):
    home = isolated_environment
    old, new = str(home / ".claude"), str(home / ".config" / "claude-sync" / "profiles" / "perso")
    values = {
        "tilde": "bash ~/.claude/hooks/x.sh",
        "home": "$HOME/.claude/hooks/x.sh",
        "braced": "${HOME}/.claude",
        "json": "cat ~/.claude.json $HOME/.claude.json",
        "other": "~/.claude-code/x",
        "user": "~u/.claude/x",
    }
    (tmp_path / "settings.json").write_text(json.dumps(values))
    keys = migration.rewrite_settings(tmp_path, old, new)
    assert keys == ["/tilde", "/home", "/braced"]
    data = json.loads((tmp_path / "settings.json").read_text())
    assert data["tilde"] == "bash ~/.config/claude-sync/profiles/perso/hooks/x.sh"
    assert data["home"] == "$HOME/.config/claude-sync/profiles/perso/hooks/x.sh"
    assert data["braced"] == "${HOME}/.config/claude-sync/profiles/perso"
    for key in ("json", "other", "user"):
        assert data[key] == values[key]
    assert migration.rewrite_settings(tmp_path, new, old) == keys
    assert json.loads((tmp_path / "settings.json").read_text()) == values


def test_rewrite_settings_home_forms_to_a_root_outside_home(isolated_environment, tmp_path):
    old = str(isolated_environment / ".claude")
    (tmp_path / "settings.json").write_text(json.dumps({"a": "~/.claude/x", "b": "$HOME/.claude"}))
    assert migration.rewrite_settings(tmp_path, old, "/srv/perso") == ["/a", "/b"]
    data = json.loads((tmp_path / "settings.json").read_text())
    assert data == {"a": "/srv/perso/x", "b": "/srv/perso"}


def test_rewrite_settings_escapes_key_paths(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"a/b": {"c~d": "/old/x"}}))
    assert migration.rewrite_settings(tmp_path, "/old", "/new") == ["/a~1b/c~0d"]


def test_rewrite_settings_on_the_legacy_configuration(legacy_claude):
    home = legacy_claude.home
    keys = migration.rewrite_settings(legacy_claude.root, f"{home}/.claude", "/p")
    assert keys == ["/hooks/PreToolUse/0/hooks/0/command"]
    settings = json.loads((legacy_claude.root / "settings.json").read_text())
    assert settings["env"]["STATE_FILE"] == f"{home}/.claude.json"


def test_rewrite_settings_without_a_match_leaves_the_file_untouched(tmp_path):
    (tmp_path / "settings.json").write_text('{"a":   "b"}')
    assert migration.rewrite_settings(tmp_path, "/old", "/new") == []
    assert (tmp_path / "settings.json").read_text() == '{"a":   "b"}'


def test_rewrite_settings_without_settings(tmp_path):
    assert migration.rewrite_settings(tmp_path, "/old", "/new") == []
    assert not (tmp_path / "settings.json").exists()


def test_rewrite_settings_refuses_invalid_json(tmp_path):
    (tmp_path / "settings.json").write_text("{nope")
    with pytest.raises(ClaudeSyncError, match="settings.json"):
        migration.rewrite_settings(tmp_path, "/old", "/new")


def ignored(repo, name):
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", name]).returncode == 0


def test_allow_manifest_unignores_the_manifest_once(legacy_claude):
    root = legacy_claude.root
    assert migration.allow_manifest(root) is True
    gitignore = (root / ".gitignore").read_text()
    assert gitignore.endswith("!/plugins/known_marketplaces.json\n!/profile.toml\n")
    assert not ignored(root, "profile.toml")
    assert ignored(root, "projects")
    assert migration.allow_manifest(root) is False
    assert (root / ".gitignore").read_text() == gitignore


def test_allow_manifest_adds_a_newline_first_when_missing(tmp_path):
    git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_text("/*")
    assert migration.allow_manifest(tmp_path) is True
    assert (tmp_path / ".gitignore").read_text() == "/*\n!/profile.toml\n"


def test_allow_manifest_leaves_a_manifest_already_tracked(tmp_path):
    git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_text("/projects/\n")
    assert migration.allow_manifest(tmp_path) is False
    assert (tmp_path / ".gitignore").read_text() == "/projects/\n"


def test_allow_manifest_outside_a_git_repository_does_nothing(tmp_path):
    (tmp_path / ".gitignore").write_text("/*\n")
    assert migration.allow_manifest(tmp_path) is False
    assert (tmp_path / ".gitignore").read_text() == "/*\n"


def test_allow_manifest_reports_a_broken_repository(tmp_path):
    (tmp_path / ".git").write_text("gitdir: /nowhere\n")
    with pytest.raises(ClaudeSyncError, match="check-ignore"):
        migration.allow_manifest(tmp_path)


def test_allow_manifest_creates_the_gitignore_when_another_rule_ignores_it(tmp_path):
    git(tmp_path, "init", "--quiet")
    (tmp_path / ".git" / "info" / "exclude").write_text("profile.toml\n")
    assert migration.allow_manifest(tmp_path) is True
    assert (tmp_path / ".gitignore").read_text() == "!/profile.toml\n"
    assert not ignored(tmp_path, "profile.toml")


def test_markdown_mentions_lists_files_naming_the_old_root(legacy_claude):
    root, home = legacy_claude.root, legacy_claude.home
    (root / "CLAUDE.md").write_text(f"See {home}/.claude for details.\n")
    (root / "rules" / "json.md").write_text("Only ~/.claude.json and ~/.claude-code here.\n")
    (root / "rules" / "end.md").write_text("Edit ~/.claude.\n")
    (root / "rules" / "notes.txt").write_text("~/.claude/hooks\n")
    (root / "projects" / "p" / "m.md").write_text("~/.claude/hooks\n")
    (root / "plugins" / "data" / "m.md").write_text("~/.claude/hooks\n")
    before = (root / "rules" / "r.md").read_text()
    found = migration.markdown_mentions(root, home / ".claude")
    assert found == [root / "CLAUDE.md", root / "rules" / "end.md", root / "rules" / "r.md"]
    assert (root / "rules" / "r.md").read_text() == before


def test_markdown_mentions_of_a_root_outside_home(tmp_path):
    (tmp_path / "a.md").write_text(f"{tmp_path}/x\n")
    assert migration.markdown_mentions(tmp_path, tmp_path) == [tmp_path / "a.md"]


BLOCK = (
    "# >>> claude-sync >>>\n"
    'command -v claude-sync >/dev/null && eval "$(claude-sync shell-init zsh)"\n'
    "# <<< claude-sync <<<\n"
)


def test_zshrc_block_add_is_idempotent_and_keeps_the_mode(tmp_path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("export A=1\n")
    zshrc.chmod(0o644)
    assert migration.zshrc_block_add(zshrc) is True
    assert migration.zshrc_block_add(zshrc) is False
    assert zshrc.read_text() == "export A=1\n" + BLOCK
    assert mode(zshrc) == 0o644


def test_zshrc_block_add_follows_a_symlinked_zshrc(tmp_path):
    real = tmp_path / "dotfiles" / "zshrc"
    real.parent.mkdir()
    real.write_text("export A=1\n")
    zshrc = tmp_path / ".zshrc"
    zshrc.symlink_to(real)
    migration.zshrc_block_add(zshrc)
    assert zshrc.is_symlink()
    assert real.read_text() == "export A=1\n" + BLOCK


def test_zshrc_block_add_adds_a_newline_when_the_file_lacks_one(tmp_path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("export A=1")
    migration.zshrc_block_add(zshrc)
    assert zshrc.read_text() == "export A=1\n" + BLOCK


def test_zshrc_block_add_creates_a_missing_zshrc(tmp_path):
    zshrc = tmp_path / ".zshrc"
    migration.zshrc_block_add(zshrc)
    assert zshrc.read_text() == BLOCK
    assert mode(zshrc) == 0o644


def test_zshrc_block_remove_removes_exactly_the_block(tmp_path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("export A=1\n")
    zshrc.chmod(0o600)
    migration.zshrc_block_add(zshrc)
    with zshrc.open("a") as handle:
        handle.write("export B=2\n")
    assert migration.zshrc_block_remove(zshrc) is True
    assert zshrc.read_text() == "export A=1\nexport B=2\n"
    assert mode(zshrc) == 0o600
    assert migration.zshrc_block_remove(zshrc) is False
    assert migration.zshrc_block_remove(tmp_path / "missing") is False


def test_zshrc_block_remove_refuses_an_unterminated_block(tmp_path):
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("# >>> claude-sync >>>\nexport A=1\n")
    with pytest.raises(ClaudeSyncError, match="<<< claude-sync <<<"):
        migration.zshrc_block_remove(zshrc)
    assert zshrc.read_text() == "# >>> claude-sync >>>\nexport A=1\n"


def test_launch_agent_plist_sets_the_config_dir_at_load():
    data = plistlib.loads(migration.launch_agent_plist(Path("/p/perso")).encode())
    assert data == {
        "Label": "io.github.ylepalud.claude-sync.env",
        "ProgramArguments": ["/bin/launchctl", "setenv", "CLAUDE_CONFIG_DIR", "/p/perso"],
        "RunAtLoad": True,
    }


def test_launch_agent_path_is_in_the_user_launch_agents(isolated_environment):
    assert migration.launch_agent_path() == (
        isolated_environment
        / "Library"
        / "LaunchAgents"
        / "io.github.ylepalud.claude-sync.env.plist"
    )


def market(name, source):
    return ObservedMarketplace(name, "github" if source else "directory-plus", source, None, None)


def test_unrebuildable_names_other_scopes_and_unmanaged_marketplaces():
    observed = Observed(
        (market("tools", "github:perso/tools"), market("local", None)), (), None, None
    )
    listed = [
        {"id": "helper@tools", "scope": "user"},
        {"id": "proj@tools", "scope": "project"},
        {"id": "mine@local", "scope": "user"},
    ]
    assert migration.unrebuildable(observed, listed) == [
        "proj@tools (installed at project scope)",
        "mine@local (marketplace local is not managed by claude-sync: directory-plus)",
    ]


def test_unrebuildable_of_the_legacy_configuration_is_empty(legacy_claude):
    cli = ClaudeCli(legacy_claude.root)
    listed = json.loads(cli.run(["plugin", "list", "--json"]))
    assert migration.unrebuildable(observe(cli, legacy_claude.root), listed) == []


def test_record_round_trips(tmp_path):
    record = migration.Record(
        old_root="/home/u/.claude",
        steps=["backup", "rename"],
        settings_keys=["/statusLine/command"],
        links=[(Path("skills/out"), "../../.agents/skills/out")],
        plist="/home/u/Library/LaunchAgents/x.plist",
    )
    record.save(tmp_path)
    assert (tmp_path / ".claude-sync-migration.json").exists()
    assert mode(tmp_path / ".claude-sync-migration.json") == 0o600
    assert migration.Record.load(tmp_path) == record


def test_record_load_without_a_record(tmp_path):
    assert migration.Record.load(tmp_path) is None


VALID_RECORD = {
    "old_root": "/home/u/.claude",
    "steps": ["backup"],
    "settings_keys": ["/a"],
    "links": [["skills/out", "../x"]],
    "plist": "/p.plist",
}


@pytest.mark.parametrize(
    "key, value",
    [
        ("old_root", 3),
        ("steps", [3]),
        ("settings_keys", [None]),
        ("links", [[1, "../x"]]),
        ("links", [["skills/out", 2]]),
        ("links", [["skills/out"]]),
        ("plist", 4),
    ],
)
def test_record_load_refuses_a_mistyped_field(tmp_path, key, value):
    (tmp_path / ".claude-sync-migration.json").write_text(json.dumps({**VALID_RECORD, key: value}))
    with pytest.raises(ClaudeSyncError, match="damaged migration record"):
        migration.Record.load(tmp_path)


@pytest.mark.parametrize("text", ["{nope", '{"old_root": "/x"}'])
def test_record_load_refuses_invalid_json_or_a_missing_key(tmp_path, text):
    (tmp_path / ".claude-sync-migration.json").write_text(text)
    with pytest.raises(ClaudeSyncError, match="damaged migration record"):
        migration.Record.load(tmp_path)


def test_record_load_accepts_a_record_without_plist(tmp_path):
    (tmp_path / ".claude-sync-migration.json").write_text(
        json.dumps({**VALID_RECORD, "plist": None})
    )
    assert migration.Record.load(tmp_path).plist is None


def test_the_record_is_not_tracked_by_the_legacy_allowlist(legacy_claude):
    migration.Record(old_root="/x").save(legacy_claude.root)
    assert ignored(legacy_claude.root, ".claude-sync-migration.json")


@pytest.mark.parametrize("entry", [{"id": "a@m"}, {"scope": "user"}, {"id": 3, "scope": "user"}])
def test_unrebuildable_refuses_an_unexpected_plugin_entry(entry):
    observed = Observed((), (), None, None)
    with pytest.raises(ClaudeSyncError, match="claude plugin list --json"):
        migration.unrebuildable(observed, [entry])


def test_absolutize_symlinks_leaves_a_dangling_link_reentering_the_root(moved):
    old, profile = moved
    (profile / "gone").symlink_to("../.claude/missing")
    links = migration.absolutize_symlinks(profile, old)
    assert Path("gone") not in [path for path, _ in links]
    assert os.readlink(profile / "gone") == "../.claude/missing"
