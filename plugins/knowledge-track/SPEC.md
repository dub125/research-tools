# knowledge-track specification

This file defines the data format. The `kt` CLI implements it and
`kt validate` enforces it.

## Model

- One record per concept. A concept is anything Claude might put into an
  experiment design or explanation that the user may or may not understand:
  a method, tool, theory, or idea, used as a black box. Its level describes
  the user's grasp of that black box from the outside. The rules for what
  counts as a concept are in [Concept rules](#concept-rules).
- Components are done with `part-of`. Prerequisites are done with `requires`.
  Fields of study are `tags`, never concepts with a level. Ids encode no
  hierarchy.
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
{"id": "message-passing", "name": "Message passing (GNN)", "summary": "Layer update in which each node aggregates its neighbours' features and combines them with its own; stacked to build most GNNs.", "level": 2, "aliases": ["MPNN", "neighbourhood aggregation"], "tags": ["gnn"], "requires": ["graph-basics"], "part-of": ["graph-neural-networks"], "note": "explained the update rule back in own words", "updated": "2026-09-14"}
```

| Field | Type | Rule |
|---|---|---|
| `id` | string | Required. `^[a-z0-9]+(-[a-z0-9]+)*$`. Unique. |
| `name` | string | Required. Human-readable name. Defaults to the id with spaces. |
| `summary` | string | Required. The black-box line: what goes in, what comes out, when it is used, without naming its parts. |
| `level` | int | Required. 0-3, see scale. |
| `aliases` | list of strings | Other names for the same concept. |
| `tags` | list of strings | Free grouping labels, including fields of study. |
| `requires` | list of ids | Prerequisites: A requires B means B is a prerequisite of A. Must resolve, no self-reference, acyclic. |
| `part-of` | list of ids | Components: A part-of B means A is inside B and B can be used without knowing A. Must resolve, no self-reference, acyclic, and no id in both `requires` and `part-of`. |
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

## Concept rules

Claude creates concepts on its own, without asking the user, so every concept
is created by the same procedure. Before `kt set` creates a concept, it must
pass these tests:

1. **Established name.** It is a term the field uses: in textbooks, papers or
   software docs. No invented units like "msm-estimation-step-2".
2. **Black-box line.** Its `summary` can say what goes in, what comes out and
   when it is used, in one sentence, without naming its parts. If that
   sentence cannot be written, it is not a concept.
3. **Inside or prerequisite.** For each related concept A of B:
   - B can be used from the outside without knowing A: A `part-of` B.
   - B's outside cannot be understood without A: B `requires` A.
4. **Only on demand.** Create a concept only when the current work depends on
   it or the user brings it up. Nothing speculative.
5. **Split, don't stretch.** When the work depends on the inside of a concept,
   create the inner concepts and track them separately. A parent's level
   never covers its parts.
6. **Context in ambiguous names.** When a name means different things in
   different fields, the id says which (`gat-attention`, not `attention`).

### Reference example

New concepts are compared against this tree as well as the rules. When a case
comes up that the rules do not settle, add a rule or an example here.

```text
msm            Markov state model: featurized trajectories in; metastable states,
               transition probabilities and implied timescales out
  requires     markov-chain
  parts        tica                       (also used on its own outside MSMs)
               clustering-microstates
               transition-count-matrix
               reversible-estimation
               lag-time-selection
               chapman-kolmogorov-test

tpt            Transition path theory: an MSM plus source and sink states in;
               committors, reactive flux and dominant pathways out
  requires     msm
  parts        committor
               reactive-flux
```

- "Build an MSM and compare implied timescales across mutants" depends on the
  outside of `msm`, so only `msm` matters.
- "Compute committors from the transition matrix and interpret the reactive
  flux" depends on the inside, so `transition-count-matrix`, `committor` and
  `reactive-flux` matter, whatever the level of `msm`.
- Graph neural networks is a concept (graph in, embeddings out); `gnn` is also
  the tag for the field.

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
- The same for `part-of`, or an id in both `requires` and `part-of`.
- Missing or empty `summary`.
- Two concepts sharing a normalised id, name or alias.

## Deliberately not decided yet

- How levels get assigned or changed, and who may change them.
- When Claude consults the knowledge base or prompts the user (gating).
- Decay of levels over time (if added, compute it at read time from `updated`).
- Any learning loop.
