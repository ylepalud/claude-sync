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
