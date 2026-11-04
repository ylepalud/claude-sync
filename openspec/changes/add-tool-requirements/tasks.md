## 1. Manifest and checks

- [x] 1.1 Extend `src/claude_sync/manifest.py` with `Tool` per design and the `tool-requirements` spec. Tests in `tests/test_manifest.py`: round trip; invalid name, version, unknown recipe kind (spec scenario), empty recipe, a `check` whose first word is not the name, a `script:` with a newline or a control character, a scoped npm package (`npm:@scope/pkg`) accepted; manifests without tools unchanged.
- [x] 1.2 Create the test stubs and guard per design: `tests/fake_tool.py` (prints the version configured in `$HOME/.fake-tools.json` for its own name, exit 127-like when absent), `tests/fake_manager.py` (one script installed as `brew`, `npm`, `uv`, `cargo`, logging argv to `$HOME/.fake-managers.log` and making the tool present at a configured version), fixtures to install them on a PATH used by the code under test, and the guard blocking the real managers for code under test. Test the guard in `tests/test_isolation.py`.
- [x] 1.3 Create `src/claude_sync/tools.py` per design. Tests in `tests/test_tools.py`: `parse_version` on `rtk 0.20.0`, `gh version 2.101.0 (2026-09-15)`, `uv 0.11.7 (Homebrew ...)`, `1.12.0`, `jq-1.6`, and no number; `check` ok, missing (not found, non-zero exit, timeout), too old, unreadable version with a minimum; `merge` highest minimum, check and recipe per field from the first profile, conflicts; `fix_command` for every kind (brew chooses install or upgrade from `brew list`), resolved absolute manager paths; resolved tool path and the shadowing binary; `all_profiles`.

## 2. Commands

- [x] 2.1 `src/claude_sync/commands/doctor.py` per spec and design (kind `mutate` plus `--json`): listing in text and `--json`, exit 0/4; `--fix` with one confirmation listing the commands with absolute manager paths (exit 3 without TTY/`--yes`), `script:` only with a TTY confirmation even with `--yes`, no prompt when nothing to run, `--dry-run`, `--fix --json` without `--yes` exit 2, stop on first failure (exit 1 with command and stderr), recheck after with exit 0/4. Register it. Tests in `tests/test_cmd_doctor.py` for every spec scenario plus exit 3 without TTY, first-failure stop, the upgrade path, the JSON shape and the dry run.
- [x] 2.2 `commands/apply.py`: tool pre-check before calling converge; `converge.build_manifest` keeps `previous.tools`. Tests: `tests/test_cmd_apply.py` (spec scenario "Apply refuses": nothing changes, `doctor --fix` hint; a passing case), `tests/test_cmd_import.py` (spec scenario "Tools survive import"), and init/uninstall unaffected by a missing tool.
- [x] 2.3 `--help` of doctor complete (description, examples, exit codes, neutral names) and apply's help mentions the tool check.

## 3. Documentation

- [x] 3.1 README: a "Tools" section (table, version parsing and `check`, recipes and what `--fix` runs for install and upgrade, merge across profiles and conflicts, apply's pre-check, `script:` runs shell after confirmation) and the roadmap marked complete.
