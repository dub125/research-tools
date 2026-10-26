# knowledge-track

A global, user-level inventory of what you know and how well: concepts,
methods, tools, and theories, each with a 0-5 level and the evidence behind it.
It lives outside any project, so Claude can look up your knowledge in any
session. Each concept is one markdown file and is atomic: if you could not
assess it with one question, split it. This version only stores and queries the
data. It does not decide how levels are assigned or when Claude asks you.

The format is defined in [SPEC.md](SPEC.md). The `kt` CLI is the only writer.

## Install

```
/plugin marketplace add <path-or-url-to-research-tools>
/plugin install knowledge-track@research-tools
```

The plugin's `bin/` directory is put on the Bash tool's PATH while the plugin
is enabled, so `kt` works as a bare command. Claude Code only: claude.ai and
Cowork do not install plugins that ship a top-level `bin/`.

## First run

```
kt init
kt remote <url>        # optional: back it up to a git remote
```

On another machine:

```
git clone <url> ~/.claude/knowledge
```

## Network rule

Only `kt remote` and `kt sync` touch the network. Every write command commits
locally and nothing more.

## CLI reference

Every write command runs lint, write, index, then `git commit -m "kt: <verb> <id>"`,
and never touches the network. List flags accept comma-separated values and may
be repeated.

### Repo

- `kt init`: create the knowledge dir (default `~/.claude/knowledge`, env
  `KNOWLEDGE_TRACK_DIR`) as a git repo with `concepts/`, `config.json`,
  `README.md`, `.gitignore`. Safe to re-run.
- `kt remote <url>`: add or set origin and push once (network).
- `kt sync`: `git pull --rebase` then `git push` (network). On conflict it
  prints the conflicting files and how to resolve: edit them, run
  `git -C <dir> rebase --continue`, then `kt lint`.
- `kt status [--json]`: counts by level and kind, branch, ahead/behind from
  local refs only, dirty flag, remote url.
- `kt index`: rebuild `index.json`.
- `kt lint [id ...] [--json]`: lint the whole KB. With ids, only report
  findings about those ids. Exit 1 on any error.

### Create

- `kt add <id> --title T --kind K --level N [--evidence "<date> <kind>: <note>"]... [--requires a,b] [--part-of x,y] [--related y] [--contrasts-with z] [--alias A]... [--tag T]... [--body TEXT | --body - | --body-file F]`:
  create a concept. Refuses on lint error.

### Read

- `kt show <id> [--json]`: human rendering: title, kind, level with name,
  relations including derived inverses, evidence, misconceptions, body.
- `kt get <id> [--threshold N]`: frontmatter plus derived `required_by`,
  `has_part`, `is_group`, `missing_prereqs` (direct `requires` targets with
  level below the threshold, default 3), and body. Always prints JSON.
- `kt list [--json]`: one line per concept: id, level, kind, title.
- `kt query [--level '<3'] [--kind K] [--tag T] [--requires-of ID] [--required-by ID] [--part-of ID] [--unresolved] [--json]`:
  - `--level` takes an operator and number (`<3`, `>=2`, `=0`).
  - `--requires-of ID` lists ID's direct prerequisites.
  - `--required-by ID` lists concepts whose `requires` contains ID.
  - `--part-of ID` lists direct members of ID.
  - `--unresolved` lists concepts with at least one relation target that does
    not exist. This only happens after hand edits or merges, since `kt`
    refuses to write them.
- `kt check <term>... [--resolve] [--threshold N] [--json]`: for each term
  returns `{query, id, known, level, matched_by}`. Matches exact id, or
  case-insensitive alias or title. With `--resolve` it also fuzzy matches.
  Unknown terms return `known: false, level: 0`.
- `kt graph [--mermaid|--dot] [--relation requires|part-of] [--json]`: default
  mermaid, both DAG relations unless `--relation` is given.
- `kt gaps <id> [--threshold N] [--json]`: transitive `requires` closure of id
  with level below the threshold.
- `kt fringe [--threshold N] [--json]`: concepts with level below the threshold
  whose every direct `requires` target is at or above it.

### Update

- `kt set <id> key=value ...`:
  - Scalars: `title`, `kind`, `level`, `body`.
  - Whole-list replacement with comma-separated values: `aliases`, `tags`,
    `requires`, `part-of`, `related`, `contrasts-with`.
  - `evidence` and `misconceptions`: each `key=value` occurrence adds one item,
    and the full list is replaced by the given occurrences. `evidence=` alone
    clears it.
  - `id`, `created`, `updated`, `last_evidenced` cannot be set.
- `kt add-evidence <id> "<date> <kind>: <note>" [--level N]`: appends evidence,
  recomputes `last_evidenced`, bumps `updated`, optionally sets the level.
- `kt link <a> <relation> <b>` and `kt unlink <a> <relation> <b>`: `requires`
  means a requires b; `part-of` means a is part of b; `related` and
  `contrasts-with` write both sides.
- `kt rename <old> <new>`: renames the file and rewrites every reference.

### Delete

- `kt rm <id> [--force]`: refuses if any concept references it. `--force`
  removes those references.
