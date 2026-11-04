## 1. Manifest and checks

- [ ] 1.1 Extend `src/claude_sync/manifest.py` with `Tool` per design and the `tool-requirements` spec. Tests in `tests/test_manifest.py`: round trip; invalid name, version, unknown recipe kind (spec scenario), empty recipe; manifests without tools unchanged.
- [ ] 1.2 Create the test stubs and guard per design: `tests/fake_tool.py` (prints the version configured in `$HOME/.fake-tools.json` for its own name, exit 127-like when absent), `tests/fake_manager.py` (one script installed as `brew`, `npm`, `uv`, `cargo`, logging argv to `$HOME/.fake-managers.log` and making the tool present at a configured version), fixtures to install them on a PATH used by the code under test, and the guard blocking the real managers for code under test. Test the guard in `tests/test_isolation.py`.
- [ ] 1.3 Create `src/claude_sync/tools.py` per design. Tests in `tests/test_tools.py`: `parse_version` on `rtk 0.20.0`, `gh version 2.101.0 (2026-09-15)`, `uv 0.11.7 (Homebrew ...)`, `1.12.0`, `jq-1.6`, and no number; `check` ok, missing (not found, non-zero exit, timeout), too old, unreadable version with a minimum; `merge` highest minimum, first-profile recipe, conflicts; `install_command`/`upgrade_command` for every kind; `all_profiles`.

## 2. Commands

- [ ] 2.1 `src/claude_sync/commands/doctor.py` per spec: listing in text and `--json` (`{"tools": [...], "conflicts": [...], "ok": bool}`), exit 0/4; `--fix` with one confirmation listing the commands (exit 3 without TTY/`--yes`), `--dry-run`, stop on first failure (exit 1 with command and stderr), recheck after; tools without recipe only reported. Register it. Tests in `tests/test_cmd_doctor.py` for every spec scenario and the dry run.
- [ ] 2.2 `converge.py`: tool pre-check before any plan; tests in `tests/test_cmd_apply.py` (spec scenario "Apply refuses": nothing changes, `doctor --fix` hint) and a passing case.
- [ ] 2.3 `--help` of doctor complete (description, examples, exit codes, neutral names) and apply's help mentions the tool check.

## 3. Documentation

- [ ] 3.1 README: a "Tools" section (table, version parsing and `check`, recipes and what `--fix` runs for install and upgrade, merge across profiles and conflicts, apply's pre-check, `script:` runs shell after confirmation) and the roadmap marked complete.
