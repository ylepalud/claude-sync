diff --git a/.githooks/commit-msg b/.githooks/commit-msg
new file mode 100755
index 0000000..d3dacf3
--- /dev/null
+++ b/.githooks/commit-msg
@@ -0,0 +1,3 @@
+#!/bin/sh
+# Block a commit whose message carries a denylisted term.
+exec scripts/check-denylist --message-file "$1"
diff --git a/.githooks/pre-commit b/.githooks/pre-commit
new file mode 100755
index 0000000..3ffcc02
--- /dev/null
+++ b/.githooks/pre-commit
@@ -0,0 +1,9 @@
+#!/bin/sh
+# Block a commit whose staged content carries a denylisted term or a secret.
+set -e
+scripts/check-denylist --staged
+if command -v gitleaks >/dev/null 2>&1; then
+    gitleaks git --staged --redact
+else
+    echo "warning: gitleaks not installed, secret scan skipped (CI still runs it)" >&2
+fi
diff --git a/.githooks/pre-push b/.githooks/pre-push
new file mode 100755
index 0000000..5f54245
--- /dev/null
+++ b/.githooks/pre-push
@@ -0,0 +1,3 @@
+#!/bin/sh
+# Check the full history before anything becomes public.
+exec scripts/check-denylist --history
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
new file mode 100644
index 0000000..012666c
--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,56 @@
+name: CI
+
+on:
+  push:
+  pull_request:
+    types: [opened, synchronize, reopened, edited]
+
+permissions:
+  contents: read
+
+jobs:
+  test:
+    runs-on: ubuntu-latest
+    strategy:
+      matrix:
+        python-version: ["3.11", "3.13"]
+    steps:
+      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
+      - uses: astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3
+        with:
+          python-version: ${{ matrix.python-version }}
+      - run: uv sync
+      - run: uv run ruff check
+      - run: uv run ruff format --check
+      - run: uv run pytest
+
+  leak-guard:
+    runs-on: ubuntu-latest
+    env:
+      DENYLIST: ${{ secrets.DENYLIST }}
+    steps:
+      - name: Require the DENYLIST secret
+        run: test -n "$DENYLIST" || { echo "DENYLIST secret is missing or empty"; exit 1; }
+      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
+        with:
+          fetch-depth: 0
+      - name: Scan tree, history and commit messages
+        run: scripts/check-denylist --tree --history
+      - name: Scan the pull request title
+        if: github.event_name == 'pull_request'
+        env:
+          PR_TITLE: ${{ github.event.pull_request.title }}
+        run: printf '%s' "$PR_TITLE" | scripts/check-denylist --text pr-title
+      - name: Scan the pull request body
+        if: github.event_name == 'pull_request'
+        env:
+          PR_BODY: ${{ github.event.pull_request.body }}
+        run: printf '%s' "$PR_BODY" | scripts/check-denylist --text pr-body
+      - name: Scan the full history for secrets
+        run: |
+          base=https://github.com/gitleaks/gitleaks/releases/download/v8.30.1
+          curl -sSfLO "$base/gitleaks_8.30.1_linux_x64.tar.gz"
+          curl -sSfLO "$base/gitleaks_8.30.1_checksums.txt"
+          sha256sum -c --ignore-missing gitleaks_8.30.1_checksums.txt
+          tar -xzf gitleaks_8.30.1_linux_x64.tar.gz gitleaks
+          ./gitleaks git --redact --log-opts=--all .
diff --git a/scripts/check-denylist b/scripts/check-denylist
new file mode 100755
index 0000000..ad1ea74
--- /dev/null
+++ b/scripts/check-denylist
@@ -0,0 +1,233 @@
+#!/usr/bin/env python3
+"""Scan this repository for denylisted terms without ever printing them."""
+
+import argparse
+import os
+import re
+import subprocess
+import sys
+from pathlib import Path
+
+EXIT_FINDINGS = 1
+EXIT_NO_TERMS = 3
+EXIT_REFUSED = 4
+
+
+def load_terms() -> list[str]:
+    raw = os.environ.get("DENYLIST")
+    if raw is None:
+        path = Path.home() / ".config" / "claude-sync" / "denylist.txt"
+        try:
+            raw = path.read_text(encoding="utf-8")
+        except OSError:
+            raw = ""
+    lines = (line.strip() for line in raw.splitlines())
+    return [line.lower() for line in lines if line and not line.startswith("#")]
+
+
+class Scanner:
+    def __init__(self, terms: list[str]):
+        self.terms = terms
+        self.findings: list[str] = []
+
+    def match(self, text: str) -> list[int]:
+        """Return the 1-based index of every term found in text."""
+        lowered = text.lower()
+        return [n for n, term in enumerate(self.terms, 1) if term in lowered]
+
+    def path_label(self, path: str, placeholder: str) -> str:
+        """Name a path, or its placeholder when the path itself carries a term."""
+        return placeholder if self.match(path) else path
+
+    def report(self, location: str, text: str) -> None:
+        for n in self.match(text):
+            self.findings.append(f"{location}: term #{n}")
+
+    def scan_lines(self, prefix: str, text: str) -> None:
+        for number, line in enumerate(text.split("\n"), 1):
+            self.report(f"{prefix}{number}", line)
+
+
+def git(*args: str) -> bytes:
+    return subprocess.run(["git", *args], capture_output=True, check=True).stdout  # stderr captured
+
+
+def git_names(*args: str) -> list[str]:
+    """Run a git command that prints NUL-separated names."""
+    return [n for n in git(*args).decode("utf-8", "replace").split("\0") if n]
+
+
+def is_binary(data: bytes) -> bool:
+    return b"\0" in data[:8192]
+
+
+def scan_tree(scanner: Scanner) -> None:
+    names = git_names("ls-files", "-z")
+    for position, name in enumerate(names, 1):
+        scanner.report(f"path #{position}", name)
+        label = scanner.path_label(name, f"path #{position}")
+        try:
+            data = Path(name).read_bytes()
+        except OSError:
+            continue
+        if is_binary(data):
+            continue
+        scanner.scan_lines(f"{label}:", data.decode("utf-8", "replace"))
+
+
+HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@")
+DIFF_ARGS = ["-U0", "--no-color", "--no-ext-diff"]
+
+
+def header_path(rest: str) -> str:
+    """Extract the path from the part of a `diff --git` line after the keyword."""
+    n = (len(rest) - 5) // 2
+    if n > 0 and rest[2 : 2 + n] == rest[-n:]:
+        return rest[2 : 2 + n]
+    return rest.rsplit(" b/", 1)[-1]
+
+
+def scan_diff(scanner: Scanner, text: str, sha: str = "") -> None:
+    """Scan the added lines of a unified diff, one location per added line.
+
+    With a sha (history), paths are scanned too, by position in the diff.
+    """
+    label = ""
+    file_index = 0
+    in_hunk = False
+    number = 0
+    for line in text.split("\n"):
+        if line.startswith("diff --git "):
+            file_index += 1
+            in_hunk = False
+            name = header_path(line[len("diff --git ") :])
+            placeholder = f"path #{file_index}"
+            label = scanner.path_label(name, placeholder)
+            if sha:
+                scanner.report(f"{sha}: {placeholder}", name)
+        elif line.startswith("@@"):
+            hunk = HUNK.match(line)
+            if hunk:
+                in_hunk = True
+                number = int(hunk.group(1))
+        elif in_hunk and line.startswith("+"):
+            where = f"{sha}:" if sha else ""
+            scanner.report(f"{where}{label}:{number}", line[1:])
+            number += 1
+
+
+def scan_history(scanner: Scanner) -> None:
+    log = git("log", "--all", "-p", *DIFF_ARGS, "--format=%x00commit %H")
+    for chunk in log.decode("utf-8", "replace").split("\0commit ")[1:]:
+        sha, _, diff = chunk.partition("\n")
+        scan_diff(scanner, diff, sha[:7])
+    messages = git("log", "--all", "--format=%H%x00%B%x00").decode("utf-8", "replace")
+    fields = messages.split("\0")
+    for sha, body in zip(fields[0::2], fields[1::2], strict=False):
+        scanner.report(f"{sha.strip()[:7]}: message", body)
+
+
+def scan_staged(scanner: Scanner) -> None:
+    names = git_names("diff", "--cached", "--name-only", "-z")
+    for position, name in enumerate(names, 1):
+        scanner.report(f"path #{position}", name)
+    diff = git("diff", "--cached", *DIFF_ARGS).decode("utf-8", "replace")
+    scan_diff(scanner, diff)
+
+
+EPILOG = """\
+Findings are printed as "<location>: term #<n>", where n is the 1-based position of
+the term in the denylist. The term, the matching line and any path that contains a
+term are never printed, so CI logs stay safe to publish.
+
+Locations:
+  <path>:<line>            added or tracked line
+  path #<k>                the path itself matches (k = position in the scanned list)
+  <sha>:<path>:<line>      history, sha is the 7-character commit id
+  <sha>: message           a commit message
+  message / <label>        --message-file / --text
+
+Terms come from the DENYLIST environment variable when it is set (even empty),
+otherwise from ~/.config/claude-sync/denylist.txt: one term per line, blank lines
+and lines starting with # ignored, matching is case-insensitive.
+
+Examples:
+  scripts/check-denylist --staged
+  scripts/check-denylist --tree --history
+  scripts/check-denylist --message-file .git/COMMIT_EDITMSG
+  printf '%s' "$PR_BODY" | scripts/check-denylist --text pr-body
+
+Exit codes:
+  0  clean
+  1  findings, or an unexpected failure
+  2  usage error
+  3  denylist is empty or missing
+  4  a tracked file is named denylist.txt (refused)
+"""
+
+
+def build_parser() -> argparse.ArgumentParser:
+    parser = argparse.ArgumentParser(
+        prog="check-denylist",
+        description="Scan for denylisted terms without ever printing them.",
+        epilog=EPILOG,
+        formatter_class=argparse.RawDescriptionHelpFormatter,
+    )
+    parser.add_argument("--tree", action="store_true", help="tracked files and their paths")
+    parser.add_argument("--staged", action="store_true", help="added lines and paths staged")
+    parser.add_argument(
+        "--history", action="store_true", help="every commit and message on every branch"
+    )
+    parser.add_argument("--message-file", metavar="PATH", help="a commit message file")
+    parser.add_argument(
+        "--text", metavar="LABEL", help="free text read from stdin, reported under LABEL"
+    )
+    return parser
+
+
+def tracked_denylist_file() -> bool:
+    names = git_names("ls-files", "-z")
+    return any(n == "denylist.txt" or n.endswith("/denylist.txt") for n in names)
+
+
+def run(args: argparse.Namespace) -> int:
+    terms = load_terms()
+    if not terms:
+        print("denylist is empty or missing", file=sys.stderr)
+        return EXIT_NO_TERMS
+    if tracked_denylist_file():
+        print("refusing to run: a tracked file is named denylist.txt", file=sys.stderr)
+        return EXIT_REFUSED
+    scanner = Scanner(terms)
+    if args.tree:
+        scan_tree(scanner)
+    if args.staged:
+        scan_staged(scanner)
+    if args.history:
+        scan_history(scanner)
+    if args.message_file is not None:
+        text = Path(args.message_file).read_bytes().decode("utf-8", "replace")
+        scanner.report("message", text)
+    if args.text is not None:
+        scanner.report(args.text, sys.stdin.buffer.read().decode("utf-8", "replace"))
+    for finding in scanner.findings:
+        print(finding)
+    return EXIT_FINDINGS if scanner.findings else 0
+
+
+def main() -> int:
+    parser = build_parser()
+    args = parser.parse_args()
+    chosen = [args.tree, args.staged, args.history, args.message_file is not None]
+    if not (any(chosen) or args.text is not None):
+        parser.error("choose at least one of --tree, --staged, --history, --message-file, --text")
+    try:
+        return run(args)
+    except Exception:
+        # Never show the exception: it could carry file content or git output.
+        print("scan failed (details withheld to keep the denylist private)", file=sys.stderr)
+        return EXIT_FINDINGS
+
+
+if __name__ == "__main__":
+    sys.exit(main())
diff --git a/scripts/install-hooks b/scripts/install-hooks
new file mode 100755
index 0000000..6f9cbbb
--- /dev/null
+++ b/scripts/install-hooks
@@ -0,0 +1,5 @@
+#!/bin/sh
+# Point git at the versioned hooks in .githooks.
+set -e
+git config core.hooksPath .githooks
+echo "git hooks installed (core.hooksPath=.githooks)"
diff --git a/tests/test_check_denylist.py b/tests/test_check_denylist.py
new file mode 100644
index 0000000..ecea844
--- /dev/null
+++ b/tests/test_check_denylist.py
@@ -0,0 +1,405 @@
+"""Behaviour of scripts/check-denylist, driven as a subprocess in a throwaway git repo."""
+
+import os
+import shutil
+import subprocess
+import sys
+from pathlib import Path
+
+import pytest
+
+SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-denylist"
+TERMS = "acme\nglobex"
+
+
+class Repo:
+    def __init__(self, root: Path, home: Path):
+        self.root = root
+        self.home = home
+
+    def git(self, *args: str, input: str | None = None) -> str:
+        result = subprocess.run(
+            ["git", *args],
+            cwd=self.root,
+            env=self.env(),
+            input=input,
+            capture_output=True,
+            text=True,
+            check=True,
+        )
+        return result.stdout.strip()
+
+    def env(self, denylist: str | None = None) -> dict[str, str]:
+        env = {k: v for k, v in os.environ.items() if k != "DENYLIST"}
+        if denylist is not None:
+            env["DENYLIST"] = denylist
+        return env
+
+    def write(self, path: str, content: str | bytes) -> None:
+        target = self.root / path
+        target.parent.mkdir(parents=True, exist_ok=True)
+        if isinstance(content, bytes):
+            target.write_bytes(content)
+        else:
+            target.write_text(content)
+
+    def commit(self, message: str = "chore: change") -> str:
+        self.git("add", "-A")
+        self.git("commit", "-q", "-m", message)
+        return self.git("rev-parse", "--short", "HEAD")
+
+    def scan(self, *args: str, denylist: str | None = TERMS, stdin: str | None = None):
+        return subprocess.run(
+            [sys.executable, str(SCRIPT), *args],
+            cwd=self.root,
+            env=self.env(denylist),
+            input=stdin,
+            capture_output=True,
+            text=True,
+        )
+
+
+@pytest.fixture
+def repo(tmp_path, isolated_environment):
+    root = tmp_path / "repo"
+    root.mkdir()
+    r = Repo(root, isolated_environment)
+    r.git("init", "-q", "-b", "main")
+    r.git("config", "user.name", "Test")
+    r.git("config", "user.email", "test@example.com")
+    r.write("README.md", "clean\n")
+    r.commit("chore: init")
+    return r
+
+
+def output(result) -> str:
+    return result.stdout + result.stderr
+
+
+def test_empty_denylist_fails_closed(repo):
+    result = repo.scan("--tree", denylist="")
+    assert result.returncode == 3
+    assert "denylist is empty or missing" in output(result)
+
+
+def test_clean_repo_exits_zero(repo):
+    result = repo.scan("--tree")
+    assert result.returncode == 0
+    assert output(result) == ""
+
+
+def test_tree_finding_names_line_and_term_index_without_the_term(repo):
+    repo.write("README.md", "one\ntwo\nworks at globex today\n")
+    repo.commit()
+    result = repo.scan("--tree")
+    assert result.returncode == 1
+    assert "README.md:3: term #2" in result.stdout
+    assert "globex" not in output(result).lower()
+
+
+def test_comments_and_blank_lines_are_ignored_in_numbering(repo):
+    repo.write("README.md", "globex\n")
+    repo.commit()
+    result = repo.scan("--tree", denylist="# note\n\n  \nacme\n# more\nglobex\n")
+    assert "README.md:1: term #2" in result.stdout
+
+
+def test_matching_is_case_insensitive(repo):
+    repo.write("README.md", "ACME Corp\n")
+    repo.commit()
+    result = repo.scan("--tree")
+    assert "README.md:1: term #1" in result.stdout
+
+
+def test_denylist_read_from_home_file_when_env_unset(repo):
+    config = repo.home / ".config" / "claude-sync"
+    config.mkdir(parents=True)
+    (config / "denylist.txt").write_text("acme\n")
+    repo.write("a.txt", "acme\n")
+    repo.commit()
+    result = repo.scan("--tree", denylist=None)
+    assert result.returncode == 1
+    assert "a.txt:1: term #1" in result.stdout
+
+
+def test_missing_denylist_file_fails_closed(repo):
+    result = repo.scan("--tree", denylist=None)
+    assert result.returncode == 3
+    assert "denylist is empty or missing" in output(result)
+
+
+def test_binary_file_is_skipped(repo):
+    repo.write("blob.bin", b"\x00\x01acme\x00")
+    repo.commit()
+    result = repo.scan("--tree")
+    assert result.returncode == 0
+
+
+def test_term_in_a_path_is_reported_by_position_without_the_path(repo):
+    repo.write("docs/acme-notes.md", "clean\n")
+    repo.commit()
+    paths = repo.git("ls-files").splitlines()
+    k = paths.index("docs/acme-notes.md") + 1
+    result = repo.scan("--tree")
+    assert result.returncode == 1
+    assert f"path #{k}: term #1" in result.stdout
+    assert "acme" not in output(result).lower()
+    assert "notes" not in output(result)
+
+
+def test_content_finding_in_a_matching_path_never_prints_the_path(repo):
+    repo.write("acme.txt", "globex\n")
+    repo.commit()
+    k = repo.git("ls-files").splitlines().index("acme.txt") + 1
+    result = repo.scan("--tree")
+    assert f"path #{k}:1: term #2" in result.stdout
+    assert "acme.txt" not in output(result)
+
+
+def test_staged_reports_added_line_with_hunk_line_number(repo):
+    repo.write("notes.txt", "1\n2\n3\n4\n5\n")
+    repo.commit()
+    repo.write("notes.txt", "1\n2\n3\n4\nfive acme\nsix\nGLOBEX seven\n")
+    repo.git("add", "notes.txt")
+    result = repo.scan("--staged")
+    assert result.returncode == 1
+    assert "notes.txt:5: term #1" in result.stdout
+    assert "notes.txt:7: term #2" in result.stdout
+    assert "notes.txt:6" not in result.stdout
+    assert "acme" not in output(result).lower()
+
+
+def test_staged_ignores_unstaged_and_removed_lines(repo):
+    repo.write("notes.txt", "acme\nkeep\n")
+    repo.commit()
+    repo.write("notes.txt", "keep\n")
+    repo.git("add", "notes.txt")
+    repo.write("other.txt", "acme\n")
+    result = repo.scan("--staged")
+    assert result.returncode == 0
+
+
+def test_staged_path_with_term_is_reported_by_position(repo):
+    repo.write("acme.txt", "clean\n")
+    repo.git("add", "acme.txt")
+    result = repo.scan("--staged")
+    assert "path #1: term #1" in result.stdout
+    assert "acme" not in output(result).lower()
+
+
+def test_staged_content_in_matching_path_never_prints_the_path(repo):
+    repo.write("acme.txt", "x\nglobex\n")
+    repo.git("add", "acme.txt")
+    result = repo.scan("--staged")
+    assert "path #1:2: term #2" in result.stdout
+    assert "acme.txt" not in output(result)
+
+
+def test_history_finds_a_term_added_then_removed(repo):
+    repo.write("old.txt", "a\nb\nacme\n")
+    sha = repo.commit("feat: add")
+    repo.write("old.txt", "a\nb\n")
+    repo.commit("fix: remove")
+    assert repo.scan("--tree").returncode == 0
+    result = repo.scan("--history")
+    assert result.returncode == 1
+    assert f"{sha}:old.txt:3: term #1" in result.stdout
+    assert "acme" not in output(result).lower()
+
+
+def test_history_reports_a_term_in_a_path_by_position(repo):
+    repo.write("globex.txt", "clean\n")
+    sha = repo.commit("feat: add")
+    result = repo.scan("--history")
+    assert f"{sha}: path #1: term #2" in result.stdout
+    assert f"{sha}:path #1:1" not in result.stdout
+    assert "globex" not in output(result).lower()
+
+
+def test_history_reports_a_term_in_a_commit_message(repo):
+    repo.write("a.txt", "clean\n")
+    sha = repo.commit("feat: work for Acme\n\nbody")
+    result = repo.scan("--history")
+    assert result.returncode == 1
+    assert f"{sha}: message: term #1" in result.stdout
+    assert "acme" not in output(result).lower()
+
+
+def test_history_covers_every_branch(repo):
+    repo.git("checkout", "-q", "-b", "side")
+    repo.write("side.txt", "globex\n")
+    sha = repo.commit("feat: side")
+    repo.git("checkout", "-q", "main")
+    result = repo.scan("--history")
+    assert f"{sha}:side.txt:1: term #2" in result.stdout
+
+
+def test_history_of_a_clean_repo_exits_zero(repo):
+    assert repo.scan("--history").returncode == 0
+
+
+def test_message_file_is_reported_as_message(repo):
+    msg = repo.root.parent / "MSG"
+    msg.write_text("feat: for globex\n")
+    result = repo.scan("--message-file", str(msg))
+    assert result.returncode == 1
+    assert "message: term #2" in result.stdout
+    assert "globex" not in output(result).lower()
+    assert str(msg) not in output(result)
+
+
+def test_clean_message_file_exits_zero(repo):
+    msg = repo.root.parent / "MSG"
+    msg.write_text("feat: fine\n")
+    assert repo.scan("--message-file", str(msg)).returncode == 0
+
+
+def test_text_from_stdin_is_reported_under_the_label(repo):
+    result = repo.scan("--text", "pr-body", stdin="line one\nmentions Acme\n")
+    assert result.returncode == 1
+    assert "pr-body: term #1" in result.stdout
+    assert "acme" not in output(result).lower()
+
+
+def test_clean_text_exits_zero(repo):
+    assert repo.scan("--text", "pr-title", stdin="all good").returncode == 0
+
+
+def test_options_can_be_combined(repo):
+    repo.write("a.txt", "acme\n")
+    repo.commit()
+    result = repo.scan("--tree", "--text", "pr-title", stdin="globex")
+    assert "a.txt:1: term #1" in result.stdout
+    assert "pr-title: term #2" in result.stdout
+
+
+def test_at_least_one_target_is_required(repo):
+    result = repo.scan()
+    assert result.returncode == 2
+
+
+def test_refuses_to_run_when_a_denylist_file_is_tracked(repo):
+    repo.write("config/denylist.txt", "acme\n")
+    repo.git("add", "-f", "config/denylist.txt")
+    result = repo.scan("--tree")
+    assert result.returncode not in (0, 1)
+    assert "denylist.txt" in output(result)
+    assert "acme" not in output(result).lower()
+
+
+def test_unexpected_failure_prints_a_fixed_message_without_git_output(tmp_path, repo):
+    outside = tmp_path / "not-a-repo"
+    outside.mkdir()
+    result = subprocess.run(
+        [sys.executable, str(SCRIPT), "--tree"],
+        cwd=outside,
+        env={**repo.env(TERMS), "GIT_CEILING_DIRECTORIES": str(tmp_path)},
+        capture_output=True,
+        text=True,
+    )
+    assert result.returncode == 1
+    assert "Traceback" not in output(result)
+    assert "fatal" not in output(result)
+    assert "scan failed" in output(result)
+
+
+def test_help_documents_options_examples_and_exit_codes(repo):
+    result = repo.scan("--help")
+    assert result.returncode == 0
+    for needle in ("--tree", "--staged", "--history", "--message-file", "--text", "Examples", "3"):
+        assert needle in result.stdout
+
+
+ROOT = SCRIPT.parent.parent
+
+
+@pytest.fixture
+def hooked(repo):
+    """The temp repo with the real scripts and hooks copied in, hooks installed."""
+    shutil.copytree(ROOT / "scripts", repo.root / "scripts")
+    shutil.copytree(ROOT / ".githooks", repo.root / ".githooks")
+    repo.git("add", "-A")
+    repo.git("commit", "-q", "-m", "chore: tooling")
+    subprocess.run([str(repo.root / "scripts" / "install-hooks")], cwd=repo.root, check=True)
+    return repo
+
+
+def try_commit(repo, message: str, denylist: str = TERMS):
+    return subprocess.run(
+        ["git", "commit", "-q", "-m", message],
+        cwd=repo.root,
+        env=repo.env(denylist),
+        capture_output=True,
+        text=True,
+    )
+
+
+def test_install_hooks_points_git_at_the_hooks_directory(hooked):
+    assert hooked.git("config", "core.hooksPath") == ".githooks"
+
+
+def test_hook_files_are_executable():
+    for name in ("pre-commit", "commit-msg", "pre-push"):
+        assert os.access(ROOT / ".githooks" / name, os.X_OK)
+    assert os.access(ROOT / "scripts" / "install-hooks", os.X_OK)
+
+
+def test_pre_commit_rejects_a_staged_term(hooked):
+    hooked.write("a.txt", "work for acme\n")
+    hooked.git("add", "a.txt")
+    result = try_commit(hooked, "feat: clean message")
+    assert result.returncode != 0
+    assert "a.txt:1: term #1" in output(result)
+    assert "acme" not in output(result).lower()
+    assert hooked.git("log", "--oneline").count("\n") == 1  # only init + tooling
+
+
+def test_commit_msg_rejects_a_term_in_the_message(hooked):
+    hooked.write("a.txt", "clean\n")
+    hooked.git("add", "a.txt")
+    result = try_commit(hooked, "feat: for globex")
+    assert result.returncode != 0
+    assert "message: term #2" in output(result)
+    assert "globex" not in output(result).lower()
+
+
+def test_clean_commit_passes_the_hooks(hooked):
+    hooked.write("a.txt", "clean\n")
+    hooked.git("add", "a.txt")
+    assert try_commit(hooked, "feat: fine").returncode == 0
+
+
+def test_pre_commit_warns_when_gitleaks_is_missing(hooked):
+    hooked.write("a.txt", "clean\n")
+    hooked.git("add", "a.txt")
+    env = hooked.env(TERMS)
+    env["PATH"] = os.pathsep.join(
+        p for p in env["PATH"].split(os.pathsep) if not (Path(p) / "gitleaks").exists()
+    )
+    result = subprocess.run(
+        ["git", "commit", "-q", "-m", "feat: fine"],
+        cwd=hooked.root,
+        env=env,
+        capture_output=True,
+        text=True,
+    )
+    assert result.returncode == 0
+    assert "gitleaks not installed" in output(result)
+
+
+def test_pre_push_rejects_a_term_in_history(hooked):
+    hooked.write("a.txt", "acme\n")
+    hooked.git("add", "a.txt")
+    hooked.git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "feat: leak")
+    remote = hooked.root.parent / "remote.git"
+    hooked.git("init", "-q", "--bare", str(remote))
+    result = subprocess.run(
+        ["git", "push", "-q", str(remote), "main"],
+        cwd=hooked.root,
+        env=hooked.env(TERMS),
+        capture_output=True,
+        text=True,
+    )
+    assert result.returncode != 0
+    assert "term #1" in output(result)
+    assert "acme" not in output(result).lower()
