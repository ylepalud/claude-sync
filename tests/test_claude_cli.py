import os
import subprocess

import pytest

from claude_sync.claude_cli import (
    ClaudeCli,
    ClaudeCliError,
    InstalledMarketplace,
    InstalledPlugin,
)


@pytest.fixture
def profile(tmp_path):
    return tmp_path / "profiles" / "perso"


def test_plugins_lists_user_scope_only_from_the_profile(fake_claude, profile, tmp_path):
    other = tmp_path / "profiles" / "work"
    fake_claude.seed(
        profile,
        {
            "plugins": [
                {"id": "a@m", "version": "1.0.0", "scope": "user", "enabled": True},
                {"id": "b@m", "version": "abc123", "scope": "project", "enabled": True},
                {"id": "c@m", "version": "2.0.0", "scope": "user", "enabled": False},
            ]
        },
    )
    fake_claude.seed(other, {})
    assert ClaudeCli(profile).plugins() == [
        InstalledPlugin("a@m", "1.0.0", True),
        InstalledPlugin("c@m", "2.0.0", False),
    ]
    assert fake_claude.calls(profile) == [["plugin", "list", "--json"]]
    assert fake_claude.calls(other) == []


@pytest.mark.parametrize(
    "plugins",
    [
        {"id": "a@m"},
        [{"id": "a@m", "scope": "user", "enabled": True}],
        [{"id": "a@m", "version": 1, "scope": "user", "enabled": True}],
        [{"id": "a@m", "version": "1", "scope": "user", "enabled": "yes"}],
        [{"id": None, "version": "1", "scope": "user", "enabled": True}],
        ["a@m"],
    ],
)
def test_an_unknown_plugin_list_shape_raises(fake_claude, profile, plugins):
    fake_claude.seed(profile, {"plugins": plugins})
    with pytest.raises(ClaudeCliError) as caught:
        ClaudeCli(profile).plugins()
    assert caught.value.command == ["claude", "plugin", "list", "--json"]


def test_output_that_is_not_json_raises(profile, monkeypatch):
    cli = ClaudeCli(profile)
    monkeypatch.setattr(cli, "run", lambda args: "Installed plugins:\n  a@m\n")
    with pytest.raises(ClaudeCliError, match="invalid JSON"):
        cli.plugins()


def test_marketplaces_reads_each_source_kind(fake_claude, profile):
    fake_claude.seed(
        profile,
        {
            "marketplaces": [
                {"name": "gh", "source": "github", "repo": "o/r", "installLocation": "/m/gh"},
                {
                    "name": "pinned",
                    "source": "git",
                    "url": "https://example.invalid/r.git",
                    "ref": "v1",
                    "installLocation": "/m/pinned",
                },
                {
                    "name": "u",
                    "source": "url",
                    "url": "https://e.invalid/m.json",
                    "installLocation": "/m/u",
                },
                {
                    "name": "dir",
                    "source": "directory",
                    "path": "/src/dir",
                    "installLocation": "/src/dir",
                },
                {"name": "f", "source": "file", "path": "/src/m.json", "installLocation": "/m/f"},
                {"name": "hosted", "source": "claudeai", "installLocation": "/m/hosted"},
            ]
        },
    )
    assert ClaudeCli(profile).marketplaces() == [
        InstalledMarketplace("gh", "github", "o/r", None, "/m/gh"),
        InstalledMarketplace("pinned", "git", "https://example.invalid/r.git", "v1", "/m/pinned"),
        InstalledMarketplace("u", "url", "https://e.invalid/m.json", None, "/m/u"),
        InstalledMarketplace("dir", "directory", "/src/dir", None, "/src/dir"),
        InstalledMarketplace("f", "file", "/src/m.json", None, "/m/f"),
        InstalledMarketplace("hosted", "claudeai", None, None, "/m/hosted"),
    ]
    assert fake_claude.calls(profile) == [["plugin", "marketplace", "list", "--json"]]


@pytest.mark.parametrize(
    "market",
    [
        {"source": "github", "repo": "o/r", "installLocation": "/m"},
        {"name": "x", "repo": "o/r", "installLocation": "/m"},
        {"name": "x", "source": "github", "installLocation": "/m"},
        {"name": "x", "source": "git", "repo": "o/r", "installLocation": "/m"},
        {"name": "x", "source": "directory", "installLocation": "/m"},
        {"name": "x", "source": "github", "repo": "o/r"},
        {"name": "x", "source": "github", "repo": "o/r", "ref": 3, "installLocation": "/m"},
    ],
)
def test_an_unknown_marketplace_list_shape_raises(fake_claude, profile, market):
    fake_claude.seed(profile, {"marketplaces": [market]})
    with pytest.raises(ClaudeCliError):
        ClaudeCli(profile).marketplaces()


@pytest.fixture
def stdin_is_a_pipe():
    """Make fd 0 a pipe so a child inheriting it would not see /dev/null."""
    read_end, write_end = os.pipe()
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        yield
    finally:
        os.dup2(saved, 0)
        for fd in (saved, read_end, write_end):
            os.close(fd)


def test_mutating_commands_target_the_user_scope_without_yes(fake_claude, profile):
    upstream, _ = fake_claude.make_upstream("market", {"tool": "1.2.0"})
    fake_claude.seed(profile, {"upstream": {"o/market": str(upstream)}})
    cli = ClaudeCli(profile)

    cli.add_marketplace("o/market")
    cli.install("tool@market")
    cli.disable("tool@market")
    cli.enable("tool@market")
    cli.uninstall("tool@market")
    cli.remove_marketplace("market")

    assert fake_claude.calls(profile) == [
        ["plugin", "marketplace", "add", "o/market"],
        ["plugin", "install", "tool@market", "--scope", "user"],
        ["plugin", "disable", "tool@market", "--scope", "user"],
        ["plugin", "enable", "tool@market", "--scope", "user"],
        ["plugin", "uninstall", "tool@market", "--scope", "user"],
        ["plugin", "marketplace", "remove", "market"],
    ]
    assert fake_claude.state(profile)["marketplaces"] == []


def test_install_runs_with_stdin_closed(fake_claude, profile, stdin_is_a_pipe):
    fake_claude.seed(
        profile,
        {
            "marketplaces": [
                {"name": "m", "source": "directory", "path": "/m", "installLocation": "/m"}
            ],
            "catalog": {"m": {"tool": "1.0.0"}},
        },
    )
    ClaudeCli(profile).install("tool@m")
    assert [entry["stdin"] for entry in fake_claude.log(profile)] == ["devnull"]
    assert fake_claude.state(profile)["plugins"] == [
        {"id": "tool@m", "version": "1.0.0", "scope": "user", "enabled": True}
    ]


def test_a_failing_command_raises_with_the_command_and_stderr(fake_claude, profile):
    fake_claude.seed(profile, {"fail": {"plugin install": "This plugin runs a command: approve?"}})
    with pytest.raises(ClaudeCliError) as caught:
        ClaudeCli(profile).install("tool@m")
    assert caught.value.command == ["claude", "plugin", "install", "tool@m", "--scope", "user"]
    assert "approve?" in caught.value.stderr
    assert "claude plugin install tool@m --scope user" in str(caught.value)
    assert "approve?" in str(caught.value)


def test_enabling_an_enabled_plugin_raises(fake_claude, profile):
    fake_claude.seed(
        profile, {"plugins": [{"id": "a@m", "version": "1", "scope": "user", "enabled": True}]}
    )
    with pytest.raises(ClaudeCliError, match="already enabled"):
        ClaudeCli(profile).enable("a@m")


def test_a_missing_claude_raises(profile, monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ClaudeCliError, match="not found"):
        ClaudeCli(profile).plugins()


def test_marketplace_commit_of_a_clone_is_its_head(fake_claude, profile):
    upstream, head = fake_claude.make_upstream("market", {"tool": "1"}, branches=("main", "stable"))
    fake_claude.seed(profile, {"upstream": {"o/market": str(upstream)}})
    cli = ClaudeCli(profile)
    cli.add_marketplace("o/market#stable")
    [market] = cli.marketplaces()
    assert market.ref == "stable"
    assert cli.marketplace_commit(market.location) == head


def test_marketplace_commit_of_a_plain_directory_is_none(profile, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert ClaudeCli(profile).marketplace_commit(str(plain)) is None


def test_marketplace_commit_inside_another_repository_is_none(fake_claude, profile):
    upstream, _ = fake_claude.make_upstream("outer", {"tool": "1"})
    assert ClaudeCli(profile).marketplace_commit(str(upstream / ".claude-plugin")) is None


def test_marketplace_commit_of_a_missing_directory_is_none(profile, tmp_path):
    assert ClaudeCli(profile).marketplace_commit(str(tmp_path / "gone")) is None


def test_adding_a_commit_as_ref_fails_like_the_real_cli(fake_claude, profile):
    upstream, head = fake_claude.make_upstream("market", {"tool": "1"})
    fake_claude.seed(profile, {"upstream": {"o/market": str(upstream)}})
    with pytest.raises(ClaudeCliError, match=head):
        ClaudeCli(profile).add_marketplace(f"o/market#{head}")


@pytest.mark.parametrize("output", [{}, 5])
def test_a_plugin_list_that_is_not_a_list_raises(fake_claude, profile, output):
    fake_claude.seed(profile, {"plugins": output})
    with pytest.raises(ClaudeCliError, match="expected a JSON list of objects"):
        ClaudeCli(profile).plugins()


def test_marketplace_commit_of_a_repository_without_commits_is_none(profile, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "-C", str(empty), "init", "--quiet"], check=True)
    assert ClaudeCli(profile).marketplace_commit(str(empty)) is None
