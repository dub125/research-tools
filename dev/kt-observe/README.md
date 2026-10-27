# kt-observe

Test-only logging for the knowledge-track observation period. Not part of the
plugin. It records what Claude does with `kt` so the system can be audited
afterwards.

## Install / remove

```sh
python3 dev/kt-observe/install.py              # hooks in ~/.claude/settings.json, /kt-flag in ~/.claude/commands
python3 dev/kt-observe/install.py --uninstall  # removes both, leaves the log
```

## What it logs

Everything goes to `~/.claude/knowledge-track-log/` (override: `KT_OBSERVE_DIR`).

`events.jsonl`, one event per line:

| event | when | fields |
|---|---|---|
| `kt` | any Bash call that runs `kt` | `kind` (read/write), `subcommands`, `failed`, `command`, `response`, `prompt` (the user's latest prompt), `kb`, `kb_head_before`, `kb_head_after` |
| `skill_loaded` | the knowledge-track skill loads | `skill` |
| `flag` | you type `/kt-flag <text>` | `text` |
| `session_end` | a session ends | `reason`, `kt_calls`, `transcript` |
| `logger_error` | the logger itself failed | `error` |

Every event has `ts`, `session` and `cwd`. For a write, the exact change is
`git -C <kb> diff <kb_head_before> <kb_head_after>`.

`sessions/<session>.jsonl` is a copy of each session's transcript, taken at
session end, because Claude Code deletes transcripts after 30 days. The audit
uses them to find what Claude missed: sessions where you showed what you
know and nothing was recorded.

The logger never prints and always exits 0, so it cannot affect a session.
