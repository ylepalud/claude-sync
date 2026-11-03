import json

import pytest

from claude_sync import manifest, paths
from claude_sync.cli import main

ORG = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def profile(fake_claude):
    """A `perso` profile whose manifest and installation agree, with a pinned commit."""
    repo, commit = fake_claude.make_upstream("tools", {"lint": "1.0.0"})
    directory = paths.profile_dir("perso")
    fake_claude.seed(
        directory,
        {
            "marketplaces": [
                {
                    "name": "tools",
                    "source": "github",
                    "repo": "acme/tools",
                    "installLocation": str(repo),
                }
            ],
            "plugins": [{"id": "lint@tools", "version": "1.0.0", "scope": "user", "enabled": True}],
        },
    )
    declared = manifest.Manifest(
        (manifest.Marketplace("tools", "github:acme/tools", None, commit),),
        (manifest.Plugin("lint@tools", "1.0.0", True),),
        None,
    )
    manifest.save(directory / manifest.MANIFEST_FILE, declared)
    return directory, declared


def test_a_profile_that_matches_exits_zero(capsys, profile):
    code, out, _ = run(capsys, "status", "--profile", "perso")
    assert code == 0
    assert out.strip() == "profile perso: no drift"


def test_json_for_a_matching_profile(capsys, profile):
    code, out, _ = run(capsys, "status", "--profile", "perso", "--json")
    assert code == 0
    assert json.loads(out) == {"profile": "perso", "drift": False, "differences": []}


def test_a_missing_plugin_is_drift(capsys, profile, fake_claude):
    directory, _ = profile
    state = fake_claude.state(directory)
    state["plugins"] = []
    fake_claude.seed(directory, state)
    code, out, _ = run(capsys, "status", "--profile", "perso", "--json")
    assert code == 4
    data = json.loads(out)
    assert data["drift"] is True
    assert data["differences"] == [
        {
            "kind": "missing",
            "subject": "lint@tools",
            "expected": "1.0.0",
            "actual": None,
            "drift": True,
        }
    ]


def test_text_lists_drift_before_information(capsys, profile, fake_claude):
    directory, declared = profile
    unpinned = manifest.Manifest(
        (manifest.Marketplace("tools", "github:acme/tools", None, None),),
        (manifest.Plugin("lint@tools", "9.9.9", True),),
        None,
    )
    manifest.save(directory / manifest.MANIFEST_FILE, unpinned)
    code, out, _ = run(capsys, "status", "--profile", "perso")
    assert code == 4
    lines = out.splitlines()
    drift_at = next(i for i, line in enumerate(lines) if "version" in line and "lint@tools" in line)
    info_at = next(i for i, line in enumerate(lines) if "unpinned" in line)
    assert drift_at < info_at
    assert "9.9.9" in lines[drift_at] and "1.0.0" in lines[drift_at]


def test_information_alone_is_not_drift(capsys, profile):
    directory, _ = profile
    unpinned = manifest.Manifest(
        (manifest.Marketplace("tools", "github:acme/tools", None, None),),
        (manifest.Plugin("lint@tools", "1.0.0", True),),
        None,
    )
    manifest.save(directory / manifest.MANIFEST_FILE, unpinned)
    code, out, _ = run(capsys, "status", "--profile", "perso", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["drift"] is False
    assert [d["kind"] for d in data["differences"]] == ["unpinned"]
    assert data["differences"][0]["drift"] is False


def test_a_wrong_signed_in_organization_is_drift(capsys, profile):
    directory, declared = profile
    manifest.save(
        directory / manifest.MANIFEST_FILE,
        manifest.Manifest(declared.marketplaces, declared.plugins, manifest.Account(ORG)),
    )
    (directory / "settings.json").write_text(
        json.dumps({"forceLoginMethod": "claudeai", "forceLoginOrgUUID": [ORG]})
    )
    (directory / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"organizationUuid": OTHER}})
    )
    code, out, _ = run(capsys, "status", "--profile", "perso", "--json")
    assert code == 4
    assert [(d["kind"], d["expected"], d["actual"]) for d in json.loads(out)["differences"]] == [
        ("org", ORG, OTHER)
    ]


def test_a_missing_profile_exits_one_with_the_hint(capsys, fake_claude):
    code, _, err = run(capsys, "status", "--profile", "work")
    assert code == 1
    assert "claude-sync profile create work" in err


def test_an_invalid_manifest_exits_one_naming_the_file(capsys, profile):
    directory, _ = profile
    (directory / manifest.MANIFEST_FILE).write_text('[[plugin]]\nid = "x@market"\n')
    code, _, err = run(capsys, "status", "--profile", "perso")
    assert code == 1
    assert "profile.toml" in err


def test_the_profile_comes_from_the_current_directory(capsys, profile, monkeypatch):
    monkeypatch.setenv("CLAUDE_SYNC_OVERRIDE", "perso")
    code, out, _ = run(capsys, "status", "--json")
    assert code == 0
    assert json.loads(out)["profile"] == "perso"


def test_a_drift_line_is_never_also_information(capsys, profile):
    directory, _ = profile
    unpinned = manifest.Manifest(
        (manifest.Marketplace("tools", "github:acme/tools", None, None),),
        (manifest.Plugin("lint@tools", "9.9.9", True),),
        None,
    )
    manifest.save(directory / manifest.MANIFEST_FILE, unpinned)
    _, out, _ = run(capsys, "status", "--profile", "perso")
    info = [line for line in out.splitlines() if line.startswith("  info:")]
    assert len(info) == 1 and "unpinned tools" in info[0]


def declare_skills(directory, declared, upstream, commit=None):
    source = manifest.SkillSource("tools", upstream.source, None, commit)
    skills = tuple(manifest.Skill(f"{s}@tools", f"skills/{s}", None) for s in ("alpha", "beta"))
    manifest.save(
        directory / manifest.MANIFEST_FILE,
        manifest.Manifest(declared.marketplaces, declared.plugins, None, (source,), skills),
    )


def test_missing_skills_are_drift_and_an_unpinned_source_is_information(
    capsys, profile, skills_upstream
):
    directory, declared = profile
    declare_skills(directory, declared, skills_upstream)
    code, out, _ = run(capsys, "status", "--profile", "perso")
    assert code == 4
    assert "  drift: clone-missing tools:" in out
    assert "  drift: skill-missing alpha@tools:" in out
    assert run(capsys, "apply", "--profile", "perso")[0] == 0
    code, out, _ = run(capsys, "status", "--profile", "perso")
    assert code == 0
    assert out.splitlines()[0] == "profile perso: no drift"
    assert f"  info: skill-unpinned tools: expected None, found {skills_upstream.second!r}" in out


def test_skill_differences_are_in_the_json(capsys, profile, skills_upstream):
    directory, declared = profile
    declare_skills(directory, declared, skills_upstream, skills_upstream.first)
    code, out, _ = run(capsys, "status", "--profile", "perso", "--json")
    assert code == 4
    kinds = {(d["kind"], d["drift"]) for d in json.loads(out)["differences"]}
    assert {("clone-missing", True), ("skill-missing", True)} <= kinds
