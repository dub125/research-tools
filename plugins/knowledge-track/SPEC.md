# knowledge-track specification

This file defines the data format. The `kt` CLI implements it and
`kt validate` enforces it.

## Model

- One record per concept. A concept is anything Claude might put into an
  experiment design or explanation that the user may or may not understand:
  a method, tool, theory, or idea. Split a concept when the user could know
  one part well and another not at all.
- Grouping is done with `tags`. Prerequisites are done with `requires`. Ids
  encode no hierarchy.
- `kt` is the single writer. It validates before every write and refuses
  invalid state. Anyone may read the file directly.

## Storage

Default directory `~/.claude/knowledge/`. The env var `KNOWLEDGE_TRACK_DIR`
overrides it. The env var `KNOWLEDGE_TRACK_TODAY` (YYYY-MM-DD) overrides the
date `kt` stamps on writes; it exists for tests.

```
~/.claude/knowledge/
  concepts.jsonl   # one JSON object per line, sorted by id
  README.md
  .git/
```

Every write is: validate, atomic rewrite of `concepts.jsonl`, then
`git commit -m "kt: <verb> <id>"`. `kt` never touches the network. To back up
or sync, use git directly (`git -C ~/.claude/knowledge push` / `pull`).

One line per concept, sorted by id, means git diffs and merges work per
concept. A merge conflict leaves markers in the file; `kt` refuses to read it
until they are resolved.

## Record

```json
{"id": "message-passing", "name": "Message passing (GNN)", "level": 2, "aliases": ["MPNN", "neighbourhood aggregation"], "tags": ["gnn"], "requires": ["graph-basics"], "note": "explained the update rule back in own words", "updated": "2026-09-14"}
```

| Field | Type | Rule |
|---|---|---|
| `id` | string | Required. `^[a-z0-9]+(-[a-z0-9]+)*$`. Unique. |
| `name` | string | Required. Human-readable name. Defaults to the id with spaces. |
| `level` | int | Required. 0-3, see scale. |
| `aliases` | list of strings | Other names for the same concept. |
| `tags` | list of strings | Free grouping labels. |
| `requires` | list of ids | Prerequisites: A requires B means B is a prerequisite of A. Must resolve, no self-reference, acyclic. |
| `note` | string | Why the level is what it is. Required when `level >= 1`. |
| `updated` | date | Required. Set by `kt` on every write to the record. |

Fields at their default value (empty list, empty string) are omitted from the
file. Unknown fields are errors, so misspellings fail loudly.

History is not stored in the record. Each write is a git commit, so
`git log -p` on the knowledge repo shows how a level and its note changed.

### Name uniqueness

The normalised forms of every id, name and alias must be unique across the
knowledge base. Normalising lowercases and turns punctuation, hyphens and runs
of whitespace into single spaces. So "Over-smoothing", "over smoothing" and
`over-smoothing` are the same name. This guarantees an exact lookup resolves to
at most one concept.

### Adding a field

Add one line to `FIELDS` in `bin/kt` with its type and default, and document it
here. Existing records without the field read as the default; no migration is
needed. Renaming or restructuring a field needs a one-off rewrite of
`concepts.jsonl`.

## Level scale

| Level | Name | Meaning |
|---|---|---|
| 0 | unknown | No meaningful exposure. Also the answer for anything not in the file. |
| 1 | heard-of | Knows the name and roughly what it is for. |
| 2 | understands | Can explain how it works and why. |
| 3 | can-use | Has used it correctly and knows when it breaks. |

## Matching

`kt check` resolves a term in two steps:

1. Exact: the term equals an id, or its normalised form equals a normalised id,
   name or alias.
2. Otherwise, up to 3 candidates whose similarity is at least 0.6. Similarity
   is the larger of character similarity (`difflib` ratio) and word-overlap
   (Jaccard) between normalised strings.

Candidates are suggestions for Claude to judge. `kt` never treats a fuzzy match
as a match.

Creating a concept with `kt set` refuses when an existing concept scores at
least 0.75 against the new id, name or aliases, unless `--new` is given. A
synonym should become an alias of the existing concept instead.

## Validation

Errors block writes:

- Merge conflict markers or a line that is not a JSON object.
- Duplicate id.
- Unknown field, missing required field, or wrong type.
- `id` not kebab-case, `level` outside 0-3, `updated` not YYYY-MM-DD.
- `level >= 1` with an empty `note`.
- Empty or duplicate items in a list field.
- `requires` naming an unknown id or itself, or a cycle in `requires`.
- Two concepts sharing a normalised id, name or alias.

## Deliberately not decided yet

- How levels get assigned or changed, and who may change them.
- When Claude consults the knowledge base or prompts the user (gating).
- Decay of levels over time (if added, compute it at read time from `updated`).
- Any learning loop.
