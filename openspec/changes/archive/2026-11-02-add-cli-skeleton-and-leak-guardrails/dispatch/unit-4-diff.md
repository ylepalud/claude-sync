diff --git a/README.md b/README.md
index 5a18465..ff05cd0 100644
--- a/README.md
+++ b/README.md
@@ -92,7 +92,8 @@ private denylist from reaching it.
   message, `pre-push` scans the full history.
 - CI needs a repository secret named `DENYLIST` holding the terms; the
   `leak-guard` job fails when it is missing or empty. It scans the tree, the
-  history, commit messages and author identities, the pull request title
+  history, commit messages, author identities, branch and tag names, annotated
+  tag messages, the pull request title
   and body, and runs
   `gitleaks` on the full history.
 
diff --git a/scripts/check-denylist b/scripts/check-denylist
index fcc2ef7..1cb2faa 100755
--- a/scripts/check-denylist
+++ b/scripts/check-denylist
@@ -11,6 +11,7 @@ from pathlib import Path
 EXIT_FINDINGS = 1
 EXIT_NO_TERMS = 3
 EXIT_REFUSED = 4
+EXIT_INTERNAL = 5
 
 
 def load_terms() -> list[str]:
@@ -66,6 +67,10 @@ def scan_tree(scanner: Scanner) -> None:
     for position, name in enumerate(names, 1):
         scanner.report(f"path #{position}", name)
         label = scanner.path_label(name, f"path #{position}")
+        if os.path.islink(name):
+            # Scan where the link points, never the pointed-to file.
+            scanner.scan_lines(f"{label}:", os.fsdecode(os.readlink(name)))
+            continue
         try:
             data = Path(name).read_bytes()
         except OSError:
@@ -130,6 +135,18 @@ def scan_history(scanner: Scanner) -> None:
         short = sha.strip()[:7]
         scanner.report(f"{short}: identity", identity)
         scanner.report(f"{short}: message", body)
+    scan_refs(scanner)
+
+
+def scan_refs(scanner: Scanner) -> None:
+    # objecttype tells an annotated tag from a ref whose %(contents) is just a commit message.
+    refs = git("for-each-ref", "--format=%(refname)%00%(objecttype)%00%(contents)%00")
+    fields = refs.decode("utf-8", "replace").split("\0")
+    triples = zip(fields[0::3], fields[1::3], fields[2::3], strict=False)
+    for position, (name, kind, contents) in enumerate(triples, 1):
+        scanner.report(f"ref #{position}", name.strip())
+        if kind == "tag" and contents.strip():
+            scanner.report(f"ref #{position}: tag message", contents)
 
 
 def scan_staged(scanner: Scanner) -> None:
@@ -151,6 +168,8 @@ Locations:
   <sha>:<path>:<line>      history, sha is the 7-character commit id
   <sha>: message           a commit message
   <sha>: identity          the author or committer name or e-mail of a commit
+  ref #<k>                 a branch or tag name (k = position in git for-each-ref)
+  ref #<k>: tag message    the message of an annotated tag
   message / <label>        --message-file / --text
 
 Terms come from the DENYLIST environment variable when it is set (even empty),
@@ -165,10 +184,11 @@ Examples:
 
 Exit codes:
   0  clean
-  1  findings, or an unexpected failure
+  1  findings
   2  usage error
   3  denylist is empty or missing
   4  a tracked file is named denylist.txt (refused)
+  5  unexpected internal failure (details withheld)
 """
 
 
@@ -232,7 +252,7 @@ def main() -> int:
     except Exception:
         # Never show the exception: it could carry file content or git output.
         print("scan failed (details withheld to keep the denylist private)", file=sys.stderr)
-        return EXIT_FINDINGS
+        return EXIT_INTERNAL
 
 
 if __name__ == "__main__":
diff --git a/src/claude_sync/cli.py b/src/claude_sync/cli.py
index 0cba208..a319479 100644
--- a/src/claude_sync/cli.py
+++ b/src/claude_sync/cli.py
@@ -55,9 +55,12 @@ def main(argv: list[str] | None = None) -> int:
     except ClaudeSyncError as e:
         _report(e)
         return int(ExitCode.ERROR)
+    except Exception:
+        _report("internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details")
+        return int(ExitCode.ERROR)
 
 
-def _report(error: ClaudeSyncError) -> None:
+def _report(error: ClaudeSyncError | str) -> None:
     if os.environ.get("CLAUDE_SYNC_DEBUG") == "1":
         traceback.print_exc()
     print(f"claude-sync: error: {error}", file=sys.stderr)
diff --git a/tests/test_check_denylist.py b/tests/test_check_denylist.py
index 8fa2908..f5e0867 100644
--- a/tests/test_check_denylist.py
+++ b/tests/test_check_denylist.py
@@ -273,10 +273,50 @@ def test_history_scans_author_and_committer_identities(repo):
     assert "acme" not in output(result).lower()
 
 
+def ref_position(repo, refname: str) -> int:
+    refs = repo.git("for-each-ref", "--format=%(refname)").splitlines()
+    return refs.index(refname) + 1
+
+
+def test_history_reports_a_ref_name_by_position_without_the_name(repo):
+    repo.git("branch", "feat/globex-thing")
+    k = ref_position(repo, "refs/heads/feat/globex-thing")
+    result = repo.scan("--history")
+    assert result.returncode == 1
+    assert f"ref #{k}: term #2" in result.stdout
+    assert "globex" not in output(result).lower()
+
+
+def test_history_reports_an_annotated_tag_message(repo):
+    repo.git("tag", "-a", "v1", "-m", "for Acme")
+    k = ref_position(repo, "refs/tags/v1")
+    result = repo.scan("--history")
+    assert result.returncode == 1
+    assert f"ref #{k}: tag message: term #1" in result.stdout
+    assert "acme" not in output(result).lower()
+
+
 def test_history_of_a_clean_repo_exits_zero(repo):
     assert repo.scan("--history").returncode == 0
 
 
+def test_tree_scans_a_symlink_target_path_not_the_pointed_file(repo):
+    outside = repo.root.parent / "outside.txt"
+    outside.write_text("acme\n")
+    (repo.root / "link.txt").symlink_to(outside)
+    repo.commit()
+    assert repo.scan("--tree").returncode == 0
+
+
+def test_tree_reports_a_term_in_a_symlink_target_path(repo):
+    (repo.root / "link.txt").symlink_to("/somewhere/globex/file.txt")
+    repo.commit()
+    result = repo.scan("--tree")
+    assert result.returncode == 1
+    assert "link.txt:1: term #2" in result.stdout
+    assert "globex" not in output(result).lower()
+
+
 def test_message_file_is_reported_as_message(repo):
     msg = repo.root.parent / "MSG"
     msg.write_text("feat: for globex\n")
@@ -336,7 +376,7 @@ def test_unexpected_failure_prints_a_fixed_message_without_git_output(tmp_path,
         capture_output=True,
         text=True,
     )
-    assert result.returncode == 1
+    assert result.returncode == 5
     assert "Traceback" not in output(result)
     assert "fatal" not in output(result)
     assert "scan failed" in output(result)
diff --git a/tests/test_cli.py b/tests/test_cli.py
index bde43c9..4889e99 100644
--- a/tests/test_cli.py
+++ b/tests/test_cli.py
@@ -91,3 +91,40 @@ def test_help_rejects_json(capsys):
     code, _, err = run(capsys, "help", "--json")
     assert code == 2
     assert "usage: claude-sync" in err and "--json" in err
+
+
+def _install_failing_command(monkeypatch):
+    def boom(args, ctx):
+        raise RuntimeError("secret detail")
+
+    fake = registry.Command(
+        name="boom",
+        summary="fails",
+        description="fails",
+        examples=[],
+        exit_codes=[],
+        kind="doc",
+        configure=lambda parser: None,
+        run=boom,
+    )
+    monkeypatch.setattr(registry, "COMMANDS", [*registry.COMMANDS, fake])
+
+
+def test_unexpected_exception_prints_a_fixed_message_and_exits_1(capsys, monkeypatch):
+    monkeypatch.delenv("CLAUDE_SYNC_DEBUG", raising=False)
+    _install_failing_command(monkeypatch)
+    code, _, err = run(capsys, "boom")
+    assert code == 1
+    assert err == (
+        "claude-sync: error: internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details\n"
+    )
+    assert "Traceback" not in err and "secret detail" not in err
+
+
+def test_unexpected_exception_shows_the_traceback_in_debug_mode(capsys, monkeypatch):
+    monkeypatch.setenv("CLAUDE_SYNC_DEBUG", "1")
+    _install_failing_command(monkeypatch)
+    code, _, err = run(capsys, "boom")
+    assert code == 1
+    assert "Traceback" in err
+    assert "claude-sync: error: internal error" in err
