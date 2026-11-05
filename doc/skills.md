# Skills

A profile has two kinds of skills:

- **Its own skills**: real directories in its `skills/`, written by you.
  claude-sync leaves them alone; version them in the profile's git
  repository if you want (add them to its `.gitignore` allowlist).
- **External skills**, taken from someone else's repository. They are
  declared in `profile.toml`, pinned to a commit, cloned once per machine
  and linked into `skills/`.

This page is about external skills.

## Tables

```toml
[[skill_source]]
name = "example-skills"
source = "github:example/skills"
ref = "main"
commit = "0123456789abcdef0123456789abcdef01234567"

[[skill]]
id = "tdd@example-skills"
path = "skills/engineering/tdd"
tree = "89abcdef0123456789abcdef0123456789abcdef"
```

### [[skill_source]]

| Key | Required | Value |
| --- | -------- | ----- |
| `name` | yes | `[A-Za-z0-9][A-Za-z0-9._-]*`, unique in the file |
| `source` | yes | `github:<owner>/<repo>` or `git:<url>` |
| `ref` | no | A branch or a tag; without it, the remote's default branch |
| `commit` | no | 40 lowercase hex characters, the commit to check out |

- `github:<owner>/<repo>` is cloned from
  `https://github.com/<owner>/<repo>.git`.
- `git:<url>` is cloned from `<url>` as it is; a local path works too.

### [[skill]]

| Key | Required | Value |
| --- | -------- | ----- |
| `id` | yes | `<skill>@<source name>`, unique; the source must be declared |
| `path` | yes | The skill's directory in the repository |
| `tree` | no | 40 lowercase hex characters, the git tree hash of that directory as installed |

- The skill name (before `@`) follows the profile name rule,
  `[a-z0-9][a-z0-9-]*`, and becomes the link `skills/<skill>`.
- `path` is relative, without a leading `/` and without `.`, `..` or
  empty segments.
- `tree` lets `apply` find the commit a skill was installed from when no
  `commit` is recorded (see [Pinning](#pinning)).

Unknown keys, missing fields, duplicates and invalid values make the
commands that read the manifest fail with exit 1, naming the file.

## Shared clones

Each source is cloned once per machine, in
`~/.config/claude-sync/sources/<name>/`, and every profile that declares
a source of that name shares the clone. The link
`skills/<skill>` in each profile is an absolute link to
`sources/<name>/<path>`.

claude-sync changes a clone only through `git clone`, `git fetch` and
`git checkout --detach`. It never edits, commits or cleans files inside
it.

### One source name, one pin

Since the clone is shared, a source name means one source at one commit
on the machine. Before cloning or checking out, `apply` reads the
`profile.toml` of every other profile and refuses with exit 1, naming
both profiles, when another profile declares the same source name:

- with another `source`;
- with another recorded `commit`;
- with a `commit` while the current profile declares the same source
  without one.

For example, when `perso` pins `example-skills` at commit `A` and `work`
at commit `B`, `claude-sync apply --profile work` fails with a message
naming `perso`, `work` and both commits. Align the commits, or give the
sources two names (two clones) to use two commits of one repository. An
invalid manifest in another profile also stops `apply`, with that
profile's error.

## Pinning

`apply` decides which commit a clone checks out, detached:

1. the recorded `commit`, when there is one;
2. otherwise, when skills of that source record a `tree`: the newest
   commit of the ref where every such skill's directory has its recorded
   tree, that is, the version that was installed. When no commit matches
   them all, the newest one matching the most, and the others are
   reported as changed since install (`skill-tree`, exit 4, accept with
   `claude-sync import`);
3. otherwise: a new clone stays at the ref's head, an existing clone on
   its ref stays where it is, and an existing clone off its ref moves to
   the ref's head.

The ref is the declared `ref` (`origin/<ref>`, or the tag `<ref>`), or
the remote's default branch without one.

A source without a `commit` is `skill-unpinned` in `status`:
information, not drift. Run `import` after `apply` to record the commit
`apply` checked out.

## Import

`claude-sync import` (see [The manifest](manifest.md#import)) records
every link in the profile's `skills/` directory that it can trace to a
repository. Links are read in name order, links into `sources/` first so
they keep their names.

| Link points into | Recorded as |
| ---------------- | ----------- |
| `sources/<name>/...` | Source `<name>`, its clone's `origin` in manifest form, its checked-out commit |
| Another git checkout with a remote | The same, the source named after the checkout's directory |
| `~/.agents/skills/<skill>`, described in `~/.agents/.skill-lock.json` | `github:<source>`, the directory of `skillPath`, `tree` = `skillFolderHash`, no commit |

- A remote `https://github.com/<owner>/<repo>`, with or without `.git`,
  becomes `github:<owner>/<repo>`; any other URL `git:<url>`.
- The lock file is the one a third-party skills CLI writes. Only version
  3 is read, and only entries of type `github`. One source is made per
  repository, named after the first `pluginName` of its entries in file
  order, else `<owner>-<repo>`.
- A source already found for the same repository is reused (at the same
  commit for a checkout, at any commit for a lock entry). A name already
  taken gets `-2`, `-3`, and so on.
- From the manifest being replaced, import keeps the `ref` of a source of
  the same name and source (a ref you added by hand), and the `tree` of a
  skill of the same id and path, read again from the clone.

Left out:

- real skill directories and files, silently (they are your own skills);
- with a warning on standard error: a link to anything else, into a
  checkout without a remote, into the profile's own repository, to the
  root of a checkout, into `~/.agents/skills` without a usable lock entry,
  and any skill or source the manifest rules would reject (an invalid
  skill name, for example);
- a lock file of another version or shape is ignored with a warning.

### After an import from the lock file

Right after such an import the links still point into
`~/.agents/skills`, and the source has no commit yet. `status` reports
each link as `skill-elsewhere` and the clone as `clone-missing`, and
exits 4; the missing commit is information. Then:

```sh
claude-sync import --profile perso   # skills still link into ~/.agents
claude-sync apply --profile perso    # clone, pin from trees, relink (confirmation)
claude-sync import --profile perso   # record the commit apply checked out
claude-sync status --profile perso   # exit 0
```

claude-sync never modifies or removes anything in `~/.agents`. Once no
profile links into it, remove it with the tool that installed it.

## Status

`claude-sync status` also reports:

| Kind | Subject | Drift | Meaning |
| ---- | ------- | ----- | ------- |
| `skill-missing` | skill id | yes | No link `skills/<skill>` |
| `skill-elsewhere` | skill id | yes | The link points elsewhere (for example into `~/.agents`): run `apply` |
| `skill-conflict` | skill id | yes | A real file or directory is at the link path |
| `skill-unlisted` | link name | yes | A link into `sources/` that the manifest does not list |
| `skill-tree` | skill id | yes | The skill's directory in the clone has another tree than `tree` |
| `clone-missing` | source | yes | `sources/<name>/` is not cloned |
| `source` | source | yes | The clone's `origin` is another source |
| `clone-commit` | source | yes | The clone is at another commit than `commit` |
| `skill-ref` | source | yes | The clone's head is not on the declared ref |
| `clone-dirty` | source | yes | The clone has local changes |
| `skill-unpinned` | source | no | No `commit` recorded |

## Apply

`apply` converges skills after plugins and marketplaces, and before MCP
servers. Per source, in manifest order:

- clone a missing one (`git clone [--branch <ref>] <url> sources/<name>`);
- fetch (`git fetch --tags origin`) when the commit to check out or the
  declared ref is absent from the clone;
- check out, detached, the commit chosen as in [Pinning](#pinning).

Then, per declared skill:

- create a missing link as an absolute link to
  `sources/<name>/<path>`;
- replace a link pointing elsewhere, after the confirmation.

With `--prune`, it also removes, after the confirmation, links in
`skills/` into the sources directory that the manifest does not list,
and nothing else: no real directory, no link elsewhere, no clone.

`--dry-run` prints the `git` commands and link changes:

```text
would run: git clone https://github.com/example/skills.git ~/.config/claude-sync/sources/example-skills
would run: git -C ~/.config/claude-sync/sources/example-skills checkout --detach 0123456789abcdef0123456789abcdef01234567
would link ~/.config/claude-sync/profiles/perso/skills/tdd -> ~/.config/claude-sync/sources/example-skills/skills/engineering/tdd
```

When the commit can only be chosen after a clone or a fetch, the dry run
shows `checkout --detach <newest commit matching the recorded trees>` or
`<head of REF>`.

### Refusals

`apply` stops with exit 1, before any change (plugins included), when:

- a real file or directory is at a declared skill's link path:
  `~/.../skills/tdd is not a link: move it away to install
  tdd@example-skills, or remove the skill from the manifest`;
- a clone in `sources/` has another `origin` than its declared source:
  remove the clone, or rename the source;
- a declared source's clone has local changes:
  `~/.config/claude-sync/sources/example-skills has local changes: commit
  or discard them, then apply again`;
- another profile declares the same source name differently (see
  [One source name, one pin](#one-source-name-one-pin)).

A declared `ref` that does not exist upstream, even after the fetch,
fails while the actions run: `unknown ref 'x' in <clone>` (exit 1).

A recorded `tree` that still differs after `apply` is reported like a
moved plugin version, with `accept with: claude-sync import`, and `apply`
exits 4.

## During migration

`init` and `uninstall` never clone or relink skills. `init` records the
skill tables in `profile.toml` and leaves every link as it is (relative
links pointing outside `~/.claude` are only made absolute so they keep
working after the move); `uninstall` restores the links as recorded.
Converge the skills afterwards with `claude-sync apply`.
