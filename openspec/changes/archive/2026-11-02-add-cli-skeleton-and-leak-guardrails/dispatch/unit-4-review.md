# Unit 4 review

## Done well
- Tests are behavioural (subprocess / main), assert absence of the term in output, and use fake terms only.
- The `%(objecttype)` addition is justified: without it a branch or lightweight tag, whose `%(contents)` is the tip commit message, would be reported as a duplicate "tag message". design.md:131-133 matches the code. Name and message are never printed; the symlink path is only `os.readlink`ed (scripts/check-denylist:70-73), never opened; the label falls back to `path #k` when the path holds a term.
- Mutation results (all restored, `cmp` identical): EXIT_INTERNAL, scan_refs call, ref-name report, islink branch, cli `except Exception`, cli debug gating were all killed by the named tests.

## Part 1: Spec compliance
- Missing: none.
- Extra: `%(objecttype)` field, documented in design.md and justified.
- Misunderstood: none.

## Part 2: Issues
### Important
- scripts/check-denylist:147: the `kind == "tag"` guard (the implementer's own addition) is untested. Mutants `if contents.strip():` and `if kind == "tag":` both survive (41 passed). No test has a branch or lightweight tag whose tip commit message holds a term (or is non-empty) and asserts no `ref #k: tag message` line. Add one, e.g. commit "for acme" on a branch plus a lightweight tag, and assert `tag message` is absent from stdout.

### Minor
- [trivial] README.md:95-97: re-wrapped list item leaves a short orphan line ("and body, and runs").

Docs: --help Locations/Exit codes, README leak-guard list and design.md are accurate.
Leak safety: no new path prints a term, ref name, tag message or symlink target.

Spec compliance: ✅ (5.1-5.4 implemented; one surviving mutant on the added guard)
Task quality: Needs fixes
