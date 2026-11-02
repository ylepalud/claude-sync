# Unit 2 report: leak guard

Status: DONE_WITH_CONCERNS (trivial only)

## Implemented
- scripts/check-denylist (stdlib, executable): --tree, --staged, --history, --message-file, --text, full --help. Exit 0/1/2/3, and 4 for a tracked denylist.txt (refusal). Git stderr captured; any unexpected exception prints a fixed message and exits 1.
- .githooks/{pre-commit,commit-msg,pre-push}, scripts/install-hooks (run in this repo: core.hooksPath=.githooks is now set here).
- .github/workflows/ci.yml per design (SHAs pinned, gitleaks binary verified with sha256sum). CI is config: no test; checked with actionlint (clean).
- tests/test_check_denylist.py: 35 tests, TDD slice by slice.

## Branch -> test
- empty DENYLIST exit 3: test_empty_denylist_fails_closed; missing file: test_missing_denylist_file_fails_closed; home fallback: test_denylist_read_from_home_file_when_env_unset
- comments/blank ignored, numbering: test_comments_and_blank_lines_are_ignored_in_numbering
- case-insensitive: test_matching_is_case_insensitive
- binary skipped: test_binary_file_is_skipped
- tree content/path/placeholder: test_tree_finding_*, test_term_in_a_path_*, test_content_finding_in_a_matching_path_*
- staged hunk numbers, removed/unstaged ignored, path, content in matching path: four test_staged_* tests
- history add-then-remove, path, message, all branches, clean: test_history_*
- message-file, text, combined, no target (exit 2), tracked denylist.txt refusal, fixed failure message, --help: matching tests
- hooks: install-hooks, executable bits, pre-commit reject, commit-msg reject, clean pass, gitleaks-missing warning, pre-push reject
- Binary "Binary files differ" in diffs: no hunk lines are produced so nothing is scanned (covered only structurally, no dedicated test) [trivial]

## Docs
Nothing described the old behaviour; README untouched as instructed. .gitignore already lists denylist.txt.

## Commands
- `uv run pytest`: 72 passed; `uv run ruff check`: clean; `uv run ruff format --check`: clean; `uvx --from actionlint-py actionlint .github/workflows/ci.yml`: exit 0.
- 3.3 proof in a throwaway temp repo with DENYLIST=acme: commit rejected, output `f.txt:1: term #1`, exit 1, no commit created.

## Files
.githooks/pre-commit, .githooks/commit-msg, .githooks/pre-push, scripts/check-denylist, scripts/install-hooks, .github/workflows/ci.yml, tests/test_check_denylist.py (+ this report)

## Concerns
- [trivial] Hooks are now active in this repo; with no denylist they fail closed (exit 3), by design.
- [trivial] In history, `path #k` is the position of the file within that commit's diff; in --tree it is the position in git ls-files.
- [trivial] Overbuild check: none beyond the brief; exit code 4 for the refusal is my choice (brief says non-zero).
