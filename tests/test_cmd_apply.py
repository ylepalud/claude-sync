import io
import json
import subprocess

import pytest

from claude_sync import manifest, mcp, paths, sync
from claude_sync.cli import main
from claude_sync.errors import ClaudeSyncError

ORG = "00000000-0000-0000-0000-000000000001"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


class Setup:
    """A `perso` profile directory, an upstream marketplace and a manifest to write."""

    def __init__(self, fake_claude):
        self.fake = fake_claude
        self.directory = paths.profile_dir("perso")
        self.repo, self.commit = fake_claude.make_upstream(
            "tools", {"lint": "1.0.0", "fmt": "1.0.0"}, branches=("main", "old")
        )
        fake_claude.seed(self.directory, {"upstream": {"acme/tools": str(self.repo)}})

    def declare(self, plugins, *, ref=None, commit=True, account=None, servers=(), tools=()):
        market = manifest.Marketplace(
            "tools", "github:acme/tools", ref, self.commit if commit else None
        )
        declared = manifest.Manifest(
            (market,), tuple(plugins), account, mcp=tuple(servers), tools=tuple(tools)
        )
        manifest.save(self.directory / manifest.MANIFEST_FILE, declared)

    def state(self):
        return self.fake.state(self.directory)

    def calls(self):
        return self.fake.calls(self.directory)

    def installed(self):
        return {p["id"]: p["enabled"] for p in self.state().get("plugins", [])}


@pytest.fixture
def setup(fake_claude):
    return Setup(fake_claude)


def test_converge_a_new_profile_then_status_is_clean(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)])
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert setup.installed() == {"lint@tools": True}
    assert run(capsys, "status", "--profile", "perso")[0] == 0


def test_a_disabled_plugin_is_installed_then_disabled(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", False)])
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    assert setup.installed() == {"lint@tools": False}


def changes(calls):
    return [c for c in calls if c[-1] != "--json"]


def test_a_matching_profile_runs_nothing(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)])
    run(capsys, "apply", "--profile", "perso")
    before = len(setup.calls())
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert changes(setup.calls()[before:]) == []


def installed_with_ref_old(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], ref="old")
    assert run(capsys, "apply", "--profile", "perso")[0] == 0


def test_a_re_pin_needs_a_confirmation(capsys, setup):
    installed_with_ref_old(capsys, setup)
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], ref="main")
    calls = len(setup.calls())
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 3
    assert len(setup.calls()) == calls + 2  # only the two observation calls
    assert setup.state()["marketplaces"][0]["ref"] == "old"
    assert "plugin marketplace remove tools" in err
    assert "uninstalls" in err and "data" in err


def test_a_confirmed_re_pin_restores_the_disabled_state(capsys, setup):
    installed_with_ref_old(capsys, setup)
    setup.declare(
        [
            manifest.Plugin("lint@tools", "1.0.0", True),
            manifest.Plugin("fmt@tools", "1.0.0", False),
        ],
        ref="main",
    )
    run(capsys, "apply", "--profile", "perso", "--yes")
    assert setup.state()["marketplaces"][0]["ref"] == "main"
    assert setup.installed() == {"lint@tools": True, "fmt@tools": False}


def test_declining_the_confirmation_changes_nothing(capsys, setup, monkeypatch):
    installed_with_ref_old(capsys, setup)
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], ref="main")
    calls = len(setup.calls())
    stdin = io.StringIO()
    stdin.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert "cancelled" in err
    assert len(setup.calls()) == calls + 2
    assert setup.state()["marketplaces"][0]["ref"] == "old"


def seed_extras(setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)])
    run_ok = main(["apply", "--profile", "perso"])
    assert run_ok == 0
    state = setup.state()
    state["plugins"].append(
        {"id": "fmt@tools", "version": "1.0.0", "scope": "user", "enabled": True}
    )
    setup.fake.seed(setup.directory, state)


def test_unlisted_plugins_stay_without_prune(capsys, setup):
    seed_extras(setup)
    capsys.readouterr()
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert "fmt@tools" in setup.installed()
    code, out, _ = run(capsys, "status", "--profile", "perso", "--json")
    assert code == 4
    assert [(d["kind"], d["subject"]) for d in json.loads(out)["differences"]] == [
        ("unlisted", "fmt@tools")
    ]


def test_prune_removes_unlisted_plugins_after_confirmation(capsys, setup):
    seed_extras(setup)
    capsys.readouterr()
    code, _, err = run(capsys, "apply", "--profile", "perso", "--prune")
    assert code == 3
    assert "fmt@tools" in err
    assert "fmt@tools" in setup.installed()
    code, _, _ = run(capsys, "apply", "--profile", "perso", "--prune", "--yes")
    assert code == 0
    assert setup.installed() == {"lint@tools": True}


def test_a_failing_command_stops_apply(capsys, setup, fake_claude):
    setup.declare(
        [manifest.Plugin("lint@tools", "1.0.0", True), manifest.Plugin("fmt@tools", "1.0.0", True)]
    )
    state = setup.state()
    state["fail"] = {"plugin install": "boom: approval needed"}
    fake_claude.seed(setup.directory, state)
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 1
    assert "claude plugin install" in err and "boom: approval needed" in err
    assert [c for c in setup.calls() if c[:2] == ["plugin", "install"]] == [
        ["plugin", "install", "fmt@tools", "--scope", "user"]
    ]


def test_an_upstream_version_change_exits_four_with_the_hint(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)])
    catalog = setup.repo / ".claude-plugin" / "marketplace.json"
    catalog.write_text(catalog.read_text().replace("1.0.0", "1.1.0"))
    subprocess.run(["git", "-C", str(setup.repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(setup.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        + ["commit", "--quiet", "-m", "bump"],
        check=True,
    )
    code, out, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 4
    assert "lint@tools" in out and "1.0.0" in out and "1.1.0" in out
    assert "accept with: claude-sync import" in out
    assert setup.installed() == {"lint@tools": True}


def test_a_moved_commit_is_reported_too(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)])
    manifest_file = setup.directory / manifest.MANIFEST_FILE
    manifest_file.write_text(manifest_file.read_text().replace(setup.commit, "f" * 40))
    code, out, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 4
    assert "f" * 40 in out and setup.commit in out
    assert "accept with: claude-sync import" in out


def test_dry_run_prints_the_commands_and_changes_nothing(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], account=manifest.Account(ORG))
    code, out, _ = run(capsys, "apply", "--profile", "perso", "--dry-run")
    assert code == 0
    assert "would run: claude plugin marketplace add acme/tools" in out
    assert "would run: claude plugin install lint@tools --scope user" in out
    assert "forceLoginOrgUUID" in out
    assert not (setup.directory / "settings.json").exists()
    assert changes(setup.calls()) == []


def test_dry_run_does_not_ask_for_a_confirmation(capsys, setup):
    installed_with_ref_old(capsys, setup)
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], ref="main")
    code, out, _ = run(capsys, "apply", "--profile", "perso", "--dry-run")
    assert code == 0
    assert "would run: claude plugin marketplace remove tools" in out


def test_the_guide_keys_are_written_and_other_keys_kept(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], account=manifest.Account(ORG))
    (setup.directory / "settings.json").write_text('{"theme": "dark"}')
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    written = json.loads((setup.directory / "settings.json").read_text())
    assert written == {"theme": "dark", "forceLoginMethod": "claudeai", "forceLoginOrgUUID": [ORG]}
    assert run(capsys, "status", "--profile", "perso")[0] == 0


def test_without_an_account_settings_are_not_touched(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)])
    run(capsys, "apply", "--profile", "perso")
    assert not (setup.directory / "settings.json").exists()


def test_a_missing_profile_exits_one_with_the_hint(capsys, fake_claude):
    code, _, err = run(capsys, "apply", "--profile", "work")
    assert code == 1
    assert "claude-sync profile create work" in err


def test_dry_run_does_not_mention_a_guide_already_in_place(capsys, setup):
    setup.declare([manifest.Plugin("lint@tools", "1.0.0", True)], account=manifest.Account(ORG))
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    code, out, _ = run(capsys, "apply", "--profile", "perso", "--dry-run")
    assert code == 0
    assert "forceLoginOrgUUID" not in out


def test_the_confirmation_lists_only_the_confirm_actions(capsys, setup):
    installed_with_ref_old(capsys, setup)
    setup.declare(
        [manifest.Plugin("lint@tools", "1.0.0", True), manifest.Plugin("fmt@tools", "1.0.0", True)],
        ref="main",
    )
    state = setup.state()
    state["plugins"].append({"id": "x@tools", "version": "1", "scope": "user", "enabled": True})
    setup.fake.seed(setup.directory, state)
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 3
    assert "claude plugin marketplace remove tools" in err
    assert "claude plugin install lint@tools" in err
    assert "enable" not in err and "disable" not in err


def test_the_question_leaves_out_actions_that_need_no_confirmation():
    from claude_sync.commands import apply as apply_cmd

    actions = [
        sync.Action(("plugin", "marketplace", "remove", "tools"), True),
        sync.Action(("plugin", "enable", "other@elsewhere", "--scope", "user"), False),
    ]
    question = apply_cmd._question(actions)
    assert "claude plugin marketplace remove tools" in question
    assert "other@elsewhere" not in question


# Skills


def declare_skills(setup, upstream, *, commit=None, name="tools", plugins=True, profile="perso"):
    """Write the manifest of `profile`: the plugin marketplace of `setup` plus two skills."""
    market = manifest.Marketplace("tools", "github:acme/tools", None, setup.commit)
    declared = manifest.Manifest(
        (market,) if plugins else (),
        (manifest.Plugin("lint@tools", "1.0.0", True),) if plugins else (),
        None,
        (manifest.SkillSource(name, upstream.source, None, commit or upstream.first),),
        tuple(manifest.Skill(f"{s}@{name}", f"skills/{s}", None) for s in ("alpha", "beta")),
    )
    manifest.save(paths.profile_dir(profile) / manifest.MANIFEST_FILE, declared)
    return declared


def skill_links(profile="perso"):
    directory = paths.profile_dir(profile) / "skills"
    return {p.name: p.readlink() for p in sorted(directory.iterdir())} if directory.exists() else {}


def test_converge_a_profile_with_plugins_and_skills_then_status_is_clean(
    capsys, setup, skills_upstream
):
    declare_skills(setup, skills_upstream)
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    clone = paths.config_home() / "sources" / "tools"
    assert setup.installed() == {"lint@tools": True}
    assert skill_links() == {"alpha": clone / "skills" / "alpha", "beta": clone / "skills" / "beta"}
    assert run(capsys, "status", "--profile", "perso")[0] == 0


def test_dry_run_lists_plugin_and_skill_actions_and_changes_nothing(capsys, setup, skills_upstream):
    declare_skills(setup, skills_upstream)
    code, out, _ = run(capsys, "apply", "--profile", "perso", "--dry-run")
    assert code == 0
    lines = out.splitlines()
    sources = "~/.config/claude-sync/sources/tools"
    skills_dir = "~/.config/claude-sync/profiles/perso/skills"
    assert lines[0].startswith("would run: claude plugin marketplace add")
    assert lines[-4:] == [
        f"would run: git clone {skills_upstream.source[4:]} {sources}",
        f"would run: git -C {sources} checkout --detach {skills_upstream.first}",
        f"would link {skills_dir}/alpha -> {sources}/skills/alpha",
        f"would link {skills_dir}/beta -> {sources}/skills/beta",
    ]
    assert setup.installed() == {}
    assert not (paths.config_home() / "sources").exists()


def converged(capsys, setup, upstream, **kwargs):
    declare_skills(setup, upstream, **kwargs)
    assert run(capsys, "apply", "--profile", "perso")[0] == 0


def foreign_link(name="alpha"):
    foreign = paths.profile_dir("perso").parent.parent / "foreign" / name
    foreign.mkdir(parents=True)
    link = paths.profile_dir("perso") / "skills" / name
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(foreign)
    return link, foreign


def test_replacing_a_foreign_link_needs_a_confirmation(capsys, setup, skills_upstream):
    declare_skills(setup, skills_upstream)
    link, foreign = foreign_link()
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 3
    assert f"replace {paths.display(link)} -> " in err
    assert link.readlink() == foreign
    assert setup.installed() == {}
    assert not (paths.config_home() / "sources").exists()
    assert run(capsys, "apply", "--profile", "perso", "--yes")[0] == 0
    assert link.readlink() == paths.config_home() / "sources" / "tools" / "skills" / "alpha"


def test_prune_removes_only_undeclared_links_into_sources(capsys, setup, skills_upstream):
    converged(capsys, setup, skills_upstream)
    directory = paths.profile_dir("perso") / "skills"
    clone = paths.config_home() / "sources" / "tools"
    (directory / "stale").symlink_to(clone / "skills" / "alpha")
    (directory / "mine").mkdir()
    foreign_link("elsewhere")
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    assert (directory / "stale").is_symlink()
    code, _, err = run(capsys, "apply", "--profile", "perso", "--prune")
    assert code == 3 and "remove " in err
    assert run(capsys, "apply", "--profile", "perso", "--prune", "--yes")[0] == 0
    assert sorted(p.name for p in directory.iterdir()) == ["alpha", "beta", "elsewhere", "mine"]


def test_a_real_directory_stops_apply_before_any_change(capsys, setup, skills_upstream):
    declare_skills(setup, skills_upstream)
    conflict = paths.profile_dir("perso") / "skills" / "alpha"
    conflict.mkdir(parents=True)
    (conflict / "SKILL.md").write_text("mine\n")
    code, _, err = run(capsys, "apply", "--profile", "perso", "--yes")
    assert code == 1
    assert "skills/alpha" in err
    assert (conflict / "SKILL.md").read_text() == "mine\n"
    assert setup.installed() == {}
    assert not (paths.config_home() / "sources").exists()


def test_two_profiles_share_one_clone(capsys, setup, skills_upstream):
    converged(capsys, setup, skills_upstream, plugins=False)
    clone = paths.config_home() / "sources" / "tools"
    inode = (clone / ".git").stat().st_ino  # the same clone, not a new one
    paths.profile_dir("work").mkdir(parents=True)
    declare_skills(setup, skills_upstream, plugins=False, profile="work")
    assert run(capsys, "apply", "--profile", "work")[0] == 0
    assert (clone / ".git").stat().st_ino == inode
    assert skill_links("work") == skill_links("perso")


def test_a_skill_changed_since_install_is_reported_with_exit_4(capsys, setup, skills_upstream):
    upstream = skills_upstream
    trees = {s: upstream.tree(upstream.first, s) for s in ("alpha", "beta")}
    market = manifest.Marketplace("tools", "github:acme/tools", None, setup.commit)
    declared = manifest.Manifest(
        (market,),
        (),
        None,
        (manifest.SkillSource("tools", upstream.source, None, upstream.second),),
        tuple(manifest.Skill(f"{s}@tools", f"skills/{s}", trees[s]) for s in ("alpha", "beta")),
    )
    manifest.save(setup.directory / manifest.MANIFEST_FILE, declared)
    code, out, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 4
    assert "skill-tree alpha@tools" in out
    assert "accept with: claude-sync import" in out


@pytest.mark.parametrize("name", ["import", "status", "apply"])
def test_help_mentions_skills_in_the_description_and_an_example(name, capsys):
    from claude_sync import registry

    command = next(c for c in registry.COMMANDS if c.name == name)
    assert "skill" in command.description
    assert any("skill" in explanation for _, explanation in command.examples)


def test_a_failing_plugin_action_leaves_the_skills_untouched(capsys, setup, skills_upstream):
    declare_skills(setup, skills_upstream)
    state = setup.state()
    state["fail"] = {"plugin install": "boom"}
    setup.fake.seed(setup.directory, state)
    code, _, err = run(capsys, "apply", "--profile", "perso", "--yes")
    assert code == 1 and "boom" in err
    assert skill_links() == {}
    assert not (paths.config_home() / "sources").exists()


# MCP servers

STDIO = manifest.McpServer("tools", "stdio", command="uvx", args=("srv",), env={"A": "value:one"})
HTTP = manifest.McpServer(
    "remote", "http", url="https://example.test/mcp", headers={"X-Id": "value:abc"}
)


def servers_of(setup):
    return mcp.observe(setup.directory)


def test_converge_one_stdio_and_one_http_server_then_status_is_clean(capsys, setup):
    setup.declare([], servers=[STDIO, HTTP])
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert servers_of(setup) == {
        "tools": {"type": "stdio", "command": "uvx", "args": ["srv"], "env": {"A": "one"}},
        "remote": {"type": "http", "url": "https://example.test/mcp", "headers": {"X-Id": "abc"}},
    }
    assert run(capsys, "status", "--profile", "perso")[0] == 0


def change_server(setup, name, **fields):
    """Rewrite an observed server in the profile's .claude.json, as a drift would."""
    file = setup.directory / mcp.STATE_FILE
    data = json.loads(file.read_text())
    data["mcpServers"][name].update(fields)
    file.write_text(json.dumps(data))


def converged_servers(capsys, setup, *servers):
    setup.declare([], servers=servers)
    assert run(capsys, "apply", "--profile", "perso")[0] == 0


def test_replacing_an_http_server_needs_a_confirmation(capsys, setup):
    converged_servers(capsys, setup, HTTP)
    change_server(setup, "remote", url="https://elsewhere.test/mcp")
    calls = len(setup.calls())
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 3
    assert "removes an http server: drops its OAuth sign-in" in err
    assert servers_of(setup)["remote"]["url"] == "https://elsewhere.test/mcp"
    assert not [c for c in setup.calls()[calls:] if c[0] == "mcp"]


def test_replacing_a_stdio_server_needs_no_confirmation(capsys, setup):
    converged_servers(capsys, setup, STDIO)
    change_server(setup, "tools", command="other")
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert servers_of(setup)["tools"]["command"] == "uvx"


def test_a_confirmed_http_replacement_is_applied(capsys, setup):
    converged_servers(capsys, setup, HTTP)
    change_server(setup, "remote", url="https://elsewhere.test/mcp")
    assert run(capsys, "apply", "--profile", "perso", "--yes")[0] == 0
    assert servers_of(setup)["remote"]["url"] == "https://example.test/mcp"


def test_prune_removes_unlisted_servers_but_skips_unmanaged_ones(capsys, setup):
    converged_servers(capsys, setup, STDIO)
    file = setup.directory / mcp.STATE_FILE
    data = json.loads(file.read_text())
    data["mcpServers"]["extra"] = {"type": "stdio", "command": "x"}
    data["mcpServers"]["odd"] = {"type": "stdio", "command": "y", "alwaysLoad": True}
    file.write_text(json.dumps(data))
    assert run(capsys, "apply", "--profile", "perso", "--yes")[0] == 0
    assert set(servers_of(setup)) == {"tools", "extra", "odd"}
    assert run(capsys, "apply", "--profile", "perso", "--prune", "--yes")[0] == 0
    assert set(servers_of(setup)) == {"tools", "odd"}


def test_apply_without_mcp_tables_leaves_servers_alone(capsys, setup):
    converged_servers(capsys, setup, STDIO)
    setup.declare([], servers=[STDIO])
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    assert not [c for c in setup.calls() if c[:2] == ["mcp", "remove"]]


SECRET = "s3cr3t-token-value"
KEYCHAIN_HEADER = manifest.McpServer(
    "remote", "http", url="https://example.test/mcp", headers={"Authorization": "keychain:svc-x"}
)


def test_a_missing_keychain_item_stops_apply_before_plugins_or_skills_change(
    capsys, setup, fake_keychain, skills_upstream
):
    declare_skills(setup, skills_upstream)
    declared = manifest.load(setup.directory / manifest.MANIFEST_FILE)
    manifest.save(
        setup.directory / manifest.MANIFEST_FILE,
        manifest.Manifest(
            declared.marketplaces,
            declared.plugins,
            declared.account,
            declared.skill_sources,
            declared.skills,
            (KEYCHAIN_HEADER,),
        ),
    )
    code, _, err = run(capsys, "apply", "--profile", "perso", "--yes")
    assert code == 1
    assert "remote" in err and "Authorization" in err and "keychain:svc-x" in err
    assert setup.installed() == {}
    assert skill_links() == {}
    assert servers_of(setup) == {}


def test_a_failing_add_json_does_not_leak_the_keychain_value(capsys, setup, fake_keychain):
    fake_keychain.set("svc-x", SECRET)
    setup.declare([], servers=[KEYCHAIN_HEADER])
    state = setup.state()
    state["fail"] = {"mcp add-json": "boom"}
    setup.fake.seed(setup.directory, state)
    code, out, err = run(capsys, "apply", "--profile", "perso")
    assert code == 1
    assert SECRET not in out and SECRET not in err
    assert "claude mcp add-json remote" in err and "***" in err and "boom" in err


def test_dry_run_and_confirmation_show_the_masked_command(capsys, setup, fake_keychain):
    fake_keychain.set("svc-x", SECRET)
    setup.declare([], servers=[STDIO, KEYCHAIN_HEADER])
    code, out, err = run(capsys, "apply", "--profile", "perso", "--dry-run")
    assert code == 0
    lines = [line for line in out.splitlines() if "mcp" in line]
    assert lines == [
        "would run: claude mcp add-json remote "
        """'{"type": "http", "url": "https://example.test/mcp", """
        """"headers": {"Authorization": "***"}}' """
        "--scope user",
        "would run: claude mcp add-json tools "
        """'{"type": "stdio", "command": "uvx", "args": ["srv"], "env": {"A": "***"}}' """
        "--scope user",
    ]
    assert SECRET not in out + err
    assert servers_of(setup) == {}


def test_the_confirmation_shows_the_masked_command(capsys, setup, fake_keychain):
    fake_keychain.set("svc-x", SECRET)
    setup.declare([], servers=[KEYCHAIN_HEADER])
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    fake_keychain.set("svc-x", "rotated-" + SECRET)
    code, out, err = run(capsys, "apply", "--profile", "perso")
    assert code == 3
    assert '"Authorization": "***"' in err and "drops its OAuth sign-in" in err
    assert SECRET not in out + err


def test_apply_help_mentions_mcp_servers(capsys):
    from claude_sync import registry

    command = next(c for c in registry.COMMANDS if c.name == "apply")
    assert "MCP" in command.description
    assert any("MCP" in explanation for _, explanation in command.examples)


def test_a_failing_add_json_that_echoes_its_arguments_does_not_leak_the_value(
    capsys, setup, fake_keychain
):
    secret = 'tok"en\\value-123'
    fake_keychain.set("svc-x", secret)
    setup.declare([], servers=[KEYCHAIN_HEADER, STDIO])
    escaped = json.dumps(secret)[1:-1]
    state = setup.state()
    state["fail"] = {"mcp add-json": f"bad request: raw={secret} json={escaped}"}
    setup.fake.seed(setup.directory, state)
    code, out, err = run(capsys, "apply", "--profile", "perso")
    assert code == 1
    assert secret not in out + err and escaped not in out + err
    assert "bad request: raw=*** json=***" in err


def test_mcp_actions_run_after_the_skill_actions(capsys, setup, skills_upstream):
    declare_skills(setup, skills_upstream)
    declared = manifest.load(setup.directory / manifest.MANIFEST_FILE)
    manifest.save(
        setup.directory / manifest.MANIFEST_FILE,
        manifest.Manifest(
            declared.marketplaces,
            declared.plugins,
            declared.account,
            declared.skill_sources,
            declared.skills,
            (STDIO,),
        ),
    )
    state = setup.state()
    state["fail"] = {"mcp add-json": "boom"}
    setup.fake.seed(setup.directory, state)
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 1 and "boom" in err
    assert set(skill_links()) == {"alpha", "beta"}


def converge_failing(setup, words):
    from claude_sync import converge
    from claude_sync.context import Context

    state = setup.state()
    state["fail"] = {words: "boom"}
    setup.fake.seed(setup.directory, state)
    ctx = Context(json=False, dry_run=False, yes=True, stdin_is_tty=False)
    with pytest.raises(ClaudeSyncError) as raised:
        converge.converge(setup.directory, ctx)
    return raised.value


def test_a_failing_add_json_says_to_run_apply_again(capsys, setup):
    setup.declare([], servers=[STDIO])
    error = converge_failing(setup, "mcp add-json")
    assert str(error).endswith("failed: boom (run apply again)")
    assert error.__cause__ is None


def test_a_failing_remove_has_no_run_again_hint(capsys, setup):
    converged_servers(capsys, setup, STDIO)
    change_server(setup, "tools", command="other")
    error = converge_failing(setup, "mcp remove")
    assert str(error).endswith("failed: boom")
    assert "run apply again" not in str(error)
    assert error.__cause__ is None


def test_the_longest_secret_is_scrubbed_first(capsys, setup):
    server = manifest.McpServer(
        "remote",
        "http",
        url="https://example.test/mcp",
        headers={"A": "value:token", "B": "value:token-with-suffix"},
    )
    setup.declare([], servers=[server])
    state = setup.state()
    state["fail"] = {"mcp add-json": "echo token-with-suffix"}
    setup.fake.seed(setup.directory, state)
    code, _, err = run(capsys, "apply", "--profile", "perso")
    assert code == 1
    assert "echo ***" in err and "suffix" not in err


def test_apply_refuses_a_too_old_tool_and_changes_nothing(capsys, setup, fake_tools):
    fake_tools.install("fakejq", "fakejq-1.6")
    setup.declare(
        [manifest.Plugin("lint@tools", "1.0.0", True)],
        tools=[manifest.Tool("fakejq", version="1.7")],
    )
    before = setup.state()
    calls = len(setup.calls())
    code, _, err = run(capsys, "apply", "--profile", "perso", "--yes")
    assert code == 1
    assert "fakejq" in err
    assert "too-old" in err
    assert "installed 1.6, required 1.7" in err
    assert "claude-sync doctor --fix" in err
    assert setup.state() == before
    assert len(setup.calls()) == calls


def test_apply_refuses_a_missing_tool_even_for_a_dry_run(capsys, setup, fake_tools):
    setup.declare(
        [manifest.Plugin("lint@tools", "1.0.0", True)],
        tools=[manifest.Tool("fakejq"), manifest.Tool("faketool")],
    )
    code, _, err = run(capsys, "apply", "--profile", "perso", "--dry-run")
    assert code == 1
    assert "fakejq" in err
    assert "faketool" in err
    assert "missing" in err


def test_apply_goes_on_when_the_tools_are_ok(capsys, setup, fake_tools):
    fake_tools.install("fakejq", "fakejq-1.7.1")
    setup.declare(
        [manifest.Plugin("lint@tools", "1.0.0", True)],
        tools=[manifest.Tool("fakejq", version="1.7")],
    )
    code, _, _ = run(capsys, "apply", "--profile", "perso")
    assert code == 0
    assert setup.installed() == {"lint@tools": True}


def test_apply_help_mentions_the_tool_check(capsys):
    _, out, _ = run(capsys, "apply", "--help")
    assert "doctor --fix" in out
