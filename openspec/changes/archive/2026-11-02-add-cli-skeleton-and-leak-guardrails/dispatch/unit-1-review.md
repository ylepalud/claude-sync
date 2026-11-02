# Unit 1 review

## Done well
Small, clear modules. Stdlib only. `main` always returns an int. Epilog rendering is shared by the top-level and subcommand parsers. `help X` reuses the real subparser, so equality with `X --help` holds by construction. ExitCode carries descriptions. Tests assert real output, not mocks. Mutation run: 29 mutants across cli, registry, context, help, version, exit_codes and __init__; 27 killed. No U+2014 and no non-neutral name outside openspec/. install.sh is executable and matches 1.5. `denylist.txt` is in .gitignore.

## Part 1: Spec compliance
All requirements and scenarios in scope are met. The dry-run and no-TTY scenarios have no command to exercise yet; Context unit tests cover confirm. Not verifiable here: the `uv tool install` run (2.7) and the install.sh network path.

Judgments:
(a) Letting non-ClaudeSyncError exceptions show a raw traceback complies. The design maps only ClaudeSyncError. Python's own traceback is an acceptable default, not a spec gap. Optional follow-up, not required.
(b) `help --json` showing top-level usage still gives exit 2 with a usage message on stderr. The spec only requires that help is exempt from --json. Acceptable.
(c) The lazy `registry.__getattr__` is justified only by the cycle (commands import Command from registry; registry imports commands). It is a bit magic. Simpler: move `Command` (and render_epilog) to a leaf module, and have registry import the commands eagerly. Not required.
(d) No em dash, no non-neutral names.

## Part 2: Code quality

### Critical
None.

### Important
1. Surviving mutant, `src/claude_sync/registry.py:14` (COMMAND_MODULES order). Swapping to ("help", "version") passes the whole suite. The spec requires `help --all` in a stable order, and the report claims test_help_all_is_in_registry_order, but that test monkeypatches COMMANDS with fakes, so the real order is unpinned. Add a test asserting `[c.name for c in registry.COMMANDS] == ["version", "help"]`, or assert real `help --all` section order.
2. Surviving mutant, `src/claude_sync/commands/help.py:~38` (rule-line separator). Replacing `f"\n{RULE}\n\n"` with `"\n"` passes everything. Brief 2.5 requires a rule line between blocks. Add a test that the separator appears (count of RULE lines == number of commands).

### Minor
- `src/claude_sync/registry.py:62` lazy `__getattr__` return annotation and the cycle workaround. [trivial]
- `src/claude_sync/cli.py:~50` `_report` prints a traceback via `traceback.print_exc()` before the error line; fine, but ordering is stderr noise. [trivial]
- `src/claude_sync/commands/help.py:~15` uses the private `parser._actions` and `argparse._SubParsersAction`. [trivial]
- `src/claude_sync/exit_codes.py:4` ExitCode.description is annotated on an IntEnum, with `__new__` return type quoted; works. [trivial]
- Report says the 2.1 tests were seen failing, but conftest, context and cli were written before their tests (self-disclosed). [trivial]

## Docs/comments
No stale docs or docstrings. README untouched per brief.

Spec compliance: ✅ (2.7 install step ⚠️ unverified here)
Issues: Critical 0, Important 2, Minor 5 (all trivial)
Task quality: Needs fixes
