import os
from pathlib import Path

import pytest

from claude_sync import gitops, manifest, paths, skills
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, Skill, SkillSource
from claude_sync.sync import Difference


def declare(upstream, commit=None, ref=None, trees=None, name="tools") -> Manifest:
    """A manifest with the source `name` serving `alpha` and `beta` from `upstream`."""
    trees = trees or {}
    return Manifest(
        (),
        (),
        None,
        (SkillSource(name, upstream.source, ref, commit),),
        tuple(
            Skill(f"{skill}@{name}", f"skills/{skill}", trees.get(skill))
            for skill in ("alpha", "beta")
        ),
    )


@pytest.fixture
def profile() -> Path:
    directory = paths.profile_dir("perso")
    directory.mkdir(parents=True)
    return directory


def kinds(differences) -> set[tuple[str, str]]:
    return {(d.kind, d.subject) for d in differences}


def test_sources_dir_is_next_to_the_configuration_file():
    assert skills.sources_dir() == paths.config_home() / "sources"


def test_nothing_installed_reports_missing_clone_and_links(profile, skills_upstream):
    declared = declare(skills_upstream, commit=skills_upstream.first)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert kinds(found) == {
        ("clone-missing", "tools"),
        ("skill-missing", "alpha@tools"),
        ("skill-missing", "beta@tools"),
    }
    assert all(d.drift for d in found)


def install(profile: Path, upstream, commit: str, name: str = "tools") -> Path:
    """Clone `upstream` into `sources/<name>/` at `commit` and link both skills."""
    clone = skills.sources_dir() / name
    gitops.clone(str(upstream.path), clone, None)
    gitops.checkout(clone, commit)
    (profile / "skills").mkdir(exist_ok=True)
    for skill in ("alpha", "beta"):
        (profile / "skills" / skill).symlink_to(clone / "skills" / skill)
    return clone


def test_converged_profile_has_no_difference(profile, skills_upstream):
    declared = declare(skills_upstream, commit=skills_upstream.first)
    install(profile, skills_upstream, skills_upstream.first)
    assert skills.diff(declared, skills.observe(profile, declared)) == []


def test_source_without_commit_is_information(profile, skills_upstream):
    declared = declare(skills_upstream)
    install(profile, skills_upstream, skills_upstream.second)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert found == [Difference("skill-unpinned", "tools", None, skills_upstream.second)]
    assert not found[0].drift


def test_clone_at_another_commit(profile, skills_upstream):
    declared = declare(skills_upstream, commit=skills_upstream.first)
    install(profile, skills_upstream, skills_upstream.second)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert Difference("clone-commit", "tools", skills_upstream.first, skills_upstream.second) in (
        found
    )


def test_clone_with_local_changes(profile, skills_upstream):
    declared = declare(skills_upstream, commit=skills_upstream.first)
    clone = install(profile, skills_upstream, skills_upstream.first)
    (clone / "skills" / "alpha" / "SKILL.md").write_text("edited\n")
    found = skills.diff(declared, skills.observe(profile, declared))
    assert Difference("clone-dirty", "tools", False, True) in found


def test_clone_off_the_declared_ref(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.first)
    declared = declare(upstream, ref="dev")
    assert "skill-ref" not in {
        d.kind for d in skills.diff(declared, skills.observe(profile, declared))
    }
    gitops.checkout(clone, upstream.second)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert Difference("skill-ref", "tools", "dev", upstream.second) in found


def test_clone_on_an_unknown_ref(profile, skills_upstream):
    install(profile, skills_upstream, skills_upstream.first)
    declared = declare(skills_upstream, ref="gone")
    found = skills.diff(declared, skills.observe(profile, declared))
    assert Difference("skill-ref", "tools", "gone", skills_upstream.first) in found


def test_skill_with_another_tree_than_recorded(profile, skills_upstream):
    upstream = skills_upstream
    trees = {s: upstream.tree(upstream.first, s) for s in ("alpha", "beta")}
    declared = declare(upstream, commit=upstream.second, trees=trees)
    install(profile, upstream, upstream.second)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert found == [
        Difference(
            "skill-tree", "alpha@tools", trees["alpha"], upstream.tree(upstream.second, "alpha")
        )
    ]


def test_link_pointing_elsewhere(profile, skills_upstream, isolated_environment):
    declared = declare(skills_upstream, commit=skills_upstream.first)
    install(profile, skills_upstream, skills_upstream.first)
    copy = isolated_environment / ".agents" / "skills" / "alpha"
    copy.mkdir(parents=True)
    (profile / "skills" / "alpha").unlink()
    (profile / "skills" / "alpha").symlink_to(copy)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert len(found) == 1
    assert (found[0].kind, found[0].subject) == ("skill-elsewhere", "alpha@tools")
    assert found[0].expected == str(skills.sources_dir() / "tools" / "skills" / "alpha")
    assert Path(found[0].actual).samefile(copy)


def test_real_directory_is_a_conflict(profile, skills_upstream):
    declared = declare(skills_upstream, commit=skills_upstream.first)
    install(profile, skills_upstream, skills_upstream.first)
    (profile / "skills" / "alpha").unlink()
    (profile / "skills" / "alpha").mkdir()
    found = skills.diff(declared, skills.observe(profile, declared))
    assert found == [
        Difference(
            "skill-conflict",
            "alpha@tools",
            str(skills.sources_dir() / "tools" / "skills" / "alpha"),
            str(profile / "skills" / "alpha"),
        )
    ]


def test_only_undeclared_links_into_sources_are_unlisted(profile, skills_upstream, tmp_path):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.first)
    declared = declare(upstream, commit=upstream.first)
    declared = Manifest((), (), None, declared.skill_sources, declared.skills[:1])  # alpha only
    own = tmp_path / "own-skill"
    own.mkdir()
    (profile / "skills" / "own").symlink_to(own)
    (profile / "skills" / "foreign").symlink_to(tmp_path / "nowhere")
    (profile / "skills" / "mine").mkdir()
    found = skills.diff(declared, skills.observe(profile, declared))
    assert len(found) == 1
    assert (found[0].kind, found[0].subject, found[0].expected) == ("skill-unlisted", "beta", None)
    assert Path(found[0].actual).samefile(clone / "skills" / "beta")


def test_recorded_tree_without_clone_is_only_a_missing_clone(profile, skills_upstream):
    upstream = skills_upstream
    declared = declare(upstream, commit=upstream.first, trees={"alpha": "a" * 40})
    found = skills.diff(declared, skills.observe(profile, declared))
    assert "skill-tree" not in {d.kind for d in found}


def converge(profile: Path, declared: Manifest, prune: bool = False) -> list[skills.SkillAction]:
    actions = skills.plan(declared, skills.observe(profile, declared), prune)
    for action in actions:
        action.run()
    return actions


def descriptions(profile: Path, declared: Manifest, prune: bool = False) -> list[str]:
    return [a.description for a in skills.plan(declared, skills.observe(profile, declared), prune)]


def test_plan_converges_a_new_profile(profile, skills_upstream):
    upstream = skills_upstream
    declared = declare(upstream, commit=upstream.first)
    clone = skills.sources_dir() / "tools"
    alpha = clone / "skills" / "alpha"
    sources = "~/.config/claude-sync/sources/tools"
    links = "~/.config/claude-sync/profiles/perso/skills"
    assert descriptions(profile, declared) == [
        f"run: git clone {upstream.path} {sources}",
        f"run: git -C {sources} checkout --detach {upstream.first}",
        f"link {links}/alpha -> {sources}/skills/alpha",
        f"link {links}/beta -> {sources}/skills/beta",
    ]
    actions = converge(profile, declared)
    assert not any(a.confirm for a in actions)
    assert gitops.head(clone) == upstream.first
    assert Path(os.readlink(profile / "skills" / "alpha")) == alpha
    assert skills.diff(declared, skills.observe(profile, declared)) == []


def test_plan_clones_at_the_ref_and_stays_on_its_head(profile, skills_upstream):
    upstream = skills_upstream
    declared = declare(upstream, ref="dev")
    assert descriptions(profile, declared)[0] == (
        f"run: git clone --branch dev {upstream.path} ~/.config/claude-sync/sources/tools"
    )
    converge(profile, declared)
    assert gitops.head(skills.sources_dir() / "tools") == upstream.first


def test_plan_checks_out_the_recorded_commit_of_an_existing_clone(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    declared = declare(upstream, commit=upstream.first)
    assert descriptions(profile, declared) == [
        f"run: git -C ~/.config/claude-sync/sources/tools checkout --detach {upstream.first}"
    ]
    converge(profile, declared)
    assert gitops.head(clone) == upstream.first


def test_plan_fetches_a_commit_the_clone_lacks(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    newer = upstream.commit()
    declared = declare(upstream, commit=newer)
    assert descriptions(profile, declared) == [
        "run: git -C ~/.config/claude-sync/sources/tools fetch --tags origin",
        f"run: git -C ~/.config/claude-sync/sources/tools checkout --detach {newer}",
    ]
    converge(profile, declared)
    assert gitops.head(clone) == newer


def test_plan_refuses_to_check_out_a_dirty_clone(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    (clone / "skills" / "alpha" / "SKILL.md").write_text("edited\n")
    declared = declare(upstream, commit=upstream.first)
    with pytest.raises(ClaudeSyncError, match="~/.config/claude-sync/sources/tools"):
        skills.plan(declared, skills.observe(profile, declared), False)
    assert gitops.head(clone) == upstream.second


def test_dirty_clone_at_its_commit_plans_nothing(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.first)
    (clone / "skills" / "alpha" / "SKILL.md").write_text("edited\n")
    assert descriptions(profile, declare(upstream, commit=upstream.first)) == []


def test_plan_replaces_a_link_pointing_elsewhere_after_confirmation(
    profile, skills_upstream, isolated_environment
):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.first)
    copy = isolated_environment / ".agents" / "skills" / "alpha"
    copy.mkdir(parents=True)
    (profile / "skills" / "alpha").unlink()
    (profile / "skills" / "alpha").symlink_to(copy)
    declared = declare(upstream, commit=upstream.first)
    actions = converge(profile, declared)
    assert [(a.description, a.confirm) for a in actions] == [
        (
            "replace ~/.config/claude-sync/profiles/perso/skills/alpha"
            " -> ~/.config/claude-sync/sources/tools/skills/alpha",
            True,
        )
    ]
    assert Path(os.readlink(profile / "skills" / "alpha")) == clone / "skills" / "alpha"
    assert copy.is_dir()


def test_plan_stops_on_a_real_directory_before_any_change(profile, skills_upstream):
    upstream = skills_upstream
    (profile / "skills" / "alpha").mkdir(parents=True)
    (profile / "skills" / "alpha" / "SKILL.md").write_text("mine\n")
    declared = declare(upstream, commit=upstream.first)
    with pytest.raises(ClaudeSyncError, match="skills/alpha"):
        skills.plan(declared, skills.observe(profile, declared), False)
    assert (profile / "skills" / "alpha" / "SKILL.md").read_text() == "mine\n"


def test_prune_removes_only_undeclared_links_into_sources(profile, skills_upstream, tmp_path):
    upstream = skills_upstream
    install(profile, upstream, upstream.first)
    full = declare(upstream, commit=upstream.first)
    declared = Manifest((), (), None, full.skill_sources, full.skills[:1])  # alpha only
    (tmp_path / "own").mkdir()
    (profile / "skills" / "own").symlink_to(tmp_path / "own")
    (profile / "skills" / "mine").mkdir()
    assert descriptions(profile, declared) == []
    actions = converge(profile, declared, prune=True)
    assert [(a.description, a.confirm) for a in actions] == [
        (
            "remove ~/.config/claude-sync/profiles/perso/skills/beta"
            " -> ~/.config/claude-sync/sources/tools/skills/beta",
            True,
        )
    ]
    assert sorted(p.name for p in (profile / "skills").iterdir()) == ["alpha", "mine", "own"]


def first_trees(upstream) -> dict[str, str]:
    return {s: upstream.tree(upstream.first, s) for s in ("alpha", "beta")}


def test_pin_from_trees_picks_the_newest_commit_where_every_skill_matches(skills_upstream):
    upstream = skills_upstream
    upstream.commit()  # beta changes: only `first` still has both recorded trees
    clone = skills.sources_dir() / "tools"
    gitops.clone(str(upstream.path), clone, None)
    recorded = declare(upstream, trees=first_trees(upstream)).skills
    assert skills.pin_from_trees(clone, None, recorded) == (upstream.first, [])
    beta_only = declare(upstream, trees={"beta": upstream.tree(upstream.first, "beta")}).skills
    assert skills.pin_from_trees(clone, None, beta_only) == (upstream.second, [])


def test_pin_from_trees_falls_back_to_the_commit_matching_most(skills_upstream):
    upstream = skills_upstream
    upstream.commit()  # third commit: alpha as in second, beta changed
    clone = skills.sources_dir() / "tools"
    gitops.clone(str(upstream.path), clone, None)
    # alpha as in `first` (matches `first` only), beta never existed.
    trees = {"alpha": upstream.tree(upstream.first, "alpha"), "beta": "b" * 40}
    recorded = declare(upstream, trees=trees).skills
    assert skills.pin_from_trees(clone, None, recorded) == (upstream.first, ["beta@tools"])
    # Ties go to the newest: alpha as in `second` matches `second` and the third commit.
    trees["alpha"] = upstream.tree(upstream.second, "alpha")
    recorded = declare(upstream, trees=trees).skills
    assert skills.pin_from_trees(clone, None, recorded) == (gitops.head(clone), ["beta@tools"])


def test_pin_to_what_is_installed(profile, skills_upstream):
    upstream = skills_upstream
    declared = declare(upstream, trees=first_trees(upstream))
    sources = "~/.config/claude-sync/sources/tools"
    assert descriptions(profile, declared)[:2] == [
        f"run: git clone {upstream.path} {sources}",
        f"run: git -C {sources} checkout --detach <newest commit matching the recorded trees>",
    ]
    converge(profile, declared)
    assert gitops.head(skills.sources_dir() / "tools") == upstream.first
    found = skills.diff(declared, skills.observe(profile, declared))
    assert [d.kind for d in found] == ["skill-unpinned"]


def test_existing_unpinned_clone_is_pinned_to_the_recorded_trees(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    declared = declare(upstream, trees=first_trees(upstream))
    assert descriptions(profile, declared) == [
        f"run: git -C ~/.config/claude-sync/sources/tools checkout --detach {upstream.first}"
    ]
    converge(profile, declared)
    assert gitops.head(clone) == upstream.first
    assert descriptions(profile, declared) == []


def test_unpinned_source_without_trees_stays_on_the_head(profile, skills_upstream):
    upstream = skills_upstream
    install(profile, upstream, upstream.first)
    assert descriptions(profile, declare(upstream)) == []


def other_profile(name: str, declared: Manifest) -> Path:
    directory = paths.profile_dir(name)
    directory.mkdir(parents=True)
    manifest.save(directory / manifest.MANIFEST_FILE, declared)
    return directory


def test_two_profiles_disagree_on_the_commit(profile, skills_upstream):
    upstream = skills_upstream
    other_profile("work", declare(upstream, commit=upstream.second))
    declared = declare(upstream, commit=upstream.first)
    manifest.save(profile / manifest.MANIFEST_FILE, declared)
    with pytest.raises(ClaudeSyncError) as error:
        skills.plan(declared, skills.observe(profile, declared), False)
    message = str(error.value)
    for word in ("perso", "work", "tools", upstream.first, upstream.second):
        assert word in message
    assert not (skills.sources_dir() / "tools").exists()


def test_two_profiles_disagree_on_the_source(profile, skills_upstream, tmp_path):
    upstream = skills_upstream
    other = Manifest(
        (), (), None, (SkillSource("tools", "github:perso/tools", None, upstream.first),), ()
    )
    other_profile("work", other)
    with pytest.raises(ClaudeSyncError, match="github:perso/tools"):
        skills.other_profiles_conflict("tools", upstream.source, upstream.first, profile)


def test_profiles_agreeing_or_without_a_recorded_commit_do_not_conflict(profile, skills_upstream):
    upstream = skills_upstream
    manifest.save(profile / manifest.MANIFEST_FILE, declare(upstream, commit=upstream.second))
    other_profile("work", declare(upstream, commit=upstream.first))
    other_profile("home", declare(upstream))
    other_profile("lab", declare(upstream, commit=upstream.second, name="other"))
    paths.profile_dir("empty").mkdir()
    skills.other_profiles_conflict("tools", upstream.source, upstream.first, profile)


def test_unpinned_profile_refuses_a_source_another_profile_pins(profile, skills_upstream):
    upstream = skills_upstream
    other_profile("work", declare(upstream, commit=upstream.first))
    declared = declare(upstream)
    with pytest.raises(ClaudeSyncError) as error:
        skills.plan(declared, skills.observe(profile, declared), False)
    message = str(error.value)
    for words in ("perso", "work", upstream.first, "same commit", "another source name"):
        assert words in message


def test_unpinned_profiles_do_not_conflict(profile, skills_upstream):
    other_profile("home", declare(skills_upstream))
    skills.other_profiles_conflict("tools", skills_upstream.source, None, profile)


def test_no_other_profile_no_conflict(tmp_path, skills_upstream):
    skills.other_profiles_conflict("tools", skills_upstream.source, None, tmp_path)


def test_import_links_into_sources_keep_the_source_name_and_commit(profile, skills_upstream):
    upstream = skills_upstream
    install(profile, upstream, upstream.first)
    assert skills.import_skills(profile) == (
        (SkillSource("tools", upstream.source, None, upstream.first),),
        (Skill("alpha@tools", "skills/alpha", None), Skill("beta@tools", "skills/beta", None)),
    )


def test_import_links_into_another_checkout_with_a_remote(profile, skills_upstream, tmp_path):
    upstream = skills_upstream
    checkout = tmp_path / "work-skills"
    gitops.clone(str(upstream.path), checkout, None)
    bare = tmp_path / "bare"
    gitops.clone(str(upstream.path), bare, None)
    gitops.run("remote", "remove", "origin", cwd=bare)
    (profile / "skills").mkdir()
    (profile / "skills" / "alpha").symlink_to(checkout / "skills" / "alpha")
    (profile / "skills" / "beta").symlink_to(bare / "skills" / "beta")
    assert skills.import_skills(profile) == (
        (SkillSource("work-skills", upstream.source, None, upstream.second),),
        (Skill("alpha@work-skills", "skills/alpha", None),),
    )


def test_import_warns_about_a_checkout_without_remote(profile, skills_upstream, tmp_path, capsys):
    bare = tmp_path / "bare"
    gitops.clone(str(skills_upstream.path), bare, None)
    gitops.run("remote", "remove", "origin", cwd=bare)
    (profile / "skills").mkdir()
    (profile / "skills" / "beta").symlink_to(bare / "skills" / "beta")
    assert skills.import_skills(profile) == ((), ())
    assert "warning: skipped ~/.config/claude-sync/profiles/perso/skills/beta" in (
        capsys.readouterr().err
    )


def lock_entry(repo: str, skill_path: str, folder_hash: str, plugin: str | None = None) -> dict:
    entry = {
        "source": repo,
        "sourceType": "github",
        "sourceUrl": f"https://github.com/{repo}.git",
        "skillPath": skill_path,
        "skillFolderHash": folder_hash,
    }
    if plugin is not None:
        entry["pluginName"] = plugin
    return entry


def link_to_agents(profile: Path, *names: str) -> None:
    (profile / "skills").mkdir(exist_ok=True)
    for name in names:
        (profile / "skills" / name).symlink_to(Path.home() / ".agents" / "skills" / name)


def test_import_from_the_lock_file(profile, skill_lock):
    skill_lock(
        {
            "tdd": lock_entry("acme/skills", "skills/engineering/tdd/SKILL.md", "1" * 40),
            "grill": lock_entry("acme/skills", "skills/grill/SKILL.md", "2" * 40, "eng"),
            "unlinked": lock_entry("acme/skills", "skills/x/SKILL.md", "3" * 40, "later"),
            "lint": lock_entry("zeta/tools", "lint/SKILL.md", "4" * 40),
        }
    )
    link_to_agents(profile, "tdd", "grill", "lint")
    assert skills.import_skills(profile) == (
        (
            SkillSource("eng", "github:acme/skills", None, None),
            SkillSource("zeta-tools", "github:zeta/tools", None, None),
        ),
        (
            Skill("grill@eng", "skills/grill", "2" * 40),
            Skill("lint@zeta-tools", "lint", "4" * 40),
            Skill("tdd@eng", "skills/engineering/tdd", "1" * 40),
        ),
    )


def test_import_ignores_a_lock_of_another_version(profile, skill_lock, capsys):
    skill_lock({"tdd": lock_entry("acme/skills", "skills/tdd/SKILL.md", "1" * 40)}, version=4)
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile) == ((), ())
    err = capsys.readouterr().err
    assert "warning: ignored ~/.agents/.skill-lock.json: version 4" in err
    assert "warning: skipped ~/.config/claude-sync/profiles/perso/skills/tdd" in err


def test_import_skips_lock_entries_of_other_types(profile, skill_lock, capsys):
    entry = lock_entry("acme/skills", "skills/tdd/SKILL.md", "1" * 40)
    skill_lock({"tdd": {**entry, "sourceType": "local"}})
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile) == ((), ())
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/tdd" in capsys.readouterr().err


def test_import_leaves_out_real_directories_and_other_links(profile, tmp_path, capsys):
    (profile / "skills" / "mine").mkdir(parents=True)
    (tmp_path / "plain").mkdir()
    (profile / "skills" / "plain").symlink_to(tmp_path / "plain")
    (Path.home() / ".agents" / "skills" / "tdd").mkdir(parents=True)
    link_to_agents(profile, "tdd")  # no lock file
    assert skills.import_skills(profile) == ((), ())
    err = capsys.readouterr().err
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/plain" in err
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/tdd" in err
    assert "mine" not in err


def test_import_ignores_an_unreadable_lock(profile, skill_lock, capsys):
    skill_lock({"tdd": lock_entry("acme/skills", "skills/tdd/SKILL.md", "1" * 40)})
    skills.lock_file().write_text("{not json")
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile) == ((), ())
    assert "ignored ~/.agents/.skill-lock.json: cannot read it" in capsys.readouterr().err


def test_import_leaves_out_links_into_the_profile_repository(profile, skills_upstream, capsys):
    gitops.run("init", "--quiet", cwd=profile)
    gitops.run("remote", "add", "origin", "https://github.com/perso/dotfiles.git", cwd=profile)
    (profile / "rules").mkdir()
    (profile / "skills").mkdir()
    (profile / "skills" / "in").symlink_to("../rules")
    assert skills.import_skills(profile) == ((), ())
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/in" in capsys.readouterr().err


def test_import_skips_a_link_to_the_root_of_a_checkout(profile, skills_upstream, tmp_path, capsys):
    checkout = tmp_path / "whole"
    gitops.clone(str(skills_upstream.path), checkout, None)
    (profile / "skills").mkdir()
    (profile / "skills" / "whole").symlink_to(checkout)
    assert skills.import_skills(profile) == ((), ())
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/whole" in capsys.readouterr().err


def test_import_names_each_checkout_once_and_never_twice(profile, skills_upstream, tmp_path):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.first)
    for link in ("alpha", "beta"):
        (profile / "skills" / link).unlink()
    first, second = tmp_path / "a" / "tools", tmp_path / "b" / "tools"
    for checkout in (first, second):
        gitops.clone(str(upstream.path), checkout, None)
    gitops.run("remote", "set-url", "origin", "https://github.com/perso/other.git", cwd=second)
    for link, target in {
        "aa": first / "skills" / "alpha",
        "ab": first / "skills" / "beta",
        "ba": second / "skills" / "alpha",
        "zz": clone / "skills" / "alpha",
    }.items():
        (profile / "skills" / link).symlink_to(target)
    assert skills.import_skills(profile) == (
        (
            SkillSource("tools", upstream.source, None, upstream.first),
            SkillSource("tools-2", upstream.source, None, upstream.second),
            SkillSource("tools-3", "github:perso/other", None, upstream.second),
        ),
        (
            Skill("zz@tools", "skills/alpha", None),
            Skill("aa@tools-2", "skills/alpha", None),
            Skill("ab@tools-2", "skills/beta", None),
            Skill("ba@tools-3", "skills/alpha", None),
        ),
    )


def test_clone_of_another_source_is_reported_and_never_checked_out(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    gitops.run("remote", "set-url", "origin", "https://github.com/perso/other.git", cwd=clone)
    declared = declare(upstream, commit=upstream.first)
    found = skills.diff(declared, skills.observe(profile, declared))
    assert Difference("source", "tools", upstream.source, "github:perso/other") in found
    assert Difference("source", "tools", upstream.source, "github:perso/other").drift
    with pytest.raises(ClaudeSyncError, match="~/.config/claude-sync/sources/tools"):
        skills.plan(declared, skills.observe(profile, declared), False)
    assert gitops.head(clone) == upstream.second


def test_import_of_a_lock_entry_without_folder_hash_has_no_tree(profile, skill_lock):
    entry = lock_entry("acme/skills", "skills/tdd/SKILL.md", "1" * 40)
    del entry["skillFolderHash"]
    skill_lock({"tdd": entry})
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile)[1] == (Skill("tdd@acme-skills", "skills/tdd", None),)


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"version": 3}',
        '{"version": 3, "skills": []}',
        '{"version": 3, "skills": {"tdd": "acme/skills"}}',
        '{"version": 3, "skills": {"tdd": ["github"]}}',
    ],
)
def test_import_ignores_a_lock_of_another_shape(profile, skill_lock, capsys, content):
    skill_lock({"tdd": lock_entry("acme/skills", "skills/tdd/SKILL.md", "1" * 40)})
    skills.lock_file().write_text(content)
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile) == ((), ())
    assert "warning: ignored ~/.agents/.skill-lock.json" in capsys.readouterr().err


def test_import_skips_a_github_entry_without_its_fields(profile, skill_lock, capsys):
    skill_lock({"tdd": {"sourceType": "github", "source": "acme/skills"}})
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile) == ((), ())
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/tdd" in capsys.readouterr().err


def imported(profile: Path, previous: Manifest | None) -> Manifest:
    sources, found = skills.import_skills(profile, previous)
    return Manifest((), (), None, sources, found)


def test_import_after_apply_is_stable_with_a_ref(profile, skills_upstream):
    upstream = skills_upstream
    declared = declare(upstream, commit=upstream.first, ref="dev")
    converge(profile, declared)
    assert imported(profile, declared) == declared
    assert imported(profile, None).skill_sources[0].ref is None


def test_import_after_apply_is_stable_from_the_lock(profile, skills_upstream, skill_lock):
    upstream = skills_upstream
    skill_lock(
        {
            s: lock_entry("acme/skills", f"skills/{s}/SKILL.md", upstream.tree(upstream.first, s))
            for s in ("alpha", "beta")
        }
    )
    link_to_agents(profile, "alpha", "beta")
    from_lock = imported(profile, None)
    assert from_lock.skill_sources == (
        SkillSource("acme-skills", "github:acme/skills", None, None),
    )
    # Stand-in for the clone apply makes (no network): same remote, local history.
    clone = skills.sources_dir() / "acme-skills"
    gitops.clone(str(upstream.path), clone, None)
    gitops.run("remote", "set-url", "origin", "https://github.com/acme/skills.git", cwd=clone)
    converge(profile, from_lock)
    assert gitops.head(clone) == upstream.first
    pinned = imported(profile, from_lock)
    assert pinned == Manifest(
        (),
        (),
        None,
        (SkillSource("acme-skills", "github:acme/skills", None, upstream.first),),
        from_lock.skills,
    )
    assert descriptions(profile, pinned) == []
    assert imported(profile, pinned) == pinned
    assert skills.diff(pinned, skills.observe(profile, pinned)) == []


def test_import_accepts_a_skill_changed_since_install(profile, skills_upstream):
    upstream = skills_upstream
    declared = declare(upstream, commit=upstream.second, ref="dev", trees=first_trees(upstream))
    converge(profile, declared)
    assert [d.kind for d in skills.diff(declared, skills.observe(profile, declared))] == [
        "skill-ref",
        "skill-tree",
    ]
    accepted = imported(profile, declared)
    assert (
        accepted.skills
        == declare(
            upstream, trees={s: upstream.tree(upstream.second, s) for s in ("alpha", "beta")}
        ).skills
    )
    # Same name, another source: the ref is not carried over.
    moved = Manifest((), (), None, (SkillSource("tools", "github:perso/x", "dev", None),), ())
    assert imported(profile, moved).skill_sources[0].ref is None


def test_observe_reads_trees_only_for_skills_recording_one(profile, skills_upstream):
    upstream = skills_upstream
    install(profile, upstream, upstream.first)
    declared = declare(upstream, commit=upstream.first, trees={"alpha": "a" * 40})
    clone = skills.observe(profile, declared).clones["tools"]
    assert clone.trees == {"alpha@tools": upstream.tree(upstream.first, "alpha")}


def test_import_skips_a_github_entry_without_source(profile, skill_lock, capsys):
    skill_lock({"tdd": {"sourceType": "github", "skillPath": "skills/tdd/SKILL.md"}})
    link_to_agents(profile, "tdd")
    assert skills.import_skills(profile) == ((), ())
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/tdd" in capsys.readouterr().err


def test_import_refreshes_a_tree_only_for_the_same_id_and_path(profile, skills_upstream):
    upstream = skills_upstream
    install(profile, upstream, upstream.first)
    previous = Manifest(
        (),
        (),
        None,
        (SkillSource("tools", upstream.source, None, upstream.first),),
        (Skill("alpha@tools", "elsewhere/alpha", "a" * 40),),
    )
    assert all(s.tree is None for s in skills.import_skills(profile, previous)[1])


def test_import_keeps_the_name_of_each_clone_in_sources(profile, skills_upstream):
    upstream = skills_upstream
    (profile / "skills").mkdir()
    for name, skill in (("a", "alpha"), ("b", "beta")):
        clone = skills.sources_dir() / name
        gitops.clone(str(upstream.path), clone, None)
        (profile / "skills" / skill).symlink_to(clone / "skills" / skill)
    sources, found = skills.import_skills(profile)
    assert [s.name for s in sources] == ["a", "b"]
    assert [s.id for s in found] == ["alpha@a", "beta@b"]


def test_plan_moves_an_unpinned_clone_to_its_declared_ref(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    declared = declare(upstream, ref="dev")
    assert descriptions(profile, declared) == [
        f"run: git -C ~/.config/claude-sync/sources/tools checkout --detach {upstream.first}"
    ]
    converge(profile, declared)
    assert gitops.head(clone) == upstream.first
    found = skills.diff(declared, skills.observe(profile, declared))
    assert [d.kind for d in found] == ["skill-unpinned"]


def test_import_skips_what_the_manifest_would_reject(profile, skill_lock, capsys):
    skill_lock(
        {
            "root": lock_entry("acme/one", "SKILL.md", "1" * 40),
            "bad-hash": lock_entry("acme/one", "skills/x/SKILL.md", "not hex"),
            "good": lock_entry("acme/one", "skills/good/SKILL.md", "2" * 40),
        }
    )
    link_to_agents(profile, "root", "bad-hash", "good")
    assert skills.import_skills(profile) == (
        (SkillSource("acme-one", "github:acme/one", None, None),),
        (Skill("good@acme-one", "skills/good", "2" * 40),),
    )
    err = capsys.readouterr().err
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/root" in err
    assert "skipped ~/.config/claude-sync/profiles/perso/skills/bad-hash" in err


def test_import_puts_a_lock_entry_under_the_clone_of_its_repository(
    profile, skills_upstream, skill_lock
):
    upstream = skills_upstream
    clone = skills.sources_dir() / "eng"
    gitops.clone(str(upstream.path), clone, None)
    gitops.checkout(clone, upstream.first)
    gitops.run("remote", "set-url", "origin", "https://github.com/acme/skills.git", cwd=clone)
    skill_lock({"beta": lock_entry("acme/skills", "skills/beta/SKILL.md", "2" * 40)})
    (profile / "skills").mkdir()
    (profile / "skills" / "alpha").symlink_to(clone / "skills" / "alpha")
    link_to_agents(profile, "beta")
    assert skills.import_skills(profile) == (
        (SkillSource("eng", "github:acme/skills", None, upstream.first),),
        (Skill("alpha@eng", "skills/alpha", None), Skill("beta@eng", "skills/beta", "2" * 40)),
    )


def add_feature_branch(upstream) -> str:
    """Create `feature` upstream, one commit after `first`; return its head."""
    git = ("-C", str(upstream.path))
    gitops.run(*git, "checkout", "--quiet", "-b", "feature", upstream.first)
    (upstream.path / "skills" / "beta" / "SKILL.md").write_text("# beta, feature\n")
    gitops.run(
        *git,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-am",
        "feature",
    )
    feature = gitops.run(*git, "rev-parse", "HEAD")
    gitops.run(*git, "checkout", "--quiet", "main")
    return feature


def test_plan_fetches_a_ref_created_upstream_after_the_clone(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    feature = add_feature_branch(upstream)
    declared = declare(upstream, ref="feature")
    sources = "~/.config/claude-sync/sources/tools"
    assert descriptions(profile, declared) == [
        f"run: git -C {sources} fetch --tags origin",
        f"run: git -C {sources} checkout --detach <head of feature>",
    ]
    converge(profile, declared)
    assert gitops.head(clone) == feature
    found = skills.diff(declared, skills.observe(profile, declared))
    assert [d.kind for d in found] == ["skill-unpinned"]


def test_plan_fails_on_a_ref_unknown_even_after_the_fetch(profile, skills_upstream):
    upstream = skills_upstream
    install(profile, upstream, upstream.second)
    declared = declare(upstream, ref="nowhere")
    with pytest.raises(ClaudeSyncError, match="unknown ref 'nowhere'"):
        converge(profile, declared)


def test_plan_fetches_an_unknown_ref_before_checking_out_the_commit(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    feature = add_feature_branch(upstream)
    declared = declare(upstream, ref="feature", commit=feature)
    sources = "~/.config/claude-sync/sources/tools"
    assert descriptions(profile, declared) == [
        f"run: git -C {sources} fetch --tags origin",
        f"run: git -C {sources} checkout --detach {feature}",
    ]
    converge(profile, declared)
    assert gitops.head(clone) == feature
    assert skills.diff(declared, skills.observe(profile, declared)) == []
    assert descriptions(profile, declared) == []


def test_late_checkout_refuses_a_dirty_clone(profile, skills_upstream):
    upstream = skills_upstream
    clone = install(profile, upstream, upstream.second)
    add_feature_branch(upstream)
    (clone / "skills" / "alpha" / "SKILL.md").write_text("edited\n")
    with pytest.raises(ClaudeSyncError, match="~/.config/claude-sync/sources/tools"):
        converge(profile, declare(upstream, ref="feature"))
    assert gitops.head(clone) == upstream.second
