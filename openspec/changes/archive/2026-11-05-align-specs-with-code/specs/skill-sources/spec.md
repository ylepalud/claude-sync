## MODIFIED Requirements

### Requirement: Apply skills
`claude-sync apply` SHALL also clone missing sources (at `ref` when given),
fetch when the recorded commit is not present, and check out (detached) the
recorded commit when one is declared; when none is declared but the skills
have a `tree`, it SHALL check out the newest commit of the ref where every
declared skill's directory has its recorded tree, or, if no commit matches
all, the newest commit matching the most of them, reporting the others as
changed since install (exit 4, accepted with `claude-sync import`); without
commit or trees, a fresh clone is at the head of its ref, an existing clone
on its ref stays where it is, and an existing clone off its declared ref is
checked out at that ref's head. It SHALL then create missing skill links as absolute
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
