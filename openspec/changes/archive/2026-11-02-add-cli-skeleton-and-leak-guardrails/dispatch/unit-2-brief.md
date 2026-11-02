# Unit 2 brief: leak guard (scanner, git hooks, CI)

Repository: /Users/yveslepalud/Dev/perso/my-projects/claude-sync. Unit 1 already built the Python package (`src/claude_sync/`, `tests/`, `pyproject.toml` with ruff `extend-include = ["scripts/check-denylist"]`, `tests/conftest.py` autouse fixture isolating HOME, unsetting DENYLIST and pointing GIT_CONFIG_GLOBAL/SYSTEM to /dev/null). Do not modify `src/claude_sync/` or README.md.

Non-negotiables (from CLAUDE.md):
- Public repo: never write an employer, client, internal domain or work e-mail anywhere. Tests use the fake terms `acme` and `globex` only.
- Never read the real `~/.config/claude-sync/denylist.txt` from tests or print its content anywhere. Do not run the scanner against the real denylist; the orchestrator does that.
- English only, no em dash (U+2014).
- The scanner is stdlib-only Python.

Seams: the executable `scripts/check-denylist` driven through `subprocess` (exit code + stdout/stderr) inside a temporary git repository; hooks driven by real `git commit` in a temporary repo with `core.hooksPath` set; CI is config (no test, say so).

Note for tests running git in a temp repo: conftest sets GIT_CONFIG_GLOBAL=/dev/null, so set `user.name`/`user.email` locally in the temp repo (`git -c` or `git config`), and pass `env` explicitly to subprocess including `DENYLIST` when needed. When `DENYLIST` is absent the scanner reads `$HOME/.config/claude-sync/denylist.txt`; HOME is a tmp_path, so tests may create that file there.

Task 3.3: install the hooks in this repository (`scripts/install-hooks`) and prove a commit is rejected using a throwaway temporary repo (not this one) so nothing is committed here.

GitHub Actions note: `${{ }}` expressions for PR title/body must only appear in `env:`, never inline in `run:`.

## Tasks (implement exactly these checkboxes)

## 3. Leak guard (`leak-guard`)

- [ ] 3.1 Write failing tests in `tests/test_check_denylist.py` that run `scripts/check-denylist` with `subprocess` inside a temporary git repo (`git init` in `tmp_path`, local `user.name`/`user.email` set, `HOME` pointed at `tmp_path`): empty `DENYLIST` exits non-zero with `denylist is empty or missing`; comments and blank lines ignored; a term in `README.md` line 3 gives `README.md:3: term #2` and the output does not contain the term; a term in a file path is reported; a term added then removed is found by `--history` with the commit short sha (`<sha>:path #k:<line>`); a term in a commit message gives `<sha>: message`; `--staged` reports a staged added line as `<path>:<line>` with the line number from the hunk header; `--message-file` gives `message`, `--text pr-body` gives `pr-body`; matching is case-insensitive; a binary file is skipped; a clean repo exits 0. Exit codes: 3 for an empty or missing denylist, 1 for findings, non-zero refusal when a tracked file is named `denylist.txt`. A term in a file path gives `path #<k>: term #<n>` and the path is absent from the output. No output of any test ever contains the term. Use fake terms like `acme` and `globex` only.
- [ ] 3.2 Implement `scripts/check-denylist` (executable, `#!/usr/bin/env python3`, stdlib only) per design: options `--tree`, `--staged`, `--history`, `--message-file PATH`, `--text LABEL` (stdin), at least one required; git commands exactly as in design.md; terms from `DENYLIST` env when set (even empty) else `~/.config/claude-sync/denylist.txt`; exit 3 when empty or missing, 1 on findings, 0 when clean; output `<location>: term #<n>` with locations exactly as in design.md, never a path that matches; capture git stderr and never echo it; catch unexpected exceptions with a fixed message and exit 1; refuse to run when a tracked file is named `denylist.txt`; full `--help` with examples and exit codes.
- [ ] 3.3 Create `.githooks/pre-commit` (`scripts/check-denylist --staged`, then `gitleaks git --staged --redact` if `command -v gitleaks`, else a one-line warning), `.githooks/commit-msg` (`scripts/check-denylist --message-file "$1"`) and `.githooks/pre-push` (`scripts/check-denylist --history`), all executable, and `scripts/install-hooks` running `git config core.hooksPath .githooks`. Run it in this repo and check a commit with the term `acme` in a temporary `DENYLIST` is rejected, then reset.
- [ ] 3.4 Create `.github/workflows/ci.yml` per design: triggers `push` (all branches) and `pull_request` with `types: [opened, synchronize, reopened, edited]`; `permissions: contents: read`; actions pinned to the SHAs in design.md; `test` job without `name:`, matrix `python-version: ["3.11", "3.13"]`, steps `uv sync`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`; `leak-guard` job with `fetch-depth: 0`, `DENYLIST: ${{ secrets.DENYLIST }}` in job `env`, a first step `test -n "$DENYLIST" || { echo "DENYLIST secret is missing or empty"; exit 1; }`, then `scripts/check-denylist --tree --history`, then on `pull_request` only `PR_TITLE: ${{ github.event.pull_request.title }}` and `PR_BODY: ${{ github.event.pull_request.body }}` in step `env` piped with `printf '%s' "$PR_TITLE" | scripts/check-denylist --text pr-title` (same for body), then download `gitleaks_8.30.1_linux_x64.tar.gz` and `gitleaks_8.30.1_checksums.txt` from the v8.30.1 release, `sha256sum -c --ignore-missing`, extract, and run `./gitleaks git --redact --log-opts=--all .`.



## Binding design

### Leak guard
- `scripts/check-denylist`: a stdlib Python script (not part of the package,
  it guards the repository, not the user's machine). Options:
  `--tree` (content and paths of `git ls-files -z`),
  `--staged` (added lines of `git diff --cached -U0 --no-color --no-ext-diff`,
  line numbers parsed from `@@ ... +<start>,<n> @@` hunk headers, and staged
  paths from `git diff --cached --name-only -z`),
  `--history` (added lines and paths of
  `git log --all -p -U0 --no-color --no-ext-diff --format=%x00commit %H`,
  and messages of `git log --all --format=%H%x00%B%x00`; the commit sha is
  what is reported, not blob shas),
  `--message-file PATH`, `--text LABEL` (reads stdin). Several may be
  combined. Binary content skipped (NUL byte in the first 8 KiB; `Binary
  files differ` lines in diffs).
- Locations: `<path>:<line>`; `path #<k>` when the path itself matches (the
  path is never printed, it would carry the term); `<short sha>:<path
  #k>:<line>`, `<short sha>: message`, `<short sha>: path #k` for history;
  `message` for `--message-file`; the label for `--text`.
- Terms: `DENYLIST` env var if set (even empty, so CI cannot silently fall
  back to a missing file), else `~/.config/claude-sync/denylist.txt`. Empty
  or missing: exit 3 with `denylist is empty or missing` (2 stays argparse's
  usage error). Findings: exit 1. Clean: 0.
- Error hygiene: git's stderr is captured and never echoed; uncaught
  exceptions print a fixed message and exit 1 without a traceback, so no
  error path can print file content.
- Output: `<location>: term #<n>`; never the term or the line. Rejected:
  printing the line, which would publish the denylist in CI logs.
- The denylist file itself is never in the repository; the script refuses
  to run if a tracked file is named `denylist.txt`.
- `.githooks/pre-commit` runs `--staged`, then `gitleaks git --staged
  --redact` when `gitleaks` is on `PATH` (a warning otherwise);
  `.githooks/commit-msg` runs `--message-file "$1"`; `.githooks/pre-push`
  runs `--history`, so a branch is checked before it becomes public even
  without a PR. `.gitignore` also lists `denylist.txt` as defence in depth. `scripts/install-hooks` sets
  `git config core.hooksPath .githooks`. Rejected: the `pre-commit`
  framework (extra tool to install for a two-hook need).

### CI (`.github/workflows/ci.yml`)
Triggers: `push` on every branch, `pull_request` with
`types: [opened, synchronize, reopened, edited]` (so an edited title or body
is rescanned). Actions pinned by commit SHA:
`actions/checkout` v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1`,
`astral-sh/setup-uv` v10.3.3 `68559e99cc807c1eb7e9238fd43a15bba460eec2`,
and the gitleaks **binary** v8.30.1 (`gitleaks_8.30.1_linux_x64.tar.gz`,
verified against `gitleaks_8.30.1_checksums.txt` with `sha256sum -c`).
Rejected: `gitleaks/gitleaks-action`, which on push and pull_request scans
only `base^..head`, not the full history.
`permissions: contents: read` at the top.
- `test` job, matrix Python 3.11 and 3.13: `uv sync`, `uv run ruff check`,
  `uv run ruff format --check`, `uv run pytest`.
- `leak-guard` job: checkout with `fetch-depth: 0`; fail if `DENYLIST` is
  empty; `scripts/check-denylist --tree --history`; on `pull_request`, pipe
  the title and the body (passed through `env:`, never interpolated into the
  script) into `--text pr-title` and `--text pr-body`; then
  `gitleaks git --redact --log-opts=--all .` over the full history.
- The `test` job has no `name:` so the matrix checks are named
  `test (3.11)` and `test (3.13)`.
- Branch protection on `main` after the first green run, through
  `PUT /repos/ylepalud/claude-sync/branches/main/protection` with
  `required_status_checks: {strict: true, contexts: [test (3.11), test (3.13),
  leak-guard]}`, `enforce_admins: true` (the owner cannot bypass),
  `required_pull_request_reviews: {required_approving_review_count: 0}`
  (single maintainer), `restrictions: null`, plus `allow_force_pushes: false`,
  `allow_deletions: false`.



## Spec this unit satisfies

## Purpose

Prevent any denylisted term (employer, client, internal domain, work e-mail)
or secret from reaching the public repository through files, history, commit
messages or pull requests.

## ADDED Requirements

### Requirement: Denylist source fails closed
The denylist scanner SHALL read terms from the `DENYLIST` environment variable
when set, otherwise from `~/.config/claude-sync/denylist.txt`, one term per
line, ignoring blank lines and lines starting with `#`, matching
case-insensitively. When no source exists or it holds no term, the scanner
SHALL fail with exit code 3 instead of reporting success. Findings exit with
code 1 and a clean scan with code 0. The scanner SHALL refuse to run when a
tracked file is named `denylist.txt`.

#### Scenario: Empty denylist
- **WHEN** the scanner runs with `DENYLIST` set to an empty string
- **THEN** it reports that the denylist is empty and exits with code 3

#### Scenario: Tracked denylist file
- **WHEN** a file named `denylist.txt` is tracked in the scanned repository
- **THEN** the scanner refuses to scan and exits with a non-zero code

#### Scenario: Comments ignored
- **WHEN** the denylist file holds `# note` and `acme`
- **THEN** only `acme` is used as a term

### Requirement: Findings never reveal the terms
A finding SHALL name the location and the 1-based index of the matching term
in the denylist, and SHALL NOT print the term, the matching line, or any path
that contains a term, so that public CI logs never disclose the denylist.
Locations are `<path>:<line>` for file content, `path #<k>` (1-based position
in the scanned path list) when the path itself matches, `<short commit sha>`
followed by `:<line>` or `message` or `path` for history, `message` for a
message file, and the caller's label for free text. Error messages SHALL never
echo file content or git output.

#### Scenario: Finding output
- **WHEN** line 3 of `README.md` contains the second denylist term
- **THEN** the output contains `README.md:3` and `term #2` and does not contain the term itself

#### Scenario: Term in a path
- **WHEN** a tracked file path contains the first denylist term
- **THEN** the output reports `path #<k>: term #1` and does not print the path

### Requirement: Scan targets
The scanner SHALL be able to scan, each selected by an option: tracked files
of the working tree including their paths, staged content, every blob and
every commit message reachable in the history, a commit message file, and a
free text passed on standard input labelled by the caller (used for PR title
and body).

#### Scenario: Leak in history only
- **WHEN** a term was added in an earlier commit and removed in a later one
- **THEN** a history scan reports the earlier commit and exits with a non-zero code

#### Scenario: Leak in staged content
- **WHEN** a staged change adds a line containing a term
- **THEN** the pre-commit hook rejects the commit

#### Scenario: Leak in a commit message
- **WHEN** a commit message being written contains a term
- **THEN** the commit-msg hook rejects the commit

#### Scenario: Clean repository
- **WHEN** no target contains any term
- **THEN** the scanner exits with code 0

### Requirement: Enforcement points
The repository SHALL ship git hooks that scan staged content (denylist, and
secrets when gitleaks is installed) before a commit, the message of each
commit, and the full history before a push. A CI pipeline SHALL, on every push
to any branch and on every pull request opened, updated or edited, scan the
tree, the full history, the commit messages and the pull request title and
body, run a secret scanner over the full history, and fail when the
`DENYLIST` secret is missing or empty.

#### Scenario: Missing secret in CI
- **WHEN** CI runs without the `DENYLIST` secret (for example on a pull request from a fork)
- **THEN** the leak-guard job fails

#### Scenario: Edited pull request description
- **WHEN** the title or body of an open pull request is edited
- **THEN** CI scans them again

