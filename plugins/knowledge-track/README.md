# knowledge-track

A global record of what you know and how well. Each concept, method, tool or
theory gets a 0-3 level and a note saying why. It lives outside any project, so
Claude can look up your knowledge in any session. This version only stores and
queries the data. It does not decide how levels are assigned or when Claude
asks you.

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
```

This creates `~/.claude/knowledge/` (override with `KNOWLEDGE_TRACK_DIR`) as a
git repo holding `concepts.jsonl`. Every `kt` write commits locally. `kt` never
touches the network; to back up or share across machines, add a remote and
push with git:

```
git -C ~/.claude/knowledge remote add origin <url>
git -C ~/.claude/knowledge push -u origin HEAD
```

On another machine, `git clone <url> ~/.claude/knowledge`.

## Example

```
$ kt set graph-basics --level 3 --note "uses networkx daily"
$ kt set message-passing --level 2 --requires graph-basics --alias MPNN \
      --note "explained the update rule back"
$ kt check mpnn "neighbourhood aggregation" oversmoothing
'mpnn' -> message-passing (alias)        2 understands
'neighbourhood aggregation'              0 not tracked
'oversmoothing'                          0 not tracked
$ kt set message-passing --alias "neighbourhood aggregation"
```

## Commands

| Command | Does |
|---|---|
| `kt init` | Create the knowledge base. Safe to re-run. |
| `kt set <id> ...` | Create or update. `--level`, `--note`, `--name` replace; `--alias`, `--tag`, `--requires` append; `--clear FIELD` empties a list first. Refuses to create something similar to an existing concept unless `--new`. |
| `kt check <term>...` | Look up terms by id, name or alias; suggests near matches. |
| `kt get <id>` | One record with `required_by` and prerequisite `gaps`. |
| `kt list` | Filter with `--level '<2'` and `--tag`; shows 50 unless `--all`. |
| `kt gaps <id>` | Transitive prerequisites below `--threshold` (default 2). |
| `kt merge <src> <dst>` | Fold a duplicate into another concept. |
| `kt dupes` | Likely duplicate pairs. |
| `kt rm <id>` | Delete; `--force` also drops links that require it. |
| `kt validate` | Check the whole file. |

Read commands take `--json`.

## Tests

```
python3 plugins/knowledge-track/tests/test_kt.py
```
