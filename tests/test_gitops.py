import subprocess
from pathlib import Path

import pytest

from claude_sync import gitops
from claude_sync.errors import ClaudeSyncError

IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *IDENTITY, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def upstream(tmp_path):
    """A repository on `main` with two commits and a `dev` branch at the first."""
    repo = tmp_path / "upstream"
    (repo / "skills" / "tdd").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch", "main", str(repo)], check=True)
    (repo / "skills" / "tdd" / "SKILL.md").write_text("one\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "one")
    first = git(repo, "rev-parse", "HEAD")
    git(repo, "branch", "dev")
    (repo / "skills" / "tdd" / "SKILL.md").write_text("two\n")
    git(repo, "commit", "--quiet", "-am", "two")
    return repo, first, git(repo, "rev-parse", "HEAD")


def test_run_returns_stripped_stdout(upstream):
    repo, _, second = upstream
    assert gitops.run("rev-parse", "HEAD", cwd=repo) == second


def test_failing_command_raises_with_command_and_stderr(tmp_path):
    with pytest.raises(ClaudeSyncError) as error:
        gitops.run("rev-parse", "--verify", "nope", cwd=tmp_path)
    message = str(error.value)
    assert "git rev-parse --verify nope" in message
    assert "fatal" in message.lower() or "not a git repository" in message.lower()


def test_clone_default_branch_and_head(upstream, tmp_path):
    repo, _, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.head(dest) == second


def test_clone_at_ref(upstream, tmp_path):
    repo, first, _ = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, "dev")
    assert gitops.head(dest) == first
    assert gitops.current_ref(dest) == "dev"


def test_checkout_detaches_at_commit_and_current_ref_is_none(upstream, tmp_path):
    repo, first, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.current_ref(dest) == "main"
    gitops.checkout(dest, first)
    assert gitops.head(dest) == first
    assert gitops.current_ref(dest) is None


def test_fetch_brings_new_commits(upstream, tmp_path):
    repo, _, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    (repo / "new.txt").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "three")
    third = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ClaudeSyncError):
        gitops.checkout(dest, third)
    gitops.fetch(dest)
    gitops.checkout(dest, third)
    assert gitops.head(dest) == third


def test_dirty(upstream, tmp_path):
    repo, _, _ = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.dirty(dest) is False
    (dest / "skills" / "tdd" / "SKILL.md").write_text("local\n")
    assert gitops.dirty(dest) is True


def test_remote_url(upstream, tmp_path):
    repo, _, _ = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.remote_url(dest) == str(repo)
    assert gitops.remote_url(repo) is None


def test_toplevel(upstream, tmp_path):
    repo, _, _ = upstream
    assert gitops.toplevel(repo / "skills" / "tdd") == repo.resolve()
    assert gitops.toplevel(tmp_path) is None
    assert gitops.toplevel(tmp_path / "missing") is None


def test_tree_at(upstream):
    repo, first, second = upstream
    expected = git(repo, "rev-parse", f"{first}:skills/tdd")
    assert gitops.tree_at(repo, first, "skills/tdd") == expected
    assert gitops.tree_at(repo, second, "skills/tdd") != expected
    assert gitops.tree_at(repo, first, "skills/absent") is None


def test_commits_newest_first(upstream, tmp_path):
    repo, first, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.commits(dest, "main") == [second, first]
    assert gitops.commits(dest, "dev") == [first]


@pytest.mark.parametrize(
    ("source", "url"),
    [
        ("github:acme/skills", "https://github.com/acme/skills.git"),
        ("git:https://example.com/x.git", "https://example.com/x.git"),
        ("git:/tmp/some/repo", "/tmp/some/repo"),
    ],
)
def test_url_of_and_source_of_round_trip(source, url):
    assert gitops.url_of(source) == url
    assert gitops.source_of(url) == source


@pytest.mark.parametrize(
    "url", ["https://github.com/acme/skills", "https://github.com/acme/skills.git"]
)
def test_source_of_accepts_github_url_with_or_without_suffix(url):
    assert gitops.source_of(url) == "github:acme/skills"


def test_source_of_other_hosts_is_git():
    assert gitops.source_of("https://example.com/a/b") == "git:https://example.com/a/b"


def commit_upstream(repo: Path, name: str) -> str:
    (repo / name).write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def test_commits_after_fetch_includes_new_upstream_commit(upstream, tmp_path):
    repo, first, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    third = commit_upstream(repo, "three")
    gitops.fetch(dest)
    assert gitops.commits(dest, "main") == [third, second, first]


def test_commits_of_a_branch_that_is_not_checked_out(upstream, tmp_path):
    repo, first, _ = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.commits(dest, "dev") == [first]


def test_commits_of_a_tag(upstream, tmp_path):
    repo, first, _ = upstream
    git(repo, "tag", "v1", first)
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.commits(dest, "v1") == [first]


def test_resolve_ref_prefers_remote_branch_then_tag(upstream, tmp_path):
    repo, first, _ = upstream
    git(repo, "tag", "v1", first)
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.resolve_ref(dest, "dev") == "origin/dev"
    assert gitops.resolve_ref(dest, "v1") == "refs/tags/v1"


def test_resolve_ref_none_is_the_remote_default(upstream, tmp_path):
    repo, _, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.resolve_ref(dest, None) == "origin/HEAD"
    assert gitops.commits(dest, None)[0] == second


def test_resolve_ref_unknown_raises_naming_the_ref(upstream, tmp_path):
    repo, _, _ = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    with pytest.raises(ClaudeSyncError, match="nope"):
        gitops.resolve_ref(dest, "nope")


def test_is_ancestor(upstream, tmp_path):
    repo, first, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.is_ancestor(dest, first, "main") is True
    assert gitops.is_ancestor(dest, second, "dev") is False
    assert gitops.is_ancestor(dest, second, "main") is True


def test_fetch_brings_new_tags(upstream, tmp_path):
    repo, _, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    git(repo, "tag", "v2", second)
    gitops.fetch(dest)
    assert gitops.commits(dest, "v2") == gitops.commits(dest, "main")


def test_source_of_github_url_with_trailing_slash():
    assert gitops.source_of("https://github.com/acme/skills/") == "github:acme/skills"


def test_run_without_git_on_path_raises_claude_sync_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ClaudeSyncError, match="cannot run"):
        gitops.run("--version")


def test_resolve_ref_branch_wins_over_tag_of_the_same_name(upstream, tmp_path):
    repo, first, second = upstream
    git(repo, "tag", "dev", second)
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    assert gitops.resolve_ref(dest, "dev") == "origin/dev"
    assert gitops.commits(dest, "dev") == [first]


def test_is_ancestor_sees_commits_fetched_after_clone(upstream, tmp_path):
    repo, _, second = upstream
    dest = tmp_path / "clone"
    gitops.clone(str(repo), dest, None)
    third = commit_upstream(repo, "three")
    gitops.fetch(dest)
    assert gitops.is_ancestor(dest, third, "main") is True
    assert gitops.is_ancestor(dest, third, None) is True
    assert gitops.is_ancestor(dest, second, None) is True
    assert gitops.is_ancestor(dest, third, "dev") is False
