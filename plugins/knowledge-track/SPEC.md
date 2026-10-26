# knowledge-track specification

This file is the authoritative definition of the data format. The `kt` CLI
implements it; `kt lint` enforces it.

## Model

- Unit: one concept per markdown file, in a flat directory. A concept is atomic
  if it is assessable with one question. "GNN" is not atomic; "message passing"
  and "over-smoothing" are.
- Hierarchy is data, not path. Grouping uses relations, so reorganising never
  renames files. Ids encode no hierarchy.
- `kt` is the single writer. It lints before every write and refuses invalid
  state. Files must not be edited by hand.

## Storage layout

Default directory `~/.claude/knowledge/`. The env var `KNOWLEDGE_TRACK_DIR`
overrides it. The env var `KNOWLEDGE_TRACK_TODAY` (YYYY-MM-DD) overrides the
date `kt` stamps on writes; it exists mainly for tests.

```
~/.claude/knowledge/        # git repo with a remote; cloned on every machine
  concepts/<id>.md          # one atomic concept per file; id == filename stem
  config.json               # tracked: {"auto_commit": true, "auto_sync": false}
  README.md                 # tracked: what this repo is, link to this spec
  .gitignore                # index.json
  index.json                # GENERATED, local-only, rebuilt on every write and by `kt index`
  .git/
```

Every write is: lint, write, index, `git commit -m "kt: <verb> <id>"`. Nothing
touches the network except `kt remote` and `kt sync`. `auto_sync` exists in
`config.json` for a future hook; it defaults to `false` and write commands never
read it. `kt status` reports ahead/behind from local refs only (no fetch).

## Concept file

```markdown
---
id: message-passing
title: Message passing (GNN layer update)
kind: concept            # concept | method | tool | theory
level: 3                 # 0-5, see scale
last_evidenced: 2026-09-14
aliases: [neighbourhood aggregation]
tags: [ml, gnn]
requires: [graph-basics, matrix-multiplication]
part-of: [graph-neural-networks]
related: [attention-mechanism]
contrasts-with: [label-propagation]
evidence:
  - "2026-09-14 observed: implemented GCN layer in gnn/main.py"
  - "2026-06-02 explained-back: described the update rule in own words during review"
  - "2026-05-20 exposed: Claude walked through Gilmer et al. message passing framework"
misconceptions:
  - "2026-05-10 thought aggregation had to be mean; sum/max are valid"
created: 2026-06-02
updated: 2026-09-14
---
One-paragraph definition in the user's own words. Optional notes below.
```

## Frontmatter grammar

- `key: scalar`
- `key: [a, b, "c d"]` (flow list)
- Block list: the key on its own line, then indented `- item` lines. Items are
  strings, optionally quoted.
- No nesting. No multi-line scalars.
- Unknown keys are errors, which keeps the schema explicit.
- An unquoted scalar may be followed by an inline comment starting with ` #`
  (space, then hash). The parser strips it. `kt` itself never writes comments.

## Fields

| Field | Rule |
|---|---|
| `id` | Required. `^[a-z0-9]+(-[a-z0-9]+)*$`. Unique. Equals the filename stem. |
| `title` | Required, non-empty. |
| `kind` | Required. One of `concept`, `method`, `tool`, `theory`. |
| `level` | Required integer 0-5. |
| `evidence` | List of strings matching `^\d{4}-\d{2}-\d{2} (self\|exposed\|explained-back\|observed\|quiz\|taught): .+$`. Must be non-empty when `level >= 1`. |
| `last_evidenced` | Required when evidence is non-empty; must equal the newest evidence date. |
| `requires`, `part-of` | Lists of ids. Must resolve. No self-reference. Each relation must be acyclic across the whole KB. |
| `related`, `contrasts-with` | Lists of ids. Must resolve. No self-reference. Symmetric by convention. |
| `aliases`, `tags`, `misconceptions` | Optional lists of strings. |
| `created`, `updated` | Required ISO dates. |

`created`, `updated`, and `last_evidenced` are maintained by `kt` and may not be
set directly. `last_evidenced` is always recomputed as the newest evidence date
on write.

There is no `domain` kind. A grouping node is any concept that other concepts
are `part-of` (derived `has_part` non-empty, `is_group` true). Its own `level`
describes only its own atomic content (for example "what GNNs are and the
general framework"), never a rollup of its parts. Rollups over parts are a
query, never a stored value.

### Serialisation

`kt` writes frontmatter keys in this fixed order: id, title, kind, level,
last_evidenced, aliases, tags, requires, part-of, related, contrasts-with,
evidence, misconceptions, created, updated. Empty optional lists are omitted.
`evidence` and `misconceptions` are written as block lists with double-quoted
items. All other lists are written as flow lists. The order is fixed so diffs
are stable.

## Evidence kinds

- `self`: the user asserted it, no demonstration.
- `exposed`: the user was shown or told it (by Claude, a paper, a lecture).
  Exposure, not competence.
- `explained-back`: the user explained it in their own words, to Claude or
  elsewhere.
- `observed`: the user was seen using it correctly in real work (code,
  analysis, derivation).
- `quiz`: the user answered targeted questions about it.
- `taught`: the user taught it to someone else or produced teaching material.

No policy attaches to kinds yet. The schema only guarantees the distinction is
recorded.

## Level scale

Definitions only; no assessment policy.

| Level | Name | Can-do statement |
|---|---|---|
| 0 | unknown | No exposure. Default for ids not in the KB. |
| 1 | aware | Can say what it is and what it's for. |
| 2 | explain | Can explain the mechanism in own words and answer "why". |
| 3 | apply | Has used it correctly with inputs and assumptions stated. |
| 4 | connect | Knows when it fails, compares with alternatives, spots misuse. |
| 5 | create | Can adapt, extend, or teach it. |

## Relations

Four relations. Only `requires` and `part-of` are DAGs. They are separate on
purpose: being part of GNNs does not make all of GNNs a prerequisite.

| Relation | Meaning | Stored |
|---|---|---|
| `requires` | A requires B: B is a prerequisite of A. | On A only. Inverse `required_by` is derived. |
| `part-of` | A is part of B (multi-parent allowed). | On A only. Inverse `has_part` is derived. |
| `related` | Associated concepts. | Symmetric: both sides. |
| `contrasts-with` | Commonly confused with. | Symmetric: both sides. |

`kt` writes both sides of symmetric relations. Lint warns when only one side
exists (possible after hand edits or merges).

## Lint rules

Errors block writes:

- Conflict markers in a file.
- Frontmatter does not parse under the grammar above (including nested YAML).
- Unknown key.
- Missing or invalid `id`, `title`, `kind`, `level`.
- `id` does not equal the filename stem, or is not unique.
- Evidence line not matching the evidence pattern (including unknown kinds).
- `level >= 1` with empty evidence.
- `last_evidenced` missing when evidence is non-empty, not equal to the
  newest evidence date, or present when there is no evidence.
- Missing or malformed `created` or `updated`.
- A relation target that does not exist.
- Self-reference in any relation, or the same id listed twice in one relation.
- A cycle in `requires` or in `part-of`.
- An empty string in `aliases`, `tags`, or `misconceptions`.

Warnings do not block:

- Empty body.
- `level >= 3` while a `requires` target has `level < 2`.
- Orphan: no relations at all, direct or derived.
- Alias that collides with another concept's id or alias.
- Symmetric relation present on one side only.

## `index.json`

Generated, local-only (git-ignored), rebuilt on every write and by `kt index`.
It is a JSON array with one record per concept. Each record holds every
frontmatter field (lists default to `[]`), the `body`, and derived fields:

- `required_by`: ids whose `requires` contains this id.
- `has_part`: ids whose `part-of` contains this id.
- `is_group`: true when `has_part` is non-empty.
- `file`: path of the concept file relative to the knowledge directory, e.g. `concepts/message-passing.md`.

## Deliberately not decided in this iteration

- How levels get assigned or changed (self-report, observation, assessment).
- Who may set a level, and verification policy.
- When Claude consults or prompts about the knowledge base.
- Decay or effective level over time.
- Gating hooks and automatic sync.
- Any learning loop.
- Bootstrapping concepts from a project.

The schema keeps evidence kinds and `last_evidenced` so these can be built
without a migration.
