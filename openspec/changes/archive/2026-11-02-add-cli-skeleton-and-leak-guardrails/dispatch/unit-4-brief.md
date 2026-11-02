# Unit 4 brief: round 2 hardening

Repository: /Users/yveslepalud/Dev/perso/my-projects/claude-sync. Units 1-3 are committed (CLI frame in src/claude_sync/, scanner scripts/check-denylist with tests in tests/test_check_denylist.py, README.md). Files you may touch: src/claude_sync/cli.py, tests/test_cli.py, scripts/check-denylist, tests/test_check_denylist.py, README.md.

Non-negotiables: public repo, fake terms `acme`/`globex` only; never read ~/.config/claude-sync/denylist.txt; English, no em dash (U+2014); the scanner never prints a term, a matching line or a path/ref name containing a term; stdlib only.

Seams: `claude_sync.cli.main(argv)` with a fake command monkeypatched into `registry.COMMANDS` (see existing tests in tests/test_cli.py for the `fake(...)` helper pattern); `scripts/check-denylist` via subprocess in the temp repo fixture of tests/test_check_denylist.py.

## Tasks

## 5. Round 2 hardening (decided 2026-11-02)

- [ ] 5.1 In `src/claude_sync/cli.py` `main`, catch any other `Exception` after `ClaudeSyncError`: print `claude-sync: error: internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details` on stderr (traceback first only when `CLAUDE_SYNC_DEBUG=1`, same as `_report`) and return 1. Test in `tests/test_cli.py` with a fake command raising `RuntimeError("secret detail")`: exit 1, the fixed message on stderr, neither `Traceback` nor `secret detail` in stderr; with `CLAUDE_SYNC_DEBUG=1` the traceback appears.
- [ ] 5.2 In `scripts/check-denylist`, map unexpected internal failures to exit 5 (findings stay 1), update the `--help` exit codes and the existing test `test_unexpected_failure_prints_a_fixed_message_without_git_output` to expect 5. Update README's mention if any.
- [ ] 5.3 In `scripts/check-denylist` `--history`, also scan `git for-each-ref --format=%(refname)%00%(contents)%00`: each ref name reported as `ref #<k>` (1-based position in that output, the name never printed), each non-empty annotated tag message as `ref #<k>: tag message`. Tests: a branch named `feat/globex-thing` gives `ref #<k>: term #2` with `globex` absent from output; an annotated tag `-m "for Acme"` gives `ref #<k>: tag message: term #1`; a clean repo still exits 0. Add the two locations to the `--help` Locations table and to README's leak-guard list.
- [ ] 5.4 In `scripts/check-denylist` `--tree`, for a tracked path that is a symlink (`os.path.islink`), scan `os.readlink(path)` as text at location `<path>:1` (or `path #k` rules unchanged for the path itself) and never open the target. Test: a symlink `link.txt -> /tmp/<tmp>/outside.txt` whose target file contains `acme` and whose target path is clean gives exit 0; a symlink whose target path contains `globex` gives a finding.


## Binding design excerpts (design.md)

- Ref names and tag messages: `--history` also scans `git for-each-ref --format=%(refname)%00%(contents)%00` over every ref: the name is reported as `ref #<k>`, an annotated tag's message as `ref #<k>: tag message`.
- Symlinks: `--tree` reads a tracked symlink with `os.readlink` and scans the target path as text, never the pointed-to file.
- Uncaught exceptions in the scanner print a fixed message and exit 5 (distinct from findings, 1) without a traceback.
- CLI: any non-ClaudeSyncError exception maps to 1 with `internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details`; tracebacks only with CLAUDE_SYNC_DEBUG=1.
