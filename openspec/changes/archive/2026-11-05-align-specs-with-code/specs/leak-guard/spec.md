## MODIFIED Requirements

### Requirement: Findings never reveal the terms
A finding SHALL name the location and the 1-based index of the matching term
in the denylist, and SHALL NOT print the term, the matching line, or any path
that contains a term, so that public CI logs never disclose the denylist.
Locations are `<path>:<line>` for file content, `path #<k>` (1-based position
in the scanned path list) when the path itself matches, for history
`<short sha>:<path>:<line>` for an added line (the path replaced by
`path #<k>` when it matches), `<short sha>: path #<k>` for a matching path,
`<short sha>: message` for a commit message, `<short sha>: identity` for an
author or committer, and `ref #<k>` or `ref #<k>: tag message` for refs, `message` for a
message file, and the caller's label for free text. Error messages SHALL never
echo file content or git output.

#### Scenario: Finding output
- **WHEN** line 3 of `README.md` contains the second denylist term
- **THEN** the output contains `README.md:3` and `term #2` and does not contain the term itself

#### Scenario: Term in a path
- **WHEN** a tracked file path contains the first denylist term
- **THEN** the output reports `path #<k>: term #1` and does not print the path
