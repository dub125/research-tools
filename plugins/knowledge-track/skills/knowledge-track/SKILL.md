---
name: knowledge-track
description: Use when you need to record, look up, or reason about what the user knows (concepts, methods, tools, theories, how well they know them, prerequisites).
allowed-tools: Bash(kt *)
---

# knowledge-track

A global record of what the user knows and how well. It lives in
`~/.claude/knowledge/concepts.jsonl` (override: `KNOWLEDGE_TRACK_DIR`), one JSON
object per concept, in a local git repo.

Write only through `kt`; it validates and commits. Reading the file directly is
fine, but `kt` output is shorter. Full schema: `SPEC.md` in the plugin directory.

## Levels

- 0 unknown: no meaningful exposure. Anything not tracked counts as 0.
- 1 heard-of: knows the name and roughly what it is for.
- 2 understands: can explain how it works and why.
- 3 can-use: has used it correctly and knows when it breaks.

## Rules

- **Look up before you create.** Run `kt check` on the term and any synonyms
  first. If it names an existing concept, or a `maybe:` candidate is the same
  thing, update that one and add the new wording with `--alias`.
- **Batch lookups.** Pass every term in one `kt check a b c` call, not one call
  per term. Do not re-check in the same session what you already looked up.
- **Don't dump the file.** Use `kt list` with `--level`/`--tag` filters. It caps
  at 50 rows.
- **Every level of 1 or more needs a `--note`** saying what you observed or what
  the user said, e.g. "implemented GCN layer in gnn/main.py". Do not raise a
  level without something to put there.
- Split a concept when the user could know one part well and another not at all.
  Group with `--tag`. Record prerequisites with `--requires`.

## Commands

- `kt check <term>...`: one line per term: level, how it matched, or up to 3
  `maybe:` candidates.
- `kt get <id>`: full record, plus `required_by` and `gaps` (prerequisites
  below level 2).
- `kt list [--level '<2'] [--tag T] [--all]`
- `kt gaps <id> [--threshold N]`: transitive prerequisites below N (default 2).
- `kt set <id> [--level N] [--note ..] [--name ..] [--alias A] [--tag T] [--requires a,b] [--clear FIELD] [--new]`:
  creates or updates. List flags append; `--clear tags` empties a list first.
  On create it refuses if a similar concept exists; use `--new` only if it is
  genuinely different.
- `kt merge <src> <dst>`: fold a duplicate into another. Its names become
  aliases and links are rewritten.
- `kt dupes`: likely duplicate pairs to review.
- `kt rm <id> [--force]`, `kt validate`, `kt init`
- Add `--json` to read commands when you need to parse output.

## Scope of this version

This version records state only. No policy exists yet for when to ask the user
about a concept or how to assign levels. Do not invent one: record what the user
tells you or what you observe, and put the basis in the note.
