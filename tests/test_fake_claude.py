"""The fake `claude mcp add-json` and `claude mcp remove`, as the real CLI behaves."""

import json
import stat

import pytest

from claude_sync.claude_cli import ClaudeCli, ClaudeCliError


@pytest.fixture
def profile(tmp_path):
    return tmp_path / "profiles" / "perso"


def _servers(profile):
    return json.loads((profile / ".claude.json").read_text())["mcpServers"]


def _add(profile, name, entry):
    return ClaudeCli(profile).run(["mcp", "add-json", name, json.dumps(entry), "--scope", "user"])


def test_add_json_stores_the_entry_verbatim_in_a_private_file(fake_claude, profile):
    entry = {"type": "stdio", "command": "tool", "args": ["${DIR:-x}"], "env": {"T": "${T}"}}
    _add(profile, "tools", entry)
    assert _servers(profile) == {"tools": entry}
    assert stat.S_IMODE((profile / ".claude.json").stat().st_mode) == 0o600


def test_add_json_keeps_the_other_keys_and_refuses_an_existing_name(fake_claude, profile):
    profile.mkdir(parents=True)
    (profile / ".claude.json").write_text(json.dumps({"oauthAccount": {"x": 1}}))
    _add(profile, "tools", {"type": "stdio", "command": "a"})
    with pytest.raises(ClaudeCliError, match="already exists"):
        _add(profile, "tools", {"type": "stdio", "command": "b"})
    data = json.loads((profile / ".claude.json").read_text())
    assert data == {
        "oauthAccount": {"x": 1},
        "mcpServers": {"tools": {"type": "stdio", "command": "a"}},
    }


def test_add_json_refuses_a_remote_entry_without_type(fake_claude, profile):
    with pytest.raises(ClaudeCliError):
        _add(profile, "idea", {"url": "https://example.invalid/mcp"})
    assert not (profile / ".claude.json").exists()


def test_add_json_stores_streamable_http_as_http(fake_claude, profile):
    _add(profile, "idea", {"type": "streamable-http", "url": "https://example.invalid/mcp"})
    assert _servers(profile) == {"idea": {"type": "http", "url": "https://example.invalid/mcp"}}


def test_add_json_supports_the_user_scope_only(fake_claude, profile):
    entry = json.dumps({"type": "stdio", "command": "a"})
    with pytest.raises(ClaudeCliError, match="user scope"):
        ClaudeCli(profile).run(["mcp", "add-json", "tools", entry])
    assert not (profile / ".claude.json").exists()


def test_remove_deletes_the_user_scope_entry_and_refuses_an_unknown_one(fake_claude, profile):
    _add(profile, "a", {"type": "stdio", "command": "a"})
    _add(profile, "b", {"type": "stdio", "command": "b"})
    ClaudeCli(profile).run(["mcp", "remove", "a", "-s", "user"])
    assert _servers(profile) == {"b": {"type": "stdio", "command": "b"}}
    assert stat.S_IMODE((profile / ".claude.json").stat().st_mode) == 0o600
    with pytest.raises(ClaudeCliError, match="No user-scoped MCP server"):
        ClaudeCli(profile).run(["mcp", "remove", "a", "-s", "user"])


def test_remove_supports_the_user_scope_only(fake_claude, profile):
    _add(profile, "a", {"type": "stdio", "command": "a"})
    with pytest.raises(ClaudeCliError, match="user scope"):
        ClaudeCli(profile).run(["mcp", "remove", "a"])
    assert _servers(profile) == {"a": {"type": "stdio", "command": "a"}}


def test_mcp_commands_honour_fail(fake_claude, profile):
    fake_claude.seed(profile, {"fail": {"mcp add-json": "boom"}})
    with pytest.raises(ClaudeCliError, match="boom"):
        _add(profile, "a", {"type": "stdio", "command": "a"})
    assert not (profile / ".claude.json").exists()


def test_without_a_config_dir_the_state_is_home_claude_json(fake_claude, isolated_environment):
    ClaudeCli(None).run(
        ["mcp", "add-json", "a", json.dumps({"type": "stdio", "command": "a"}), "--scope", "user"]
    )
    assert _servers(isolated_environment) == {"a": {"type": "stdio", "command": "a"}}


def test_add_json_accepts_a_stdio_entry_without_type(fake_claude, profile):
    _add(profile, "tools", {"command": "tool"})
    assert _servers(profile) == {"tools": {"command": "tool"}}


@pytest.mark.parametrize(
    "args",
    [
        ["mcp", "add-json", "a", "{}", "extra", "--scope", "user"],
        ["mcp", "remove", "a", "extra", "-s", "user"],
    ],
)
def test_mcp_commands_refuse_extra_arguments(fake_claude, profile, args):
    _add(profile, "a", {"type": "stdio", "command": "a"})
    with pytest.raises(ClaudeCliError, match="argument"):
        ClaudeCli(profile).run(args)
    assert _servers(profile) == {"a": {"type": "stdio", "command": "a"}}
