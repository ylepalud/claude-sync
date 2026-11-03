## Purpose

Declare the external skills a profile uses, pinned to a commit, and keep
their links in the profile in step with that declaration.

## ADDED Requirements

### Requirement: Skill tables
The profile manifest SHALL accept zero or more `[[skill_source]]` tables
with `name`, `source` (`github:<owner>/<repo>` or `git:<url>`), an optional
`ref` (branch or tag) and an optional `commit` (40 lowercase hex), and zero
or more `[[skill]]` tables with `id` (`<skill>@<source name>`) and `path`
(a relative path inside the repository, without `..`) and an optional `tree`
(40 lowercase hex, the git tree hash of the installed skill directory).
Every skill's source
SHALL be declared; names and ids SHALL be unique; a skill name SHALL follow
the profile name rule. An invalid table SHALL make the commands that read
the manifest fail with exit code 1, naming the file and the problem.

#### Scenario: Undeclared source
- **WHEN** a manifest lists the skill `tdd@tools` and no skill source named `tools`
- **THEN** `claude-sync status` exits with code 1 and names the file and `tools`

### Requirement: Shared clones
Each skill source SHALL be cloned at most once per machine, in
`sources/<name>/` next to the configuration file, and SHALL be shared by
every profile that declares a source of that name with the same `source`.
claude-sync SHALL never modify files inside a clone other than through git
fetch and checkout, and SHALL refuse to check out a clone with local
changes, naming it.

#### Scenario: Two profiles, one clone
- **WHEN** `perso` and `work` both declare the source `tools` and apply runs for both
- **THEN** `sources/tools/` is cloned once and both profiles link into it

### Requirement: Import skills
`claude-sync import` SHALL also record every link in the profile's `skills/`
directory whose target resolves into `sources/<name>/`, into another git
checkout with a remote, or into `~/.agents/skills/<skill>` described by a
version-3 `~/.agents/.skill-lock.json` entry of type `github`. A link into
`sources/<name>/` keeps that source name, its remote mapped back to the
manifest form (`https://github.com/<o>/<r>(.git)` gives `github:<o>/<r>`,
anything else `git:<url>`), and its checked-out commit. A lock entry gives
`github:<source>`, the directory of `skillPath`, and `tree` =
`skillFolderHash`, with no commit; one source per repository, named after
the first `pluginName` found for it in file order, else `<owner>-<repo>`.
A checkout without a remote, real skill directories (not links), other lock
types and links to anything else SHALL be left out, with a warning for
skipped links.

#### Scenario: Import from the lock file
- **WHEN** `skills/tdd` links to `~/.agents/skills/tdd` and the lock describes `tdd` from `github` `acme/skills` at `skills/engineering/tdd/SKILL.md` with folder hash `T`
- **THEN** the manifest has a source `github:acme/skills` without commit and a skill `tdd@<source>` with path `skills/engineering/tdd` and `tree = "T"`

#### Scenario: Import after apply is stable
- **WHEN** apply converged a profile and the user runs `claude-sync import` then `claude-sync status`
- **THEN** the manifest is unchanged and status exits 0

### Requirement: Skill status
`claude-sync status` SHALL also report: a declared skill without its link,
a link pointing elsewhere than its declared skill (for example still into
`~/.agents` right after import: `run claude-sync apply`), a link into the
sources directory that the manifest does not list, a missing clone, a clone
at another commit than the recorded one or on another ref, a clone with
local changes, and a skill whose directory in the clone has another tree
than its recorded `tree`. A source without a recorded commit is
information, not drift.

#### Scenario: Link points elsewhere
- **WHEN** `skills/tdd` links to `~/.agents/skills/tdd` and the manifest declares `tdd@tools`
- **THEN** status reports the link as pointing elsewhere and exits with code 4

### Requirement: Apply skills
`claude-sync apply` SHALL also clone missing sources (at `ref` when given),
fetch when the recorded commit is not present, and check out (detached) the
recorded commit when one is declared; when none is declared but the skills
have a `tree`, it SHALL check out the newest commit of the ref where every
declared skill's directory has its recorded tree, or, if no commit matches
all, the newest commit matching the most of them, reporting the others as
changed since install (exit 4, accepted with `claude-sync import`); without
commit or trees it stays on the ref's head. It SHALL then create missing skill links as absolute
links to `sources/<name>/<path>`, and replace a link pointing elsewhere only
after a confirmation. It SHALL never replace a real directory or file in
`skills/`; such a conflict stops apply with exit code 1, naming it. With
`--prune` it SHALL remove, after a confirmation, links into the sources
directory that the manifest does not list, and nothing else. `--dry-run`
SHALL print the planned git commands and link changes and change nothing.

#### Scenario: Converge skills
- **WHEN** a profile declares one source at a commit and two skills, and nothing exists yet
- **THEN** apply clones the source, checks out the commit, creates both links, and status then exits 0

#### Scenario: Pin to what is installed
- **WHEN** the manifest has no commit and both skills record the trees they had at upstream commit `C`, older than the head
- **THEN** apply checks out `C`

#### Scenario: Real directory conflict
- **WHEN** `skills/tdd` is a real directory and the manifest declares `tdd@tools`
- **THEN** apply exits with code 1, names `skills/tdd`, and leaves it unchanged

### Requirement: One source, one pin
A source name SHALL map to one source and one commit across all profiles of
the machine, since they share one clone. Before cloning or checking out,
apply SHALL read the manifests of the other profiles and refuse, with exit
code 1 and both profile names, when another profile declares the same
source name with another source or another recorded commit.

#### Scenario: Two profiles disagree
- **WHEN** `perso` declares `tools` at commit `A` and `work` declares `tools` at commit `B`
- **THEN** `claude-sync apply --profile work` exits with code 1 and names `perso`, `work` and both commits
