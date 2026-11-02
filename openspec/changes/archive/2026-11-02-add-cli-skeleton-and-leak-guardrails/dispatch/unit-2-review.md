# Unit 2 review: leak guard

## Done well
- Output is built only from location + term index; git stderr captured; exceptions replaced by a fixed message (verified: missing message file and run outside a repo print only the fixed line).
- Mutation run (21 mutants on scripts/check-denylist: empty/missing denylist, comments, case, binary, path placeholder in tree/staged/history, hunk number, in_hunk, `--all` on both log calls, short sha, tracked-denylist refusal, stderr capture, exception catch, exit code, required target, label, message file): all killed. Script restored byte-identical (cmp).
- Workflow: `${{ }}` for PR title/body only in step `env:`; `DENYLIST` secret in job `env:`; empty-secret check is the first step (before checkout); both action SHAs match the brief; `permissions: contents: read`; `test` has no name.
- Exit code 4 is documented in --help (scripts/check-denylist:160-165), consistent.
- Root commit is covered (`git log -p` shows root diff).

## Part 1: spec compliance
- ✅ Fail-closed, comments, findings format, scan targets, hooks, CI structure.
- ⚠️ CI runtime not verifiable here: `sha256sum -c --ignore-missing` (ci.yml:54) exit status when nothing matches depends on the coreutils version; checksums file comes from the same origin as the tarball (as designed). actionlint reported clean by implementer, not re-run.
- ❌ "every commit reachable in the history" is not met for merge commits (see Important 1).

## Issues
### Critical
none

### Important
1. scripts/check-denylist:120 `git log --all -p` prints no diff for merge commits, so a term introduced only in a merge (conflict resolution or evil merge) then removed later is never reported. Demonstrated in a temp repo with term `globex`: merge adds `m`, next commit removes it, `--history` exits 0 with no finding. Fix: add `--diff-merges=first-parent` (or `-m`) to the log call and a test.
2. scripts/check-denylist:120-127 author/committer name and e-mail are never scanned. Demonstrated: author e-mail `t@acme.example`, DENYLIST=acme, `--history` exits 0. The spec lists "work e-mail" as a protected category and an author e-mail is the most common way one reaches a public repo. Add `%an %ae %cn %ce` to the message log format (location `<sha>: author`) with a test. (Gap exists in the binding design too; flag for the orchestrator.)

### Minor
- scripts/check-denylist:120-127 branch names, tag names and annotated tag messages are not scanned (`git branch globex-branch`, `git tag -a -m "globex tag"` exit 0). [trivial: out of the specified targets]
- scripts/check-denylist:70 `Path(name).read_bytes()` follows symlinks outside the repo for --tree. [trivial]
- scripts/check-denylist:229 an internal failure and a findings result share exit 1 (documented at line 162). [trivial]
- tests/test_check_denylist.py: no dedicated test for `Binary files differ` in diffs (report admits it). [trivial]

## Spec compliance: ✅ except history merges (❌), CI runtime ⚠️
Issues by severity: Critical 0, Important 2, Minor 4.

Task quality: Needs fixes
