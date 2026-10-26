---
name: knowledge-track
description: Use when you need to record, look up, or reason about what the user knows (concepts, tools, methods, theories, knowledge levels, prerequisites).
allowed-tools: Bash(kt *)
---

# knowledge-track

A global inventory of what the user knows and how well. It lives in
`~/.claude/knowledge/` (override: `KNOWLEDGE_TRACK_DIR`), a git repo with one
markdown file per concept.

**Never read or edit the markdown files directly. Always go through `kt`.**
`kt` is the single writer: it lints, writes, rebuilds the index, and commits
locally. Only `kt remote` and `kt sync` touch the network. Use `--json` when you
need to parse output. Full schema: `SPEC.md` in the plugin directory.

## Atomicity test

A concept is atomic if it is assessable with one question. "GNN" is not atomic;
"message passing" and "over-smoothing" are. Group with relations (`part-of`),
not folders. Ids are lowercase kebab-case and encode no hierarchy.

## Commands

- `kt init`, `kt remote <url>`, `kt sync`, `kt status`, `kt index`, `kt lint [id...]`
- `kt add <id> --title T --kind concept|method|tool|theory --level 0-5 [--evidence "<date> <kind>: <note>"]... [--requires a,b] [--part-of x] [--related y] [--contrasts-with z] [--alias A]... [--tag T]... [--body TEXT|-|--body-file F]`
- `kt show <id>`, `kt get <id> [--threshold N]` (JSON with required_by, has_part, is_group, missing_prereqs; default threshold 3), `kt list`
- `kt query [--level '<3'] [--kind K] [--tag T] [--requires-of ID] [--required-by ID] [--part-of ID] [--unresolved]`
- `kt check <term>... [--resolve]`: per term `{query, id, known, level, matched_by}`; unknown is level 0
- `kt graph [--mermaid|--dot] [--relation requires|part-of]`
- `kt gaps <id> [--threshold N]`: transitive prerequisites below threshold
- `kt fringe [--threshold N]`: concepts below threshold whose direct prerequisites are all at or above it
- `kt set <id> key=value ...`: scalars and whole-list replacement; each `evidence=`/`misconceptions=` occurrence is one item, `evidence=` alone clears
- `kt add-evidence <id> "<date> <kind>: <note>" [--level N]`
- `kt link|unlink <a> requires|part-of|related|contrasts-with <b>` (a requires b; a is part of b; the last two are symmetric)
- `kt rename <old> <new>`, `kt rm <id> [--force]`

## Evidence kinds

- `self`: the user asserted it, no demonstration.
- `exposed`: the user was shown or told it. Exposure, not competence.
- `explained-back`: the user explained it in their own words.
- `observed`: the user was seen using it correctly in real work.
- `quiz`: the user answered targeted questions about it.
- `taught`: the user taught it or produced teaching material.

A level of 1 or more requires at least one evidence line.

## Levels

- 0 unknown: no exposure. Default for ids not in the KB.
- 1 aware: can say what it is and what it is for.
- 2 explain: can explain the mechanism in own words and answer "why".
- 3 apply: has used it correctly with inputs and assumptions stated.
- 4 connect: knows when it fails, compares alternatives, spots misuse.
- 5 create: can adapt, extend, or teach it.

## Scope of this version

This iteration records state only. No policy exists yet for when to ask the user
about a concept or how to assign levels. Do not invent one: record what the user
tells you or what you observe, cite it as evidence, and do not raise levels
without evidence.
