"""Behaviour of scripts/check-denylist, driven as a subprocess in a throwaway git repo."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-denylist"
TERMS = "acme\nglobex"


class Repo:
    def __init__(self, root: Path, home: Path):
        self.root = root
        self.home = home

    def git(self, *args: str, input: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=self.env(),
            input=input,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def env(self, denylist: str | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "DENYLIST"}
        if denylist is not None:
            env["DENYLIST"] = denylist
        return env

    def write(self, path: str, content: str | bytes) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def commit(self, message: str = "chore: change") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "--short", "HEAD")

    def scan(self, *args: str, denylist: str | None = TERMS, stdin: str | None = None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.root,
            env=self.env(denylist),
            input=stdin,
            capture_output=True,
            text=True,
        )


@pytest.fixture
def repo(tmp_path, isolated_environment):
    root = tmp_path / "repo"
    root.mkdir()
    r = Repo(root, isolated_environment)
    r.git("init", "-q", "-b", "main")
    r.git("config", "user.name", "Test")
    r.git("config", "user.email", "test@example.com")
    r.write("README.md", "clean\n")
    r.commit("chore: init")
    return r


def output(result) -> str:
    return result.stdout + result.stderr


def test_empty_denylist_fails_closed(repo):
    result = repo.scan("--tree", denylist="")
    assert result.returncode == 3
    assert "denylist is empty or missing" in output(result)


def test_clean_repo_exits_zero(repo):
    result = repo.scan("--tree")
    assert result.returncode == 0
    assert output(result) == ""


def test_tree_finding_names_line_and_term_index_without_the_term(repo):
    repo.write("README.md", "one\ntwo\nworks at globex today\n")
    repo.commit()
    result = repo.scan("--tree")
    assert result.returncode == 1
    assert "README.md:3: term #2" in result.stdout
    assert "globex" not in output(result).lower()


def test_comments_and_blank_lines_are_ignored_in_numbering(repo):
    repo.write("README.md", "globex\n")
    repo.commit()
    result = repo.scan("--tree", denylist="# note\n\n  \nacme\n# more\nglobex\n")
    assert "README.md:1: term #2" in result.stdout


def test_matching_is_case_insensitive(repo):
    repo.write("README.md", "ACME Corp\n")
    repo.commit()
    result = repo.scan("--tree")
    assert "README.md:1: term #1" in result.stdout


def test_denylist_read_from_home_file_when_env_unset(repo):
    config = repo.home / ".config" / "claude-sync"
    config.mkdir(parents=True)
    (config / "denylist.txt").write_text("acme\n")
    repo.write("a.txt", "acme\n")
    repo.commit()
    result = repo.scan("--tree", denylist=None)
    assert result.returncode == 1
    assert "a.txt:1: term #1" in result.stdout


def test_missing_denylist_file_fails_closed(repo):
    result = repo.scan("--tree", denylist=None)
    assert result.returncode == 3
    assert "denylist is empty or missing" in output(result)


def test_binary_file_is_skipped(repo):
    repo.write("blob.bin", b"\x00\x01acme\x00")
    repo.commit()
    result = repo.scan("--tree")
    assert result.returncode == 0


def test_term_in_a_path_is_reported_by_position_without_the_path(repo):
    repo.write("docs/acme-notes.md", "clean\n")
    repo.commit()
    paths = repo.git("ls-files").splitlines()
    k = paths.index("docs/acme-notes.md") + 1
    result = repo.scan("--tree")
    assert result.returncode == 1
    assert f"path #{k}: term #1" in result.stdout
    assert "acme" not in output(result).lower()
    assert "notes" not in output(result)


def test_content_finding_in_a_matching_path_never_prints_the_path(repo):
    repo.write("acme.txt", "globex\n")
    repo.commit()
    k = repo.git("ls-files").splitlines().index("acme.txt") + 1
    result = repo.scan("--tree")
    assert f"path #{k}:1: term #2" in result.stdout
    assert "acme.txt" not in output(result)


def test_staged_reports_added_line_with_hunk_line_number(repo):
    repo.write("notes.txt", "1\n2\n3\n4\n5\n")
    repo.commit()
    repo.write("notes.txt", "1\n2\n3\n4\nfive acme\nsix\nGLOBEX seven\n")
    repo.git("add", "notes.txt")
    result = repo.scan("--staged")
    assert result.returncode == 1
    assert "notes.txt:5: term #1" in result.stdout
    assert "notes.txt:7: term #2" in result.stdout
    assert "notes.txt:6" not in result.stdout
    assert "acme" not in output(result).lower()


def test_staged_ignores_unstaged_and_removed_lines(repo):
    repo.write("notes.txt", "acme\nkeep\n")
    repo.commit()
    repo.write("notes.txt", "keep\n")
    repo.git("add", "notes.txt")
    repo.write("other.txt", "acme\n")
    result = repo.scan("--staged")
    assert result.returncode == 0


def test_staged_path_with_term_is_reported_by_position(repo):
    repo.write("acme.txt", "clean\n")
    repo.git("add", "acme.txt")
    result = repo.scan("--staged")
    assert "path #1: term #1" in result.stdout
    assert "acme" not in output(result).lower()


def test_staged_content_in_matching_path_never_prints_the_path(repo):
    repo.write("acme.txt", "x\nglobex\n")
    repo.git("add", "acme.txt")
    result = repo.scan("--staged")
    assert "path #1:2: term #2" in result.stdout
    assert "acme.txt" not in output(result)


def test_history_finds_a_term_added_then_removed(repo):
    repo.write("old.txt", "a\nb\nacme\n")
    sha = repo.commit("feat: add")
    repo.write("old.txt", "a\nb\n")
    repo.commit("fix: remove")
    assert repo.scan("--tree").returncode == 0
    result = repo.scan("--history")
    assert result.returncode == 1
    assert f"{sha}:old.txt:3: term #1" in result.stdout
    assert "acme" not in output(result).lower()


def test_history_reports_a_term_in_a_path_by_position(repo):
    repo.write("globex.txt", "clean\n")
    sha = repo.commit("feat: add")
    result = repo.scan("--history")
    assert f"{sha}: path #1: term #2" in result.stdout
    assert f"{sha}:path #1:1" not in result.stdout
    assert "globex" not in output(result).lower()


def test_history_reports_a_term_in_a_commit_message(repo):
    repo.write("a.txt", "clean\n")
    sha = repo.commit("feat: work for Acme\n\nbody")
    result = repo.scan("--history")
    assert result.returncode == 1
    assert f"{sha}: message: term #1" in result.stdout
    assert "acme" not in output(result).lower()


def test_history_covers_every_branch(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.txt", "globex\n")
    sha = repo.commit("feat: side")
    repo.git("checkout", "-q", "main")
    result = repo.scan("--history")
    assert f"{sha}:side.txt:1: term #2" in result.stdout


def test_history_scans_content_introduced_by_a_merge(repo):
    repo.git("checkout", "-q", "-b", "side")
    repo.write("side.txt", "clean\n")
    repo.commit("feat: side")
    repo.git("checkout", "-q", "main")
    repo.write("main.txt", "clean\n")
    repo.commit("feat: main")
    repo.git("merge", "-q", "--no-commit", "side")
    repo.write("merge.txt", "globex\n")
    repo.git("add", "merge.txt")
    repo.git("commit", "-q", "-m", "chore: merge side")
    sha = repo.git("rev-parse", "--short", "HEAD")
    repo.write("merge.txt", "clean\n")
    repo.commit("fix: clean")
    result = repo.scan("--history")
    assert result.returncode == 1
    assert f"{sha}:" in result.stdout and "term #2" in result.stdout


def test_history_scans_author_and_committer_identities(repo):
    repo.write("a.txt", "clean\n")
    repo.git("add", "a.txt")
    repo.git(
        "-c",
        "user.email=dev@acme.example",
        "commit",
        "-q",
        "-m",
        "feat: add",
        "--author",
        "Dev <dev@acme.example>",
    )
    sha = repo.git("rev-parse", "--short", "HEAD")
    result = repo.scan("--history")
    assert result.returncode == 1
    assert f"{sha}: identity: term #1" in result.stdout
    assert "acme" not in output(result).lower()


def test_history_of_a_clean_repo_exits_zero(repo):
    assert repo.scan("--history").returncode == 0


def test_message_file_is_reported_as_message(repo):
    msg = repo.root.parent / "MSG"
    msg.write_text("feat: for globex\n")
    result = repo.scan("--message-file", str(msg))
    assert result.returncode == 1
    assert "message: term #2" in result.stdout
    assert "globex" not in output(result).lower()
    assert str(msg) not in output(result)


def test_clean_message_file_exits_zero(repo):
    msg = repo.root.parent / "MSG"
    msg.write_text("feat: fine\n")
    assert repo.scan("--message-file", str(msg)).returncode == 0


def test_text_from_stdin_is_reported_under_the_label(repo):
    result = repo.scan("--text", "pr-body", stdin="line one\nmentions Acme\n")
    assert result.returncode == 1
    assert "pr-body: term #1" in result.stdout
    assert "acme" not in output(result).lower()


def test_clean_text_exits_zero(repo):
    assert repo.scan("--text", "pr-title", stdin="all good").returncode == 0


def test_options_can_be_combined(repo):
    repo.write("a.txt", "acme\n")
    repo.commit()
    result = repo.scan("--tree", "--text", "pr-title", stdin="globex")
    assert "a.txt:1: term #1" in result.stdout
    assert "pr-title: term #2" in result.stdout


def test_at_least_one_target_is_required(repo):
    result = repo.scan()
    assert result.returncode == 2


def test_refuses_to_run_when_a_denylist_file_is_tracked(repo):
    repo.write("config/denylist.txt", "acme\n")
    repo.git("add", "-f", "config/denylist.txt")
    result = repo.scan("--tree")
    assert result.returncode not in (0, 1)
    assert "denylist.txt" in output(result)
    assert "acme" not in output(result).lower()


def test_unexpected_failure_prints_a_fixed_message_without_git_output(tmp_path, repo):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tree"],
        cwd=outside,
        env={**repo.env(TERMS), "GIT_CEILING_DIRECTORIES": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Traceback" not in output(result)
    assert "fatal" not in output(result)
    assert "scan failed" in output(result)


def test_help_documents_options_examples_and_exit_codes(repo):
    result = repo.scan("--help")
    assert result.returncode == 0
    for needle in ("--tree", "--staged", "--history", "--message-file", "--text", "Examples", "3"):
        assert needle in result.stdout


ROOT = SCRIPT.parent.parent


@pytest.fixture
def hooked(repo):
    """The temp repo with the real scripts and hooks copied in, hooks installed."""
    shutil.copytree(ROOT / "scripts", repo.root / "scripts")
    shutil.copytree(ROOT / ".githooks", repo.root / ".githooks")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "chore: tooling")
    subprocess.run([str(repo.root / "scripts" / "install-hooks")], cwd=repo.root, check=True)
    return repo


def try_commit(repo, message: str, denylist: str = TERMS):
    return subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=repo.root,
        env=repo.env(denylist),
        capture_output=True,
        text=True,
    )


def test_install_hooks_points_git_at_the_hooks_directory(hooked):
    assert hooked.git("config", "core.hooksPath") == ".githooks"


def test_hook_files_are_executable():
    for name in ("pre-commit", "commit-msg", "pre-push"):
        assert os.access(ROOT / ".githooks" / name, os.X_OK)
    assert os.access(ROOT / "scripts" / "install-hooks", os.X_OK)


def test_pre_commit_rejects_a_staged_term(hooked):
    hooked.write("a.txt", "work for acme\n")
    hooked.git("add", "a.txt")
    result = try_commit(hooked, "feat: clean message")
    assert result.returncode != 0
    assert "a.txt:1: term #1" in output(result)
    assert "acme" not in output(result).lower()
    assert hooked.git("log", "--oneline").count("\n") == 1  # only init + tooling


def test_commit_msg_rejects_a_term_in_the_message(hooked):
    hooked.write("a.txt", "clean\n")
    hooked.git("add", "a.txt")
    result = try_commit(hooked, "feat: for globex")
    assert result.returncode != 0
    assert "message: term #2" in output(result)
    assert "globex" not in output(result).lower()


def test_clean_commit_passes_the_hooks(hooked):
    hooked.write("a.txt", "clean\n")
    hooked.git("add", "a.txt")
    assert try_commit(hooked, "feat: fine").returncode == 0


def test_pre_commit_warns_when_gitleaks_is_missing(hooked):
    hooked.write("a.txt", "clean\n")
    hooked.git("add", "a.txt")
    env = hooked.env(TERMS)
    env["PATH"] = os.pathsep.join(
        p for p in env["PATH"].split(os.pathsep) if not (Path(p) / "gitleaks").exists()
    )
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "feat: fine"],
        cwd=hooked.root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "gitleaks not installed" in output(result)


def test_pre_push_rejects_a_term_in_history(hooked):
    hooked.write("a.txt", "acme\n")
    hooked.git("add", "a.txt")
    hooked.git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "feat: leak")
    remote = hooked.root.parent / "remote.git"
    hooked.git("init", "-q", "--bare", str(remote))
    result = subprocess.run(
        ["git", "push", "-q", str(remote), "main"],
        cwd=hooked.root,
        env=hooked.env(TERMS),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "term #1" in output(result)
    assert "acme" not in output(result).lower()
