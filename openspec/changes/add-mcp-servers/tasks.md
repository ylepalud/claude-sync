## 1. Manifest and secrets

- [x] 1.1 Extend `src/claude_sync/manifest.py` with `McpServer` per design and the `mcp-servers` spec (transport rules, references `env:`/`keychain:`/`value:` for env and headers, `${NAME}` allowed in command/args/url, unique names). Tests in `tests/test_manifest.py`: round trip; each invalid case naming the file, including the spec's "Bare value refused"; manifests without MCP tables unchanged.
- [x] 1.2 Create `tests/fake_security.py` (executable stub answering `find-generic-password -s <service> [-a <account>] -w` from `$HOME/.fake-keychain.json`, exit 44 with the real tool's message when absent), extend the autouse guard to block the real `security`, add a `fake_keychain` fixture. Create `src/claude_sync/secrets.py` per design. Tests in `tests/test_secrets.py`: each reference kind, missing item (exit 44) and other failures (exit 51) as errors naming the reference without the tool output, no value in any error message.

## 2. MCP logic

- [x] 2.1 Teach `tests/fake_claude.py` `mcp add-json` and `mcp remove` per design (with tests in `tests/test_fake_claude.py` or the existing claude CLI tests).
- [x] 2.2 Create `src/claude_sync/mcp.py` with `observe`, `desired`, `diff`, `plan`, `import_servers` per design. Tests in `tests/test_mcp.py`: observe defaults and aliases; desired for env/value/keychain; each difference kind with field paths and no value in the output; plan adds, replaces (confirm only for http/sse), prunes (confirm), masks secrets in descriptions; import turns literals into `env:<SERVER>_<KEY>`, keeps `${NAME}` as `env:NAME`, keeps previous references that still produce the observed value (keychain included), and returns the exports list.

## 3. Commands

- [x] 3.1 `src/claude_sync/converge.py` and `commands/apply.py`: `mcp` parameter, MCP plan and resolution before any action, MCP actions after skills, confirmation and dry run with the masked `shown` form, a failing MCP action raising an error with the masked command. Tests in `tests/test_cmd_apply.py`: converge one stdio and one http server then status exits 0; replacing the http server needs confirmation (exit 3 without TTY), replacing a stdio one does not; prune skips unmanaged servers; a missing Keychain item stops apply before plugins or skills change; a failing `mcp add-json` (fake `fail`) with a Keychain value: exit 1 and the value absent from stdout and stderr; dry run and confirmation text masked.
- [x] 3.2 `commands/status.py`: MCP differences in text and `--json` (field paths, never values; unmanaged as information). Tests in `tests/test_cmd_status.py`.
- [x] 3.3 `build_manifest` and `commands/import_cmd.py`: servers imported with exports printed; `init` and `uninstall` pass `mcp=False`. Tests in `tests/test_cmd_import.py`, `tests/test_cmd_init.py`, `tests/test_cmd_uninstall.py`: import of a literal prints the export and writes no value; `Bearer ${T}` imported as `value:`; apply then import then status is stable; init leaves `.claude.json` servers untouched (spec scenario); uninstall never adds, replaces or removes a server.
- [x] 3.4 `--help` of import, status and apply mention MCP servers and the reference kinds.

## 4. Documentation

- [ ] 4.1 README: an "MCP servers" section (table, reference kinds and where each value ends up, placeholders expanded by Claude Code at run time, import of literals into `env:` references with the export list, replacement and OAuth loss, prune, init/uninstall leave servers alone, values never printed) and roadmap 5b done.
