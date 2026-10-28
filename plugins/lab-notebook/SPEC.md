# lab-notebook specification

This file defines the data model and storage. The `nb` CLI implements it and
`nb lint` enforces it.

## Model

- One notebook per git repository: a typed graph of what the project is
  trying to find out, what it did, what it found, and what it concluded.
- The notebook holds epistemic state only. Metrics and configs stay in
  W&B, MLflow or Hydra run directories; the notebook stores references to
  them. Work items and operational how-to facts belong in foam. What the user
  knows belongs in knowledge-track.
- `nb` is the single writer. It validates before every write and refuses
  invalid state. Anyone may read the ref directly with git.
- Things that only Claude proposes (goals, conclusions, leads, decisions)
  start `pending` and become established only when the user runs or approves
  `nb confirm`.

## Storage

The notebook lives on the git ref `refs/notebook/data` of the repository that
contains the current directory. Nothing is checked out, so it is the same on
every branch and worktree, and a result recorded on a branch that is later
deleted is not lost.

```text
refs/notebook/data  ->  commit  ->  tree
                                     meta.json         {"schema": 1, "config": {...}}
                                     nodes/<id>.json   one node per file
```

Every write is: load, apply, validate the whole graph, then write blobs and a
tree with `git hash-object -w` and `git mktree`, make a commit with
`git commit-tree -p <old>`, and move the ref with
`git update-ref refs/notebook/data <new> <old>`. The last step is a
compare-and-swap: if another `nb` moved the ref first, the write reloads and
retries (up to 5 times). There is no lock and no daemon. The commit message is
`nb: <verb> <id>`.

Reads are one `git ls-tree -r` and one `git cat-file --batch` over the tree,
so no cache is needed at the expected scale (thousands of nodes).

The **notebook version** is the ref's commit SHA. Fields that record "as of
when" (`confirmed_at`, `audited_at`) store that SHA. "What changed since X" is
a tree diff between X and the current ref, which stays correct across merges.

Env vars: `NB_TODAY` (YYYY-MM-DD) overrides the date stamped on writes, for
tests. `NB_REF` overrides the ref name, for tests. There is deliberately no
variable that sets the author (see [Authorship](#authorship)).

### Schema versioning

`meta.json` carries `schema` (an integer, currently 1). `nb` migrates an older
schema in memory and writes the new one on the next write. It refuses a ref
whose schema is newer than it knows. Adding an optional field with a default
does not bump the schema; renaming, restructuring or adding a required field
does, with a migration function in `bin/nb`.

### Sync

`nb sync` exchanges the notebook with the `origin` remote:

1. `git fetch origin +refs/notebook/data:refs/notebook/origin`.
2. If one side contains the other, fast-forward. Otherwise merge three-way
   against `git merge-base`, node by node:
   - a node changed on one side only takes that side;
   - a node changed on both sides is merged field by field. Append-only lists
     (`log`, `links`, `refs`, `deviations`, `runs`) are unioned, keeping the
     base order and then each side's new entries. A scalar changed on one side
     takes that side. A scalar changed differently on both sides is a
     conflict.
3. On any conflict, or if the merged graph fails validation, nothing is
   written and `nb sync` lists the nodes and fields. Resolve by changing one
   side with `nb` and syncing again.
4. Commit the merge with both parents, then
   `git push origin refs/notebook/data:refs/notebook/data`. Retry from step 1
   up to 3 times if the push is rejected.

`nb init` adds the fetch refspec to `origin` and appends a delimited block to
`.git/hooks/pre-push` that runs `nb sync` (skipped when `NB_IN_HOOK` is set,
never failing the code push). An existing hook, such as foam's, is kept. A
fresh clone needs `nb init` before the notebook is visible.

## IDs

`<prefix>-<4 chars>`, the chars drawn at random from `0-9a-z` without
`i l o u`. On collision, `nb` draws again; after 10 collisions it uses 5
chars.

| Type | Prefix |
|---|---|
| goal | `goal` |
| question | `q` |
| hypothesis | `hyp` |
| experiment | `exp` |
| exploration | `xpl` |
| result | `res` |
| conclusion | `con` |
| lead | `lead` |
| decision | `dec` |
| audit | `aud` |
| source | `src` (reserved) |

Every command that takes an id accepts any unique prefix of one (`exp-7k`).
An ambiguous prefix is an error that lists the matches.

## Node

```json
{"id": "con-4mxa", "type": "conclusion", "title": "BioEmu2 propagation committors are worse than a constant predictor",
 "author": "claude", "created": "2026-10-23", "updated": "2026-10-24", "status": "supported",
 "rationale": "Brier skill -0.28 on all three proteins, below the q=0.5 constant baseline ...",
 "scope": "chignolin, villin, trp-cage; 108 starts each; strict-core endpoints",
 "alternatives": "core-definition artifact ruled out by the f sweep (res-9q2c)",
 "confirmed_at": "1f3c9e0...",
 "links": [{"rel": "derived-from", "to": "res-9q2c"}, {"rel": "answers", "to": "q-b7r1"},
           {"rel": "contradicts", "to": "hyp-2wde"}],
 "log": [{"date": "2026-10-23", "author": "claude", "event": "add", "to": "pending"},
         {"date": "2026-10-24", "author": "user", "event": "confirm", "from": "pending", "to": "supported"}]}
```

### Common fields

| Field | Type | Rule |
|---|---|---|
| `id` | string | Required. See [IDs](#ids). Unique. |
| `type` | string | Required. One of the types below. |
| `title` | string | Required, one line. For claims (hypothesis, conclusion, lead, decision) the title is the claim itself. |
| `author` | `user` \| `claude` | Required. Set by `nb`, never by a flag. |
| `created`, `updated` | date | Required. Set by `nb`. |
| `status` | string | Required for every type except `audit`. Allowed values per type below. |
| `body` | string | Free markdown: context, details, links to notebook entries. |
| `refs` | list of strings | Opaque references: foam issue ids, URLs, paths, W&B runs. Stored, never parsed. |
| `tags` | list of strings | Free filtering labels (protein, run family, method). Changeable on any node; `nb query --tag`. |
| `links` | list of `{rel, to}` | Outgoing edges. See [Edges](#edges). |
| `log` | list of entries | Append-only history: `{date, author, event, from?, to?, reason?}`. Every status change and every change to a field after creation adds one. |

Fields at their default (empty string, empty list, absent) are omitted.
Unknown fields are errors.

### Types

| Type | Statuses (initial first) | Type fields |
|---|---|---|
| `goal` | pending, active, superseded, rejected | none |
| `question` | open, answered, settled, parked, abandoned | none |
| `hypothesis` | open, supported, refuted, superseded | `prediction` (required): what should be observed if it holds |
| `experiment` | draft, frozen, done, abandoned | see below |
| `exploration` | draft, frozen, done, abandoned | see below |
| `result` | valid, invalidated | `summary` (required, facts only), `provenance`, `metrics` |
| `conclusion` | pending, supported, refuted, superseded, rejected | `rationale`, `scope`, `alternatives` (all required); `confidence` (`low` \| `medium` \| `high`); `confirmed_at` |
| `lead` | pending, active, followed, dropped | `rationale` (required) |
| `decision` | pending, active, superseded, rejected | `rationale` (required), `rejected` (list: alternatives considered and not taken), `revisit_if` |
| `audit` | none | `verdict` (`sound` \| `concerns` \| `unsound`), `findings` (required), `auditor`, `audited_at` |

`goal`, `conclusion`, `lead` and `decision` start `pending` when authored by
Claude and established (`active`, `supported`, `active`, `active`) when
authored by the user. A lead that was taken up is `followed` (it raised a
question or spawned a hypothesis); whether it panned out is told by the
conclusions downstream, not by the lead.

**Experiment and exploration** share one schema. The difference is the
evidence tier: an exploration looks at data without a hypothesis and can only
suggest leads; an experiment tests hypotheses and its results can back
conclusions. Analysis decided on after an experiment was frozen, even on that
experiment's data, is a new exploration (or a new experiment with its own
frozen predictions) that `uses` the earlier result. It is not a deviation and
not another result of the frozen experiment.

| Field | Type | Rule |
|---|---|---|
| `retrospective` | bool | Set only at creation (`nb add experiment --retro`). The spec and predictions were written after the results existed, e.g. when backfilling a project. Freezing still applies, but everything built on it is marked `retro` in `show`, `context`, `path` and `prime`. |
| `spec` | string | What will be done, on what data, with what command or procedure. Required to freeze. |
| `execution` | `command` \| `analysis` \| `manual` | Required to freeze. `command`: training, sampling, batch jobs. `analysis`: a script or notebook over existing data. `manual`: wet lab, external tools, human input. |
| `predictions` | list of `{hypothesis, prediction, metric, decision_rule}` | Experiment only. At least one to freeze, all four keys non-empty. One entry per tested hypothesis; a sweep or a controlled arm is part of the spec, not a separate experiment. |
| `spec_hash` | string | Set by `freeze`: sha256 of the canonical JSON of `title`, `spec`, `execution`, `predictions`. |
| `frozen_at` | string | Set by `freeze`: the notebook version at freezing. |
| `deviations` | list of `{date, author, text}` | Append-only after freezing: anything done differently from the spec, and why. |
| `runs` | list of `{date, command, commit, dirty, cwd}` | Run attempts, appended by the run hook (phase 3). Shown next to results so that "1 result from 4 runs" is visible. |

**Result** `provenance` is an object, captured automatically where possible:

| Key | Source |
|---|---|
| `commit` | `git rev-parse HEAD`, unless `--commit` is given |
| `dirty` | true if tracked files differ from `HEAD` |
| `cwd` | the working directory, relative to the repo root |
| `run_dir` | `--run-dir` |
| `external_ids` | `--ext-id`, repeatable (W&B run ids, MLflow ids, job ids) |
| `artifacts` | `--artifact`, repeatable (paths relative to the repo root, or URLs) |

`metrics` is an optional JSON object loaded with `--metrics FILE` (the file
path is added to `artifacts`). It may nest, e.g. one entry per protein or per
arm. It exists so that numbers can come from a file the run wrote rather than
being typed by hand.

### Edges

Edges are stored in the `links` of the node they start from. The CLI keeps
`tests` links and `predictions` in step: every prediction's hypothesis has a
`tests` link and every `tests` link has a prediction.

| rel | from | to |
|---|---|---|
| `refines` | question | goal, question |
| `addresses` | hypothesis | question |
| `tests` | experiment | hypothesis |
| `investigates` | exploration | question |
| `produces` | experiment, exploration | result |
| `derived-from` | conclusion | result |
| `suggested-by` | lead | result, source |
| `answers` | conclusion | question |
| `raises` | lead | question |
| `spawns` | lead | hypothesis |
| `supports`, `contradicts` | result, conclusion, source | hypothesis, conclusion |
| `audits` | audit | conclusion |
| `supersedes` | goal, hypothesis, conclusion, decision | same type |
| `variant-of` | experiment, exploration | same type |
| `uses` | experiment, exploration | result (existing data it analyses) |
| `based-on` | decision | result, conclusion |
| `affects` | decision | goal, question, hypothesis, experiment, exploration |

No self-edges, no duplicate edges, and no cycles in `refines`, `supersedes`
or `variant-of`.

**Supersession** has no command of its own. A node added with a `supersedes`
link takes effect when it becomes established: immediately for user-authored
nodes and for hypotheses, on `nb confirm` for Claude-authored ones. At that
point the old node's status becomes `superseded`, with a log entry.

**Adding links later.** Links are append-only: any node may gain outgoing
links after creation, so a lead can spawn a hypothesis created after it and a
decision can affect a later experiment. The exceptions are the links that are
the basis of a claim or a frozen design: `derived-from` and `supersedes` on an
established node, `tests` on a frozen experiment, `produces` (only through
`nb result`), and anything on an audit. A result may gain only `supports` and
`contradicts` links. Every added link is logged with its author.

## Rules enforced on write

`nb` refuses a write that breaks any of these. `nb lint` re-checks all of
them on the whole graph, because a merge or a hand-made commit can bypass the
CLI.

- **Schema.** Required fields per type and status, field types, allowed
  statuses, the edge table above.
- **Required structure at creation.** A question `refines` something. A
  hypothesis `addresses` a question. An exploration `investigates` a
  question. A conclusion has at least one `derived-from`. A lead has at least
  one `suggested-by`. An audit `audits` exactly one conclusion.
- **Freezing** (`nb freeze`) requires `spec`, `execution`, and a path to an
  active goal; for an experiment also at least one complete prediction.
- **Frozen specs are immutable.** After freezing, `title`, `spec`,
  `execution` and `predictions` cannot change. Only `deviations`, `runs`,
  `body`, `refs`, `tags`, links (see above) and status may change. A
  deviation is a change to the procedure (a run killed and restarted, a
  different seed count); a new analysis is a new node.
- **Results** are added only to a frozen experiment or exploration (`nb
  result` adds the result and the `produces` link). A result's fields never
  change; `nb invalidate` sets it `invalidated` with a required reason.
- **Conclusions** must derive from at least one valid result produced by an
  experiment. Results of explorations may be listed as context but cannot be
  the only basis. Leads may be suggested by results of either tier.
- **Established claims are append-only.** A `supported` conclusion, an
  `active` decision or goal changes only by supersession or a status change
  with a reason; its other fields are frozen except `body`, `refs` and
  `tags`. To reword an active goal, add a new goal that supersedes it.
- **Status changes need evidence where they assert something.** A hypothesis
  becomes `supported` or `refuted` only if a `supported` conclusion
  `supports` or `contradicts` it. A question becomes `answered` only if a
  `supported` conclusion `answers` it, and `settled` only if an `active`
  decision `affects` it: `answered` means the project found out, `settled`
  means it chose without establishing a fact. `abandoned`, `parked`, `dropped`,
  `rejected` and an experiment's `abandoned` need `--reason`. An experiment
  becomes `done` only if it has produced at least one result.
- **Audits** are immutable once added. An audit never changes the audited
  conclusion; a `concerns` or `unsound` verdict appears in `prime` and `lint`
  for the user to act on.
- **Unlinking** is allowed only while the source node is in its initial
  status (draft, open, pending), and never for the required links above.

## Authorship

`author` is `claude` when the environment has `CLAUDECODE` set (Claude Code
sets it in every Bash tool call) and `user` otherwise. There is no flag or
variable to override it.

This is a guard against a well-meaning agent, not an adversary. The gate hook
(phase 2) also asks before any command that unsets `CLAUDECODE`.

## Gated commands

These commands turn a proposal into an established fact or change the rules,
so when Claude runs them the user must approve:

| Command | Why |
|---|---|
| `nb freeze` | Approving an experiment design. Claude cannot approve its own, so it cannot chain experiments. |
| `nb confirm` | Making a pending goal, conclusion, lead or decision established. |
| `nb invalidate` | Withdrawing a result. |
| `nb config set` | Changing thresholds and run-gating patterns. |

Plugins cannot ship permission rules, so the gate is a plugin PreToolUse hook
(`hooks/gate.py`) that returns `ask` for these commands. A user running `nb`
in their own terminal is not prompted.

## Lint

`nb lint` prints `error ...` and `warn ...` lines and exits 1 if there are
errors, 0 otherwise (`--json` gives a list). Beyond re-checking the write
rules:

| Check | Level |
|---|---|
| Dangling edge, edge type mismatch, cycle | error |
| A frozen experiment's `spec_hash` does not match its fields | error |
| A draft or frozen experiment or exploration has no path to an active goal (the goal was superseded under it) | error |
| A `supported` conclusion derives from an invalidated result | error |
| **Drift:** an experiment or exploration whose lineage passes through `drift_leads` or more leads | warn |
| A `supported` conclusion has a `contradicts` from a node added after `confirmed_at` | warn |
| A `supported` conclusion has an audit with verdict `concerns` or `unsound` | warn |
| A `supported` conclusion has fewer than `min_results_supported` derived-from results | warn |
| A `supported` or `refuted` hypothesis, or an `answered` question, no longer has a `supported` conclusion behind it (it was superseded or refuted); a `settled` question no longer has an `active` decision | warn |
| An `open` question has no path to an active goal (its goal was superseded and it was not re-linked, parked or abandoned) | warn |
| A pending node is older than `pending_days` | warn |
| A result's provenance commit is not reachable from any ref (squashed or deleted branch) | warn |
| A result backing a `supported` conclusion has an artifact path that no longer exists | warn |

**Path to a goal** follows these edges upward: result → (produced by)
experiment or exploration; experiment → `tests` → hypothesis; exploration →
`investigates` → question; hypothesis → `addresses` → question; question →
`refines` → question or goal. `nb path <id>` prints every such path.

**Lineage** follows how ideas came about: a hypothesis `spawned` by a lead,
or a question `raised` by a lead, comes from that lead; the lead comes from
the results it is `suggested-by`; a result comes from the experiment that
produced it, which comes from the hypotheses it tests or the question it
investigates. The drift count of a node is the largest number of leads on any
lineage chain behind it. A long chain of leads is how a rabbit hole looks in
the graph: each step was suggested by the last, and none was asked for by the
goal.

## Config

Stored in `meta.json`, read with `nb config get [key]`, changed with
`nb config set <key> <value>` (gated).

| Key | Default | Meaning |
|---|---|---|
| `prime_max_chars` | 4000 | Hard cap on `nb prime` output. |
| `prime_section_limit` | 5 | Items per prime section before "(+N more)". |
| `pending_days` | 7 | Age at which a pending node is a lint warning. |
| `drift_leads` | 2 | Leads on a lineage chain before a drift warning. |
| `min_results_supported` | 1 | Derived-from results a supported conclusion should have. |
| `run_patterns` | [] | Phase 3: regexes for commands that launch runs. |

## Prime

`nb prime` prints a capped briefing for the start of a session. It loads by
default (SessionStart hook); everything else is pulled on demand with `show`,
`context`, `path` and `query`. Order:

```text
# lab-notebook
This repo's research record (nb): goals, questions, experiments, results, conclusions.
foam holds work and how-to facts; nb holds what the project found and why. Use nb context/path/query for more.

## Goals
goal-3kd2  Condition BioEmu on endpoints and committor to sample the TSE
## Awaiting the user (pending, not established)
con-8fz1  Run-1 ControlNet ignores q direction        claude, 2026-10-28
## In flight (frozen)
exp-q9w4  ControlNet run 2 on villin holdout           frozen 2026-10-27, 0 results, 1 run
## Open questions
q-m2a7    Does a ControlNet fine-tune sample the TSE at the requested q?
## Recent conclusions
con-4mxa  BioEmu2 propagation committors are worse than a constant predictor
## Active leads
lead-7tq1 The +0.3 folding bias comes from the starting structures
## Lint: 0 errors, 2 warnings (nb lint)
```

Sections: active goals; pending nodes; frozen experiments and explorations
with result and run counts; open questions under active goals, most recent
first; supported conclusions, most recently confirmed first; active leads;
lint counts. Conclusions show their `confidence`, and anything resting on a
retrospective experiment is marked `retro`. Each section shows at most `prime_section_limit` items and then
`(+N more: nb query ...)`. Empty sections are omitted. If the output would
exceed `prime_max_chars`, later sections are cut to a single count line. Pending nodes
appear only under "Awaiting the user". Outside a repository with a notebook,
`nb prime` prints nothing and exits 0.

`--hook-json` wraps the text as
`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}`.

## CLI

Every read command takes `--json`. Errors go to stderr as `nb: <message>` (or
`{"error": "<message>"}` with `--json`) and exit 1; usage errors exit 2.

Within a minor version, `--json` output only gains keys; existing keys keep
their names and types.

### Write

| Command | Effect |
|---|---|
| `nb init` | Create the ref if absent; add the fetch refspec and pre-push block if `origin` exists. Idempotent. |
| `nb add <type> <title> [--body TEXT\|-] [--ref R]... [--tag T]... [--link REL:ID]... [type flags]` | Create a node; print its id. Type flags: `--prediction` (hypothesis); `--spec`, `--exec`, `--retro` (experiment), `--spec`, `--exec` (exploration); `--rationale`, `--scope`, `--alternatives`, `--confidence`, `--from RES`... (conclusion: `derived-from`); `--rationale`, `--from RES`... (lead: `suggested-by`); `--rationale`, `--reject ALT`..., `--revisit-if` (decision); `--of CON`, `--verdict`, `--findings`, `--auditor` (audit). A flag shown with `...` is repeated once per value. |
| `nb predict <exp> <hyp> --prediction P --metric M --rule R` | Add a prediction and the `tests` link (draft only). |
| `nb link <from> <rel> <to>` / `nb unlink <from> <rel> <to>` | Add or remove an edge. |
| `nb set <id> <field> <value>` | Change a mutable field. `--append` adds to a list field. |
| `nb status <id> <status> [--reason R]` | Change status, subject to the rules above. |
| `nb freeze <id>` | Freeze an experiment or exploration. Gated. |
| `nb deviate <id> <text>` | Record a deviation on a frozen experiment or exploration. |
| `nb result <exp> <summary> [--run-dir D] [--artifact P]... [--ext-id X]... [--metrics FILE] [--commit SHA] [--tag T]... [--link supports\|contradicts:ID]...` | Record a result with provenance; print its id. |
| `nb confirm <id>` | Establish a pending node; apply its supersessions. Gated. |
| `nb reject <id> --reason R` | Reject a pending node (`rejected`, or `dropped` for a lead). |
| `nb invalidate <res> --reason R` | Invalidate a result. Gated. |
| `nb config set <key> <value>` | Change config. Gated. |

### Read

| Command | Output |
|---|---|
| `nb show <id>` | The node with its outgoing and incoming edges. |
| `nb prime [--hook-json] [--max-chars N]` | See [Prime](#prime). |
| `nb context <id> [--depth N]` | The node plus its neighbourhood (default depth 1, both directions), one line per node. |
| `nb path <id>` | Every path to a goal, and the lineage with leads marked. |
| `nb pending` | Pending nodes awaiting the user. |
| `nb query [--type T] [--status S] [--author A] [--tag T] [--since DATE] [--text S] [--all]` | Matching nodes, newest first, 50 unless `--all`. |
| `nb log [-n N]` | Recent notebook commits. |
| `nb config get [key]` | Config values. |

### Repository

| Command | Effect |
|---|---|
| `nb lint` | See [Lint](#lint). |
| `nb sync` | See [Sync](#sync). |

## Claude Code integration

Phase 2:

- **SessionStart** runs `nb prime --hook-json`.
- **PreToolUse** on Bash, `"if": "Bash(nb *)"`, runs `hooks/gate.py`. It
  splits the command into simple commands (`&&`, `||`, `;`, `|`, newlines),
  finds `nb` invoked by name or path, and returns `permissionDecision: "ask"`
  with a one-line reason for gated commands and for any command that unsets
  `CLAUDECODE`. Everything else passes through unchanged.
- **Skill** `lab-notebook`: when and how to record, the rules above in short,
  and a command cheat sheet. Its `allowed-tools` pre-approves read commands
  only.

## Later phases (not specified yet)

- **Run gating (phase 3).** A PreToolUse hook blocks commands matching
  `run_patterns` unless prefixed with `NB_EXP=<frozen id>` or `NB_SCRATCH=1`.
  A PostToolUse hook appends a run attempt to the experiment and injects:
  report the facts first, a brief read clearly labeled as such is fine,
  record no conclusions or leads, launch nothing further without asking.
- **Design and interpret skills (phase 4)**, with `nb review <exp>`
  (structural checks: path to goal, redundancy, contradicting conclusions,
  ignored leads, `kt check` on relied-on concepts) and `nb similar`
  (structural keys first: same hypothesis and metric, variant-of chains,
  spec hash; title word overlap only as a fallback).
- **Reviewer subagent and `nb audit <id>` bundle (phase 5)**, then `source`
  nodes holding a citation key that must resolve in Zotero.

## Deliberately not decided yet

- Whether conclusion-strength rules should ever block rather than warn.
- Whether `prime` should rank open questions by activity instead of recency.
