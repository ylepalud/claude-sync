# Unit 3 brief: README

Repository: /Users/yveslepalud/Dev/perso/my-projects/claude-sync. Only file you edit: `README.md` (currently a short stub; keep its intro and License section, rewrite the rest).

Task 4.1 (from tasks.md):
- [ ] 4.1 README: install (`uv tool install git+https://github.com/ylepalud/claude-sync`, and the clone alternative `git clone` + `./install.sh` with `CLAUDE_SYNC_SOURCE=.`), usage (`claude-sync help --all`), development (`uv sync`, `uv run pytest`, `scripts/install-hooks`), leak guard (where the denylist lives, that it is never committed, that CI needs the `DENYLIST` secret, that findings print term numbers only).

Facts to read before writing (do not invent behaviour; read these files):
- `install.sh`, `pyproject.toml`, `src/claude_sync/cli.py`, `src/claude_sync/commands/*.py`, `src/claude_sync/exit_codes.py`
- `scripts/check-denylist --help` (run it with `env DENYLIST=x python3 scripts/check-denylist --help`), `scripts/install-hooks`, `.githooks/*`, `.github/workflows/ci.yml`
- `openspec/changes/add-cli-skeleton-and-leak-guardrails/design.md` for the roadmap (steps 2 to 5 are not built yet: say so as a short "Roadmap" list, marking only step 1 as done).

Rules:
- Audience: the maintainer and an LLM agent reading the repo. Short, precise, runnable commands. Mention the CLI conventions (every command has --help with examples and exit codes; read commands --json; mutating commands --dry-run/--yes; refuses instead of prompting without a TTY) and list the exit codes table.
- Public repo: no employer, client or internal name; use `perso` / `work` / `~/Dev/work` if an example needs one.
- English, no em dash (U+2014). Do not mention any real denylist term. Never read `~/.config/claude-sync/denylist.txt`.
- Do not commit. Report to `openspec/changes/add-cli-skeleton-and-leak-guardrails/dispatch/unit-3-report.md` (what each section says and which file each claim was checked against).
