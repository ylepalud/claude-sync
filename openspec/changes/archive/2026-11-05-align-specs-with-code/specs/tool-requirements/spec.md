## MODIFIED Requirements

### Requirement: Tool tables
The profile manifest SHALL accept zero or more `[[tool]]` tables with a
unique `name` (letters, digits, `.`, `_`, `-`, starting with a letter or a
digit), an optional `version` (a
minimum, dotted numbers), an optional `check` (a command line whose first
word is the tool's name; default `<name> --version`) and an optional
`install` recipe: `brew:<formula>`, `npm:<package>`, `uv:<package>`,
`cargo:<crate>` or `script:<command>` (a single line without control
characters). An
invalid table SHALL make commands that read the manifest fail with exit
code 1, naming the file and the problem.

#### Scenario: Unknown recipe kind
- **WHEN** a tool declares `install = "apt:jq"`
- **THEN** the manifest is invalid and the error names the allowed kinds
