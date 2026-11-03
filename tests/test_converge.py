import pytest

from claude_sync import manifest, paths
from claude_sync.context import Context
from claude_sync.converge import build_manifest, converge
from claude_sync.errors import ConfirmationRequired

ORG = "00000000-0000-0000-0000-000000000001"


def context(*, dry_run=False, yes=True, tty=False):
    return Context(json=False, dry_run=dry_run, yes=yes, stdin_is_tty=tty)


@pytest.fixture
def declare(fake_claude):
    """Seed a `perso` profile and return a function (re)writing its manifest."""
    directory = paths.profile_dir("perso")
    repo, commit = fake_claude.make_upstream("tools", {"lint": "1.0.0"})
    fake_claude.seed(directory, {"upstream": {"acme/tools": str(repo)}})

    def write(account=None, ref=None):
        market = manifest.Marketplace("tools", "github:acme/tools", ref, commit)
        plugin = manifest.Plugin("lint@tools", "1.0.0", True)
        manifest.save(
            directory / manifest.MANIFEST_FILE, manifest.Manifest((market,), (plugin,), account)
        )

    write()
    return write


@pytest.fixture
def profile(declare):
    return paths.profile_dir("perso")


def plugins(fake_claude, directory):
    return [p["id"] for p in fake_claude.state(directory).get("plugins", [])]


def test_converge_installs_what_the_manifest_declares(fake_claude, profile):
    assert converge(profile, context()) == 0
    assert plugins(fake_claude, profile) == ["lint@tools"]


def test_converge_dry_run_prints_the_commands_and_runs_none(fake_claude, profile, capsys):
    before = len(fake_claude.calls(profile))
    assert converge(profile, context(dry_run=True)) == 0
    assert "would run: claude plugin install lint@tools" in capsys.readouterr().out
    assert len(fake_claude.calls(profile)) == before + 2
    assert plugins(fake_claude, profile) == []


def test_converge_writes_the_guide_keys_and_reports_it_in_dry_run(profile, declare, capsys):
    declare(account=manifest.Account(org_uuid=ORG))
    converge(profile, context(dry_run=True))
    assert "would write forceLoginMethod and forceLoginOrgUUID" in capsys.readouterr().out
    converge(profile, context())
    assert ORG in (profile / "settings.json").read_text()


def test_converge_needs_a_confirmation_for_a_marketplace_removal(fake_claude, profile, declare):
    converge(profile, context())
    declare(ref="other")
    state = fake_claude.state(profile)
    state["marketplaces"][0]["ref"] = "main"
    fake_claude.seed(profile, state)
    with pytest.raises(ConfirmationRequired):
        converge(profile, context(yes=False))


def test_converge_prune_removes_unlisted_plugins(fake_claude, profile):
    converge(profile, context())
    state = fake_claude.state(profile)
    state["plugins"].append({"id": "x@tools", "version": "1", "scope": "user", "enabled": True})
    fake_claude.seed(profile, state)
    converge(profile, context())
    assert "x@tools" in plugins(fake_claude, profile)
    converge(profile, context(), prune=True)
    assert "x@tools" not in plugins(fake_claude, profile)


def test_converge_exits_four_when_the_upstream_moved(fake_claude, profile, capsys):
    converge(profile, context())
    declared = manifest.load(profile / manifest.MANIFEST_FILE)
    plugin = manifest.Plugin("lint@tools", "0.9.0", True)
    manifest.save(
        profile / manifest.MANIFEST_FILE,
        manifest.Manifest(declared.marketplaces, (plugin,), declared.account),
    )
    assert converge(profile, context()) == 4
    assert "accept with: claude-sync import" in capsys.readouterr().out


def test_build_manifest_lists_managed_marketplaces_and_their_plugins(fake_claude, tmp_path):
    repo, commit = fake_claude.make_upstream("tools", {"lint": "1.0.0"})
    source = tmp_path / "source"
    fake_claude.seed(
        source,
        {
            "marketplaces": [
                {
                    "name": "tools",
                    "source": "github",
                    "repo": "acme/tools",
                    "ref": "main",
                    "installLocation": str(repo),
                },
                {"name": "odd", "source": "file", "path": "/x", "installLocation": "/x"},
            ],
            "plugins": [
                {"id": "lint@tools", "version": "1.0.0", "scope": "user", "enabled": False},
                {"id": "y@odd", "version": "1", "scope": "user", "enabled": True},
            ],
        },
    )
    account = manifest.Account(org_uuid=ORG)
    built = build_manifest(source, account)
    assert built.marketplaces == (
        manifest.Marketplace("tools", "github:acme/tools", "main", commit),
    )
    assert built.plugins == (manifest.Plugin("lint@tools", "1.0.0", False),)
    assert built.account == account


def test_build_manifest_warns_about_a_skipped_marketplace(fake_claude, tmp_path, capsys):
    source = tmp_path / "source"
    fake_claude.seed(
        source,
        {
            "marketplaces": [
                {"name": "odd", "source": "file", "path": "/x", "installLocation": "/x"}
            ]
        },
    )
    assert build_manifest(source, None).marketplaces == ()
    assert "skipped marketplace 'odd'" in capsys.readouterr().err
