import json

import pytest

from claude_sync import mcp
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, McpServer
from claude_sync.sync import Difference


@pytest.fixture
def profile(tmp_path):
    directory = tmp_path / "profiles" / "perso"
    directory.mkdir(parents=True)
    return directory


def _seed(profile, servers, **other):
    (profile / ".claude.json").write_text(json.dumps({**other, "mcpServers": servers}))


def test_observe_reads_the_user_scope_servers_with_type_defaults(profile):
    _seed(
        profile,
        {
            "plain": {"command": "tool"},
            "idea": {"type": "streamable-http", "url": "https://example.invalid/mcp"},
            "events": {"type": "sse", "url": "https://example.invalid/sse"},
        },
        oauthAccount={},
    )
    assert mcp.observe(profile) == {
        "plain": {"type": "stdio", "command": "tool"},
        "idea": {"type": "http", "url": "https://example.invalid/mcp"},
        "events": {"type": "sse", "url": "https://example.invalid/sse"},
    }


def test_observe_without_servers_is_empty(profile):
    assert mcp.observe(profile) == {}
    (profile / ".claude.json").write_text("{}")
    assert mcp.observe(profile) == {}


@pytest.mark.parametrize("servers", [[], {"a": "tool"}])
def test_observe_refuses_an_unknown_shape(profile, servers):
    _seed(profile, servers)
    with pytest.raises(ClaudeSyncError, match=r"\.claude\.json.*mcpServers"):
        mcp.observe(profile)


def test_desired_stdio_writes_type_and_resolves_each_reference(fake_keychain):
    fake_keychain.set("service-x", "s3cr3t")
    server = McpServer(
        "tools",
        "stdio",
        command="tool",
        args=("--dir", "${HOME}"),
        env={"TOKEN": "env:SERVICE_TOKEN", "MODE": "value:debug", "KEY": "keychain:service-x"},
    )
    assert mcp.desired(server) == {
        "type": "stdio",
        "command": "tool",
        "args": ["--dir", "${HOME}"],
        "env": {"TOKEN": "${SERVICE_TOKEN}", "MODE": "debug", "KEY": "s3cr3t"},
    }


def test_desired_remote_writes_type_url_and_headers():
    server = McpServer("idea", "http", url="https://example.invalid/mcp")
    assert mcp.desired(server) == {
        "type": "http",
        "url": "https://example.invalid/mcp",
        "headers": {},
    }
    server = McpServer("events", "sse", url="u", headers={"Authorization": "value:Bearer ${T}"})
    assert mcp.desired(server)["headers"] == {"Authorization": "Bearer ${T}"}


def test_desired_names_the_server_key_and_reference_of_a_missing_keychain_item(fake_keychain):
    server = McpServer("idea", "http", url="u", headers={"Authorization": "keychain:service-x"})
    with pytest.raises(ClaudeSyncError) as caught:
        mcp.desired(server)
    message = str(caught.value)
    assert "'idea'" in message
    assert "headers.Authorization" in message
    assert "keychain:service-x" in message


def _declared(*servers):
    return Manifest((), (), None, mcp=servers)


def test_diff_reports_missing_and_unlisted_servers_and_nothing_for_equal_ones():
    declared = _declared(
        McpServer("tools", "stdio", command="tool"),
        McpServer("idea", "http", url="https://example.invalid/mcp"),
    )
    observed = {
        "idea": {"type": "http", "url": "https://example.invalid/mcp"},
        "old": {"type": "sse", "url": "u"},
    }
    assert mcp.diff(declared, observed) == [
        Difference("mcp-missing", "tools", "stdio", None),
        Difference("mcp-unlisted", "old", None, "sse"),
    ]


def test_diff_names_the_changed_fields_of_a_server_without_any_value(fake_keychain):
    fake_keychain.set("service-x", "declared-secret")
    declared = _declared(
        McpServer(
            "idea",
            "http",
            url="https://example.invalid/mcp",
            headers={
                "Authorization": "keychain:service-x",
                "X-Mode": "value:fast",
                "X-Same": "keychain:service-x",
            },
        ),
        McpServer("tools", "stdio", command="tool", args=("a",), env={"T": "env:T"}),
        McpServer("same", "stdio", command="tool"),
    )
    observed = {
        "idea": {
            "type": "http",
            "url": "https://example.invalid/other",
            "headers": {
                "Authorization": "observed-secret",
                "X-Mode": "fast",
                "X-Old": "gone",
                "X-Same": "declared-secret",
            },
        },
        "tools": {"type": "stdio", "command": "other", "args": ["b"], "env": {}},
        "same": {"type": "stdio", "command": "tool"},
    }
    differences = mcp.diff(declared, observed)
    assert differences == [
        Difference("mcp-changed", "idea", None, "url, headers.Authorization, headers.X-Old"),
        Difference("mcp-changed", "tools", None, "command, args, env.T"),
    ]
    assert "secret" not in repr(differences)


def test_diff_reports_a_changed_transport():
    declared = _declared(McpServer("idea", "sse", url="u"))
    observed = {"idea": {"type": "http", "url": "u"}}
    assert mcp.diff(declared, observed) == [Difference("mcp-changed", "idea", None, "type")]


def test_diff_reports_an_unresolvable_reference_as_drift_and_compares_the_rest(fake_keychain):
    fake_keychain.set("service-y", "kept-secret")
    declared = _declared(
        McpServer(
            "idea",
            "http",
            url="u",
            headers={"Authorization": "keychain:service-x", "X-Key": "keychain:service-y"},
        )
    )
    observed = {"idea": {"type": "http", "url": "u", "headers": {"Authorization": "secret"}}}
    differences = mcp.diff(declared, observed)
    assert differences == [
        Difference(
            "mcp-secret",
            "idea",
            "headers.Authorization",
            "keychain:service-x: Keychain item not found",
        ),
        Difference("mcp-changed", "idea", None, "headers.X-Key"),
    ]
    assert all(d.drift for d in differences)
    assert "secret" not in repr(differences).replace("mcp-secret", "")


@pytest.mark.parametrize(
    ("entry", "fields"),
    [
        ({"type": "stdio", "command": "t", "cwd": "/tmp", "timeout": 5}, "cwd, timeout"),
        ({"type": "http", "url": "u", "oauth": {"clientId": "x"}}, "oauth"),
        ({"type": "stdio", "command": "t", "url": "u"}, "url"),
        ({"type": "http", "url": "u", "env": {}}, "env"),
        ({"type": "ws", "url": "u"}, "type"),
        ({"type": "stdio"}, "command"),
        ({"type": "stdio", "command": 3}, "command"),
        ({"type": "stdio", "command": "t", "args": "a"}, "args"),
        ({"type": "stdio", "command": "t", "args": [1]}, "args"),
        ({"type": "stdio", "command": "t", "env": {"A": 1}}, "env"),
        ({"type": "stdio", "command": "t", "env": []}, "env"),
        ({"type": "sse"}, "url"),
        ({"type": "http", "url": 3}, "url"),
        ({"type": ["http"], "url": "u"}, "type"),
        ({"type": None, "command": "t"}, "type"),
        ({"type": "sse", "url": "u", "headers": {"A": None}}, "headers"),
    ],
)
def test_diff_reports_a_server_with_unmodelled_fields_as_unmanaged_information(entry, fields):
    differences = mcp.diff(_declared(), {"x": entry})
    assert differences == [Difference("mcp-unmanaged", "x", None, fields)]
    assert not differences[0].drift


def test_a_declared_server_observed_unmanaged_is_drift_naming_the_fields():
    declared = _declared(McpServer("x", "stdio", command="t"))
    differences = mcp.diff(declared, {"x": {"type": "stdio", "command": "t", "cwd": "/"}})
    assert differences == [
        Difference("mcp-changed", "x", None, "cwd"),
        Difference("mcp-unmanaged", "x", None, "cwd"),
    ]


def test_plan_adds_a_missing_server_with_its_values_masked_in_what_is_shown(fake_keychain):
    fake_keychain.set("service-x", "s3cr3t")
    server = McpServer(
        "tools", "stdio", command="tool", env={"KEY": "keychain:service-x", "T": "env:T"}
    )
    [action] = mcp.plan(_declared(server), {}, prune=False)
    entry = {"type": "stdio", "command": "tool", "args": [], "env": {"KEY": "s3cr3t", "T": "${T}"}}
    assert action.args == ("mcp", "add-json", "tools", json.dumps(entry), "--scope", "user")
    assert not action.confirm
    masked = '{"type": "stdio", "command": "tool", "args": [], "env": {"KEY": "***", "T": "***"}}'
    assert action.shown == f"claude mcp add-json tools '{masked}' --scope user"
    assert action.description == f"run: {action.shown}"
    assert "s3cr3t" not in action.shown + action.description


def test_plan_replaces_a_changed_stdio_server_without_confirmation():
    declared = _declared(
        McpServer("tools", "stdio", command="tool"), McpServer("same", "stdio", command="s")
    )
    observed = {
        "tools": {"type": "stdio", "command": "old"},
        "same": {"type": "stdio", "command": "s"},
    }
    remove, add = mcp.plan(declared, observed, prune=False)
    assert remove.args == ("mcp", "remove", "tools", "-s", "user")
    assert remove.shown == "claude mcp remove tools -s user"
    assert remove.description == "run: claude mcp remove tools -s user"
    assert add.args[:3] == ("mcp", "add-json", "tools")
    assert not remove.confirm and not add.confirm


@pytest.mark.parametrize("kind", ["http", "sse"])
def test_plan_replaces_a_changed_remote_server_after_an_oauth_confirmation(kind):
    declared = _declared(McpServer("idea", "http", url="https://example.invalid/new"))
    observed = {"idea": {"type": kind, "url": "https://example.invalid/old"}}
    remove, add = mcp.plan(declared, observed, prune=False)
    assert remove.args == ("mcp", "remove", "idea", "-s", "user")
    assert remove.confirm and add.confirm
    assert "OAuth sign-in" in remove.description
    assert remove.description.startswith("run: claude mcp remove idea -s user")


def test_plan_prunes_unlisted_servers_after_confirmation_but_never_unmanaged_ones():
    observed = {
        "old": {"type": "stdio", "command": "t"},
        "idea": {"type": "http", "url": "u"},
        "custom": {"type": "stdio", "command": "t", "cwd": "/"},
    }
    assert mcp.plan(_declared(), observed, prune=False) == []
    old, idea = mcp.plan(_declared(), observed, prune=True)
    assert old.args == ("mcp", "remove", "old", "-s", "user")
    assert old.description == "run: claude mcp remove old -s user"
    assert idea.args == ("mcp", "remove", "idea", "-s", "user")
    assert "OAuth sign-in" in idea.description
    assert old.confirm and idea.confirm


def test_plan_refuses_a_declared_server_whose_entry_is_unmanaged():
    declared = _declared(McpServer("custom", "stdio", command="t"))
    observed = {"custom": {"type": "stdio", "command": "t", "cwd": "/"}}
    with pytest.raises(ClaudeSyncError, match=r"'custom'.*cwd"):
        mcp.plan(declared, observed, prune=True)


def test_plan_stops_on_an_unresolvable_reference_before_listing_anything(fake_keychain):
    declared = _declared(
        McpServer("a", "stdio", command="t"),
        McpServer("b", "sse", url="u", headers={"A": "keychain:service-x"}),
    )
    with pytest.raises(ClaudeSyncError, match=r"'b'.*headers\.A.*keychain:service-x"):
        mcp.plan(declared, {}, prune=False)


def test_import_turns_literals_into_env_references_and_keeps_placeholders(profile, capsys):
    _seed(
        profile,
        {
            "tools": {
                "command": "tool",
                "args": ["--dir", "${HOME}"],
                "env": {"API_KEY": "s3cr3t", "TOKEN": "${SERVICE_TOKEN}", "MODE": "${M:-fast}"},
            },
            "my-idea": {
                "type": "http",
                "url": "https://example.invalid/mcp",
                "headers": {"Authorization": "Bearer ${T}", "X-Api-Key": "k3y"},
            },
        },
    )
    servers, exports = mcp.import_servers(profile, None)
    assert servers == (
        McpServer(
            "my-idea",
            "http",
            url="https://example.invalid/mcp",
            headers={"Authorization": "value:Bearer ${T}", "X-Api-Key": "env:MY_IDEA_X_API_KEY"},
        ),
        McpServer(
            "tools",
            "stdio",
            command="tool",
            args=("--dir", "${HOME}"),
            env={
                "API_KEY": "env:TOOLS_API_KEY",
                "TOKEN": "env:SERVICE_TOKEN",
                "MODE": "value:${M:-fast}",
            },
        ),
    )
    assert exports == ["MY_IDEA_X_API_KEY", "TOOLS_API_KEY"]
    captured = capsys.readouterr()
    assert "s3cr3t" not in captured.out + captured.err
    assert "k3y" not in captured.out + captured.err


def test_import_refuses_two_keys_giving_the_same_variable(profile):
    _seed(
        profile, {"t": {"type": "sse", "url": "u", "headers": {"X-Key": "v4lue", "X_KEY": "other"}}}
    )
    with pytest.raises(ClaudeSyncError) as caught:
        mcp.import_servers(profile)
    message = str(caught.value)
    assert all(word in message for word in ("'t'", "X-Key", "X_KEY", "T_X_KEY"))
    assert "v4lue" not in message


def test_import_refuses_a_variable_starting_with_a_digit(profile):
    _seed(profile, {"1tool": {"command": "t", "env": {"KEY": "v4lue"}}})
    with pytest.raises(ClaudeSyncError, match=r"'1tool'.*KEY.*1TOOL_KEY.*digit") as caught:
        mcp.import_servers(profile)
    assert "v4lue" not in str(caught.value)


def test_import_refuses_keys_of_two_servers_giving_the_same_variable(profile):
    _seed(
        profile,
        {
            "a-b": {"command": "t", "env": {"C": "one"}},
            "a": {"command": "t", "env": {"B_C": "two"}},
        },
    )
    with pytest.raises(ClaudeSyncError, match=r"'a-b'.*env\.B_C of 'a'.*A_B_C"):
        mcp.import_servers(profile)


def test_import_keeps_previous_references_that_still_produce_the_observed_value(
    profile, fake_keychain, capsys
):
    fake_keychain.set("service-x", "s3cr3t")
    fake_keychain.set("service-y", "rotated")
    _seed(
        profile,
        {
            "tools": {
                "command": "tool",
                "env": {"KEY": "s3cr3t", "OLD": "stale", "MODE": "debug", "NEW": "fresh"},
            }
        },
    )
    previous = _declared(
        McpServer(
            "tools",
            "stdio",
            command="tool",
            env={"KEY": "keychain:service-x", "OLD": "keychain:service-y", "MODE": "value:debug"},
        )
    )
    [server], exports = mcp.import_servers(profile, previous)
    assert server.env == {
        "KEY": "keychain:service-x",
        "OLD": "env:TOOLS_OLD",
        "MODE": "value:debug",
        "NEW": "env:TOOLS_NEW",
    }
    assert exports == ["TOOLS_OLD", "TOOLS_NEW"]
    captured = capsys.readouterr()
    for secret in ("s3cr3t", "rotated", "stale", "fresh"):
        assert secret not in captured.out + captured.err


def test_import_keeps_an_unresolvable_previous_keychain_reference_with_a_warning(
    profile, fake_keychain, capsys
):
    _seed(profile, {"idea": {"type": "http", "url": "u", "headers": {"Authorization": "s3cr3t"}}})
    previous = _declared(
        McpServer("idea", "http", url="u", headers={"Authorization": "keychain:service-x"})
    )
    [server], exports = mcp.import_servers(profile, previous)
    assert server.headers == {"Authorization": "keychain:service-x"}
    assert exports == []
    err = capsys.readouterr().err
    assert "warning" in err
    assert "'idea'" in err and "headers.Authorization" in err and "keychain:service-x" in err
    assert "s3cr3t" not in err


def test_import_ignores_previous_references_of_another_server_or_table(profile):
    _seed(profile, {"tools": {"command": "tool", "env": {"MODE": "debug"}}})
    previous = _declared(McpServer("other", "stdio", command="t", env={"MODE": "value:debug"}))
    [server], _ = mcp.import_servers(profile, previous)
    assert server.env == {"MODE": "env:TOOLS_MODE"}


def test_import_skips_an_unmanaged_server_with_a_warning_naming_the_fields(profile, capsys):
    _seed(
        profile,
        {
            "custom": {"command": "t", "cwd": "/", "env": {"KEY": "s3cr3t"}},
            "plain": {"command": "t"},
        },
    )
    servers, exports = mcp.import_servers(profile)
    assert [s.name for s in servers] == ["plain"]
    assert exports == []
    err = capsys.readouterr().err
    assert "warning" in err and "'custom'" in err and "cwd" in err
    assert "s3cr3t" not in err


@pytest.mark.parametrize(
    ("name", "entry"),
    [("bad name", {"command": "t"}), ("empty", {"command": ""}), ("e", {"type": "sse", "url": ""})],
)
def test_import_skips_a_server_the_manifest_would_reject_with_a_warning(
    profile, capsys, name, entry
):
    _seed(profile, {name: {**entry, "env": {"K": "s3cr3t"}} if "command" in entry else entry})
    assert mcp.import_servers(profile) == ((), [])
    err = capsys.readouterr().err
    assert "warning" in err and repr(name) in err
    assert "s3cr3t" not in err


def test_an_action_repr_never_shows_the_resolved_arguments(fake_keychain):
    fake_keychain.set("service-x", "s3cr3t")
    server = McpServer("idea", "http", url="u", headers={"Authorization": "keychain:service-x"})
    [action] = mcp.plan(_declared(server), {}, prune=False)
    assert "s3cr3t" in " ".join(action.args)
    assert "s3cr3t" not in repr(action)
    assert "***" in repr(action)


def test_a_skipped_server_reserves_no_variable(profile):
    _seed(
        profile,
        {
            "bad name": {"command": "t", "env": {"K": "one"}},
            "bad_name": {"command": "t", "env": {"K": "two"}},
        },
    )
    [server], exports = mcp.import_servers(profile)
    assert server.env == {"K": "env:BAD_NAME_K"}
    assert exports == ["BAD_NAME_K"]


@pytest.mark.parametrize("placeholder", ["${TOOLS_B}", None])
def test_import_refuses_a_generated_variable_another_key_of_the_server_names(
    profile, fake_keychain, placeholder
):
    # The other key names TOOLS_B either as an exact placeholder or by a kept reference.
    _seed(profile, {"tools": {"command": "t", "env": {"A": "${TOOLS_B}", "B": "v4lue"}}})
    previous = None
    if placeholder is None:
        previous = _declared(McpServer("tools", "stdio", command="t", env={"A": "env:TOOLS_B"}))
    with pytest.raises(ClaudeSyncError) as caught:
        mcp.import_servers(profile, previous)
    message = str(caught.value)
    assert all(word in message for word in ("'tools'", "env.A", "env.B", "TOOLS_B"))
    assert "v4lue" not in message


def test_import_lets_servers_share_a_placeholder_variable(profile):
    _seed(
        profile,
        {
            "a": {"command": "t", "env": {"T": "${GITHUB_TOKEN}"}},
            "b": {"command": "t", "env": {"T": "${GITHUB_TOKEN}"}},
        },
    )
    servers, exports = mcp.import_servers(profile)
    assert [s.env for s in servers] == [{"T": "env:GITHUB_TOKEN"}] * 2
    assert exports == []


def test_import_refuses_a_placeholder_naming_a_variable_an_earlier_key_generated(profile):
    _seed(profile, {"tools": {"command": "t", "env": {"B": "v4lue", "A": "${TOOLS_B}"}}})
    with pytest.raises(ClaudeSyncError, match=r"'tools'.*env\.A.*env\.B.*TOOLS_B"):
        mcp.import_servers(profile)


def test_prune_never_removes_a_declared_server():
    declared = _declared(
        McpServer("tools", "stdio", command="t"), McpServer("idea", "http", url="u")
    )
    observed = {
        "tools": {"type": "stdio", "command": "t"},
        "idea": {"type": "http", "url": "u"},
        "old": {"type": "stdio", "command": "t"},
    }
    [action] = mcp.plan(declared, observed, prune=True)
    assert action.args == ("mcp", "remove", "old", "-s", "user")


def test_a_declared_unmanaged_server_is_reported_changed_once_by_its_unmodelled_fields():
    declared = _declared(McpServer("x", "stdio", command="t"))
    observed = {"x": {"type": "stdio", "command": "other", "cwd": "/"}}
    assert mcp.diff(declared, observed) == [
        Difference("mcp-changed", "x", None, "cwd"),
        Difference("mcp-unmanaged", "x", None, "cwd"),
    ]


def test_observe_and_import_treat_a_non_string_type_as_unmanaged(profile, capsys):
    _seed(profile, {"odd": {"type": ["http"], "url": "u"}})
    observed = mcp.observe(profile)
    assert mcp.diff(_declared(), observed) == [Difference("mcp-unmanaged", "odd", None, "type")]
    assert mcp.plan(_declared(), observed, prune=True) == []
    assert mcp.import_servers(profile) == ((), [])
    assert "'odd'" in capsys.readouterr().err


def test_import_ignores_a_previous_reference_of_the_same_key_in_another_table(profile):
    _seed(profile, {"tools": {"type": "http", "url": "u", "headers": {"A": "debug"}}})
    previous = _declared(McpServer("tools", "stdio", command="t", env={"A": "value:debug"}))
    [server], exports = mcp.import_servers(profile, previous)
    assert server.headers == {"A": "env:TOOLS_A"}
    assert exports == ["TOOLS_A"]


def test_a_digit_leading_variable_aborts_import_even_for_a_server_the_manifest_rejects(profile):
    _seed(profile, {"1 bad": {"command": "t", "env": {"K": "v4lue"}}})
    with pytest.raises(ClaudeSyncError, match=r"'1 bad'.*env\.K.*1_BAD_K.*digit") as caught:
        mcp.import_servers(profile)
    assert "v4lue" not in str(caught.value)


def test_import_lets_two_keys_of_a_server_share_a_placeholder_variable(profile):
    _seed(profile, {"tools": {"command": "t", "env": {"A": "${SAME}", "B": "${SAME}"}}})
    [server], exports = mcp.import_servers(profile)
    assert server.env == {"A": "env:SAME", "B": "env:SAME"}
    assert exports == []


def test_import_lets_a_placeholder_use_a_variable_another_server_made(profile):
    _seed(
        profile,
        {
            "a": {"command": "t", "env": {"KEY": "v4lue"}},
            "b": {"command": "t", "env": {"T": "${A_KEY}"}},
        },
    )
    servers, exports = mcp.import_servers(profile)
    assert [s.env for s in servers] == [{"KEY": "env:A_KEY"}, {"T": "env:A_KEY"}]
    assert exports == ["A_KEY"]
