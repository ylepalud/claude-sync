import pytest

from claude_sync.claude_cli import InstalledMarketplace, InstalledPlugin
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Account, Manifest, Marketplace, Plugin
from claude_sync.sync import (
    Action,
    Difference,
    Observed,
    ObservedMarketplace,
    diff,
    observe,
    plan,
)

ORG = "00000000-0000-0000-0000-000000000001"
OTHER_ORG = "00000000-0000-0000-0000-000000000002"
C1 = "1" * 40
C2 = "2" * 40


def manifest(marketplaces=(), plugins=(), account=None) -> Manifest:
    return Manifest(tuple(marketplaces), tuple(plugins), account)


def observed(marketplaces=(), plugins=(), guide=None, signed_in=None) -> Observed:
    return Observed(tuple(marketplaces), tuple(plugins), guide, signed_in)


GH = Marketplace("m", "github:o/m", "main", C1)
GH_SEEN = ObservedMarketplace("m", "github", "github:o/m", "main", C1)


def kinds(differences):
    return [(d.kind, d.subject) for d in differences]


def test_identical_profile_has_no_difference():
    declared = manifest([GH], [Plugin("p@m", "1.0", True)], Account(ORG))
    seen = observed([GH_SEEN], [InstalledPlugin("p@m", "1.0", True)], ORG, ORG)
    assert diff(declared, seen) == []


def test_missing_and_unlisted():
    declared = manifest([GH], [Plugin("p@m", "1.0", True)])
    seen = observed(
        [ObservedMarketplace("x", "github", "github:o/x", None, C2)],
        [InstalledPlugin("q@x", "2.0", True)],
    )
    assert diff(declared, seen) == [
        Difference("missing", "m", "github:o/m", None),
        Difference("unlisted", "x", None, "github:o/x"),
        Difference("missing", "p@m", "1.0", None),
        Difference("unlisted", "q@x", None, "2.0"),
    ]


def test_source_ref_and_commit_differences():
    seen = observed([ObservedMarketplace("m", "github", "github:o/fork", "dev", C2)])
    assert diff(manifest([GH]), seen) == [
        Difference("source", "m", "github:o/m", "github:o/fork"),
        Difference("ref", "m", "main", "dev"),
        Difference("commit", "m", C1, C2),
    ]


def test_path_sources_compare_as_normalized_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    declared = manifest([Marketplace("d", "path:~/market", None, None)])
    seen = observed([ObservedMarketplace("d", "directory", f"path:{tmp_path}/market", None, None)])
    assert diff(declared, seen) == []


def test_version_and_enabled_differences():
    declared = manifest([GH], [Plugin("p@m", "1.0", True)])
    seen = observed([GH_SEEN], [InstalledPlugin("p@m", "1.1", False)])
    assert diff(declared, seen) == [
        Difference("version", "p@m", "1.0", "1.1"),
        Difference("enabled", "p@m", True, False),
    ]


@pytest.mark.parametrize("guide", [None, OTHER_ORG])
def test_guide_absent_or_different(guide):
    seen = observed(guide=guide)
    assert diff(manifest(account=Account(ORG)), seen) == [
        Difference("guide", "account", ORG, guide)
    ]


def test_org_mismatch_only_when_signed_in():
    declared = manifest(account=Account(ORG))
    assert diff(declared, observed(guide=ORG, signed_in=None)) == []
    assert diff(declared, observed(guide=ORG, signed_in=OTHER_ORG)) == [
        Difference("org", "account", ORG, OTHER_ORG)
    ]


def test_no_account_checks_without_org_uuid():
    assert diff(manifest(), observed(guide=None, signed_in=OTHER_ORG)) == []


def test_unpinned_marketplace_is_information():
    declared = manifest([Marketplace("m", "github:o/m", None, None)])
    seen = observed([ObservedMarketplace("m", "github", "github:o/m", None, C2)])
    [difference] = diff(declared, seen)
    assert difference == Difference("unpinned", "m", None, C2)
    assert difference.drift is False


def test_path_marketplace_is_never_unpinned():
    declared = manifest([Marketplace("d", "path:/src/d", None, None)])
    seen = observed([ObservedMarketplace("d", "directory", "path:/src/d", None, None)])
    assert diff(declared, seen) == []


def test_unmanaged_marketplace_and_its_plugins_are_information():
    seen = observed(
        [ObservedMarketplace("hosted", "claudeai", None, None, None)],
        [InstalledPlugin("p@hosted", "1", True)],
    )
    [difference] = diff(manifest(), seen)
    assert difference == Difference("unmanaged", "hosted", None, "claudeai")
    assert difference.drift is False


def test_declared_marketplace_seen_unmanaged_is_a_source_difference():
    seen = observed([ObservedMarketplace("m", "file", None, None, None)])
    assert kinds(diff(manifest([GH]), seen)) == [("source", "m"), ("unmanaged", "m")]


def test_every_other_kind_is_drift():
    for kind in ("missing", "unlisted", "source", "ref", "commit", "version", "enabled"):
        assert Difference(kind, "x", None, None).drift is True
    for kind in ("guide", "org"):
        assert Difference(kind, "account", None, None).drift is True


class StubCli:
    """An in-memory stand-in for ClaudeCli's read methods."""

    def __init__(self, marketplaces, plugins, commits):
        self._marketplaces, self._plugins, self._commits = marketplaces, plugins, commits
        self.commit_asked = []

    def marketplaces(self):
        return self._marketplaces

    def plugins(self):
        return self._plugins

    def marketplace_commit(self, location):
        self.commit_asked.append(location)
        return self._commits.get(location)


def test_observe_maps_sources_commits_and_account(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "settings.json").write_text(
        f'{{"forceLoginMethod": "claudeai", "forceLoginOrgUUID": ["{ORG}"]}}'
    )
    (profile / ".claude.json").write_text(
        f'{{"oauthAccount": {{"organizationUuid": "{OTHER_ORG}"}}}}'
    )
    cli = StubCli(
        [
            InstalledMarketplace("gh", "github", "o/gh", "main", "/m/gh"),
            InstalledMarketplace("g", "git", "https://e.invalid/g.git", None, "/m/g"),
            InstalledMarketplace("u", "url", "https://e.invalid/m.json", None, "/m/u"),
            InstalledMarketplace("d", "directory", "/src/d", None, "/src/d"),
            InstalledMarketplace("f", "file", "/src/m.json", None, "/m/f"),
            InstalledMarketplace("h", "claudeai", None, None, "/m/h"),
        ],
        [InstalledPlugin("p@gh", "1.0", True)],
        {"/m/gh": C1, "/m/g": C2, "/src/d": C1},
    )
    assert observe(cli, profile) == Observed(
        (
            ObservedMarketplace("gh", "github", "github:o/gh", "main", C1),
            ObservedMarketplace("g", "git", "git:https://e.invalid/g.git", None, C2),
            ObservedMarketplace("u", "url", "url:https://e.invalid/m.json", None, None),
            ObservedMarketplace("d", "directory", "path:/src/d", None, None),
            ObservedMarketplace("f", "file", None, None, None),
            ObservedMarketplace("h", "claudeai", None, None, None),
        ),
        (InstalledPlugin("p@gh", "1.0", True),),
        ORG,
        OTHER_ORG,
    )
    assert cli.commit_asked == ["/m/gh", "/m/g", "/m/u"]


def test_observe_without_account_files(tmp_path):
    seen = observe(StubCli([], [], {}), tmp_path)
    assert (seen.guide, seen.signed_in_org) == (None, None)


def add(spec, confirm=False):
    return Action(("plugin", "marketplace", "add", spec), confirm)


def remove(name, confirm=True):
    return Action(("plugin", "marketplace", "remove", name), confirm)


def plugin_cmd(verb, plugin_id, confirm=False):
    return Action(("plugin", verb, plugin_id, "--scope", "user"), confirm)


def test_plan_for_an_identical_profile_is_empty():
    declared = manifest([GH], [Plugin("p@m", "1.0", True)], Account(ORG))
    seen = observed([GH_SEEN], [InstalledPlugin("p@m", "1.0", True)], ORG, ORG)
    assert plan(declared, seen, prune=True) == []


def test_plan_adds_marketplaces_before_installing_plugins(tmp_path):
    declared = manifest(
        [GH, Marketplace("d", f"path:{tmp_path}/d", None, None)],
        [Plugin("p@m", "1.0", True), Plugin("q@d", "2.0", False)],
    )
    assert plan(declared, observed(), prune=False) == [
        add("o/m#main"),
        add(f"{tmp_path}/d"),
        plugin_cmd("install", "p@m"),
        plugin_cmd("install", "q@d"),
        plugin_cmd("disable", "q@d"),
    ]


def test_plan_enables_and_disables_to_match():
    declared = manifest([GH], [Plugin("p@m", "1", True), Plugin("q@m", "1", False)])
    seen = observed(
        [GH_SEEN], [InstalledPlugin("p@m", "1", False), InstalledPlugin("q@m", "1", True)]
    )
    assert plan(declared, seen, prune=False) == [
        plugin_cmd("enable", "p@m"),
        plugin_cmd("disable", "q@m"),
    ]


def test_version_and_commit_drift_plan_nothing():
    declared = manifest([GH], [Plugin("p@m", "1.0", True)])
    seen = observed(
        [ObservedMarketplace("m", "github", "github:o/m", "main", C2)],
        [InstalledPlugin("p@m", "1.1", True)],
    )
    assert plan(declared, seen, prune=False) == []


@pytest.mark.parametrize(
    "seen_market",
    [
        ObservedMarketplace("m", "github", "github:o/m", "dev", C1),
        ObservedMarketplace("m", "github", "github:o/fork", "main", C1),
    ],
)
def test_re_pin_removes_adds_and_reinstalls_with_confirmation(seen_market):
    declared = manifest(
        [GH, Marketplace("other", "github:o/other", None, None)],
        [Plugin("p@m", "1", True), Plugin("q@m", "1", False), Plugin("r@other", "1", True)],
    )
    seen = observed(
        [seen_market, ObservedMarketplace("other", "github", "github:o/other", None, C2)],
        [
            InstalledPlugin("p@m", "1", True),
            InstalledPlugin("q@m", "1", False),
            InstalledPlugin("r@other", "1", True),
        ],
    )
    assert plan(declared, seen, prune=False) == [
        remove("m"),
        add("o/m#main", confirm=True),
        plugin_cmd("install", "p@m", confirm=True),
        plugin_cmd("install", "q@m", confirm=True),
        plugin_cmd("disable", "q@m", confirm=True),
    ]


def test_unlisted_items_are_pruned_only_with_prune():
    declared = manifest([GH], [Plugin("p@m", "1", True)])
    seen = observed(
        [GH_SEEN, ObservedMarketplace("x", "github", "github:o/x", None, C2)],
        [
            InstalledPlugin("p@m", "1", True),
            InstalledPlugin("extra@m", "1", True),
            InstalledPlugin("y@x", "1", True),
        ],
    )
    assert plan(declared, seen, prune=False) == []
    assert plan(declared, seen, prune=True) == [
        plugin_cmd("uninstall", "extra@m", confirm=True),
        remove("x"),
    ]


def test_unmanaged_marketplaces_are_never_planned():
    declared = manifest([GH], [Plugin("p@m", "1", True)])
    seen = observed(
        [GH_SEEN, ObservedMarketplace("hosted", "claudeai", None, None, None)],
        [InstalledPlugin("p@m", "1", True), InstalledPlugin("h@hosted", "1", False)],
    )
    assert plan(declared, seen, prune=True) == []


def test_prune_leaves_plugins_of_a_re_pinned_marketplace_to_its_removal():
    declared = manifest([GH], [Plugin("p@m", "1", True)])
    seen = observed(
        [ObservedMarketplace("m", "github", "github:o/m", "dev", C1)],
        [InstalledPlugin("p@m", "1", True), InstalledPlugin("extra@m", "1", True)],
    )
    assert plan(declared, seen, prune=True) == [
        remove("m"),
        add("o/m#main", confirm=True),
        plugin_cmd("install", "p@m", confirm=True),
    ]


def test_re_pin_disables_a_plugin_declared_disabled_exactly_once():
    declared = manifest([GH], [Plugin("q@m", "1", False)])
    seen = observed(
        [ObservedMarketplace("m", "github", "github:o/m", "dev", C1)],
        [InstalledPlugin("q@m", "1", True)],
    )
    assert plan(declared, seen, prune=False) == [
        remove("m"),
        add("o/m#main", confirm=True),
        plugin_cmd("install", "q@m", confirm=True),
        plugin_cmd("disable", "q@m", confirm=True),
    ]


@pytest.mark.parametrize("kind", ["file", "claudeai"])
def test_plan_refuses_a_declared_marketplace_held_by_an_unmanaged_one(kind):
    seen = observed([ObservedMarketplace("m", kind, None, None, None)])
    with pytest.raises(ClaudeSyncError) as caught:
        plan(manifest([GH]), seen, prune=False)
    assert "'m'" in str(caught.value)
    assert "managed outside claude-sync" in str(caught.value)
    assert kind in str(caught.value)
