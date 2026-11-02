import io
import json
import subprocess

import pytest

from claude_sync import manifest, paths, sync
from claude_sync.cli import main

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

    def declare(self, plugins, *, ref=None, commit=True, account=None):
        market = manifest.Marketplace(
            "tools", "github:acme/tools", ref, self.commit if commit else None
        )
        declared = manifest.Manifest((market,), tuple(plugins), account)
        manifest.save(self.directory / manifest.MANIFEST_FILE, declared)

    def state(self):
        return self.fake.state(self.directory)

    def calls(self):
        return self.fake.calls(self.directory)

    def installed(self):
        return {p["id"]: p["enabled"] for p in self.state()["plugins"]}


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
