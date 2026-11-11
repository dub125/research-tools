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
- A hypothesis is decided by the rule frozen with its experiment, not by a
  conclusion. A **verdict** (supported, refuted, inconclusive) is recorded with
  the result and applies at once, because the user approved the rule when
  freezing. Conclusions are for interpretation: what results add up to,
  across runs or beyond one rule.
- Every result is **reviewed** with the user: a conclusion or lead drawn from
  the user's own read, or "nothing yet". While the freeze gate is on, nothing
  new is frozen while a result is unreviewed or an experiment is missing
  verdicts. See [Closing the loop](#closing-the-loop).

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
retries after a short random wait (up to 30 times). There is no lock and no daemon. The commit message is
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

`meta.json` carries `schema` (an integer, currently 2). `nb` migrates an older
schema in memory and writes the new one on the next write. It refuses a ref
whose schema is newer than it knows. Adding an optional field with a default
does not bump the schema; renaming, restructuring or adding a required field
does, with a migration function in `bin/nb`.

Schema 2 derives a hypothesis's status from the set of its verdicts instead
of the most recent one, and adds the `contested` status (see
[Hypothesis status](#hypothesis-status)). Migrating from schema 1 recomputes
every hypothesis that has a verdict, with a `migrate` log entry for each one
that changes. An `nb` from before schema 2 refuses the notebook, so update the
plugin on every machine before syncing.

The verdict, review and audit additions are optional fields and need no
bump. In a notebook from before them: done experiments without verdicts are
a lint warning until backfilled with `nb verdict`; every existing result
counts as unreviewed, so `freeze_gate` stays off until the backlog is
reviewed; conclusions and leads without `origin` stay valid.

### Sync

`nb sync` exchanges the notebook with the `origin` remote:

1. `git fetch origin +refs/notebook/data:refs/notebook/origin`.
2. If one side contains the other, fast-forward. Otherwise merge three-way
   against `git merge-base`, node by node:
   - a node changed on one side only takes that side;
   - a node changed on both sides is merged field by field. Append-only lists
     (`log`, `links`, `refs`, `tags`, `deviations`, `runs`, `verdicts`,
     `reviews`) are merged as sets: an entry either side added is kept, an
     entry either side removed (`unlink`, `retract`) stays removed, in base
     order and then each side's new entries. Both sides adding a verdict for
     the same hypothesis is a conflict. A scalar changed on one side
     takes that side. A scalar changed differently on both sides is a
     conflict, except derived statuses (hypothesis status, an experiment's
     `frozen`/`done`), which are recomputed from the merged graph.
     Fields fixed at creation (`interim`, `origin`, `user_words`) cannot
     differ.
3. On any conflict, or if the merged graph fails validation, nothing is
   written and `nb sync` lists the nodes and fields. Resolve by changing one
   side with `nb` and syncing again.
4. Commit the merge with both parents, then
   `git push origin refs/notebook/data:refs/notebook/data`. Retry from step 1
   up to 3 times if the push is rejected.

`nb init` adds the fetch refspec to `origin` and appends a delimited block to
`.git/hooks/pre-push` that runs `nb sync` (skipped when `NB_IN_HOOK` is set,
never failing the code push). An existing hook, such as foam's, is kept. A
fresh clone needs `nb init` before the notebook is visible; in a clone, `nb
init` adopts origin's notebook instead of starting a new one. `nb sync`
pushes with `--no-verify`, so it does not run other pre-push hooks.

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
| `title` | string | Required, one line. For claims (hypothesis, conclusion, lead, decision) the title is the claim itself. A conclusion or lead makes **one claim**: something that could be true or false on its own. "A, but B, so C" is three conclusions. Not enforced by `nb` (it cannot tell); the auditor checks it. |
| `author` | `user` \| `claude` | Required. Set by `nb`, never by a flag. |
| `created`, `updated` | date | Required. Set by `nb`. |
| `status` | string | Required for every type except `audit`. Allowed values per type below. |
| `body` | string | Free markdown: context, details, links to notebook entries. |
| `refs` | list of strings | Opaque references: foam issue ids, URLs, paths, W&B runs. Stored, never parsed. |
| `tags` | list of strings | Free filtering labels (protein, run family, method). Changeable on any node; `nb query --tag`. |
| `links` | list of `{rel, to}` | Outgoing edges. See [Edges](#edges). |
| `log` | list of entries | Append-only history: `{date, author, event, from?, to?, field?, reason?}`. Every status change and every change to a field after creation adds one. |

Fields at their default (empty string, empty list, absent) are omitted.
Unknown fields are errors.

### Types

| Type | Statuses (initial first) | Type fields |
|---|---|---|
| `goal` | pending, active, superseded, rejected | none |
| `question` | open, answered, settled, parked, abandoned | none |
| `hypothesis` | open, supported, refuted, contested, superseded | `prediction` (required): what should be observed if it holds |
| `experiment` | draft, frozen, done, abandoned | see below |
| `exploration` | draft, frozen, done, abandoned | see below |
| `result` | valid, invalidated | `summary` (required, facts only), `provenance`, `metrics`, `interim` (bool), `reviews` (see [Review](#review)) |
| `conclusion` | pending, supported, refuted, superseded, rejected | `rationale`, `scope`, `alternatives` (all required); `confidence` (`low` \| `medium` \| `high`); `confirmed_at`; `origin`, `user_words` (see below) |
| `lead` | pending, active, followed, dropped | `rationale` (required); `origin`, `user_words` (see below) |
| `decision` | pending, active, superseded, rejected | `rationale` (required), `rejected` (list: alternatives considered and not taken), `revisit_if` |
| `audit` | none | `verdict` (`sound` \| `concerns` \| `unsound`), `findings` (required), `auditor`, `audited_at` |

`goal`, `conclusion`, `lead` and `decision` start `pending` when authored by
Claude and established (`active`, `supported`, `active`, `active`) when
authored by the user. A lead that was taken up is `followed` (it raised a
question or spawned a hypothesis, experiment or exploration); whether it panned out is told by the
conclusions downstream, not by the lead.

**Origin of a conclusion or lead.** `origin` is `user` when it was drafted
from the user's own read, and `claude` when it is Claude's read, given because
the user asked for it. `user_words` holds the user's read verbatim and is
required when `origin` is `user`. Both are required at creation for a
Claude-authored conclusion or lead (older nodes without them stay valid), and
both are fixed once set. A user-authored node needs neither. The confirm prompt,
`show` and `prime` display the origin, so the user can always tell their own
reading from Claude's. A conclusion does not need to answer a question:
`answers` is optional, and findings that turned up along the way are
conclusions like any other.

**Interim results.** `nb result --interim` records a partial result (a run
stopped part-way, a first batch). It carries no verdicts, does not close
anything and is not reviewed on its own; the final result is.

**Experiment and exploration** share one schema. The difference is the
evidence tier: an exploration looks at data without a hypothesis and can only
suggest leads; an experiment tests hypotheses and its results can back
conclusions. Analysis decided on after an experiment was frozen, even on that
experiment's data, is a new exploration (or a new experiment with its own
frozen predictions) that `uses` the earlier result. It is not a deviation and
not another result of the frozen experiment.

**What a design builds on.** An experiment or exploration that changes an
earlier one is `variant-of` it ("run 19 = run 18 with mean loss"). One that
uses another's outputs, such as its trained checkpoint or the dataset it
generated, `uses` that experiment or exploration, even before it has results
("two-state check of run 19 `uses` run 19"). One that analyses an existing
result `uses` that result. Work that builds on nothing in the notebook is
marked `fresh` (`nb add ... --fresh`, or `nb set <id> fresh true` while
draft). Freezing requires at least one of these, so lineage is stated when the
design is approved rather than reconstructed later.

| Field | Type | Rule |
|---|---|---|
| `fresh` | bool | Builds on nothing in the notebook; see above. Settable while draft. |
| `retrospective` | bool | Set only at creation (`nb add experiment --retro`). The spec and predictions were written after the results existed, e.g. when backfilling a project. Freezing still applies, but everything built on it is marked `retro` in `show`, `context`, `path` and `prime`. |
| `spec` | string | What will be done, on what data, with what command or procedure. Required to freeze. |
| `execution` | `command` \| `analysis` \| `manual` | Required to freeze. `command`: training, sampling, batch jobs. `analysis`: a script or notebook over existing data. `manual`: wet lab, external tools, human input. |
| `predictions` | list of `{hypothesis, prediction, metric, decision_rule}` | Experiment only. At least one to freeze, all four keys non-empty. One entry per tested hypothesis; a sweep or a controlled arm is part of the spec, not a separate experiment. |
| `spec_hash` | string | Set by `freeze`: sha256 of the canonical JSON of `title`, `spec`, `execution`, `predictions`. |
| `frozen_at` | string | Set by `freeze`: the notebook version at freezing. |
| `deviations` | list of `{date, author, text}` | Append-only after freezing: anything done differently from the spec, and why. |
| `runs` | list of `{date, command, commit, dirty, cwd}` | Run attempts, appended by the run hook (phase 3). Shown next to results so that "1 result from 4 runs" is visible. |
| `verdicts` | list of `{hypothesis, verdict, result, basis, date, at, author, replaces?, reason?}` | Experiment only. Append-only history, written only by `nb result --verdict` and `nb verdict`. `verdict` is `supported`, `refuted` or `inconclusive`; `result` is the result it was judged on; `basis` is the measured value and the bound it was compared to (`jsd_tp 0.312 >= 0.295`). A replacement is a new entry with `replaces: true` and a `reason`. `at` is the UTC time of the write (`YYYY-MM-DDTHH:MM:SSZ`), kept as a record; no status depends on it. The **current** verdict for a hypothesis is its last entry whose result is still valid. See [Verdicts](#verdicts). |

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
| `spawns` | lead | hypothesis, experiment, exploration |
| `supports`, `contradicts` | result, conclusion, source | hypothesis, conclusion |
| `audits` | audit | conclusion, lead |
| `supersedes` | goal, hypothesis, conclusion, decision | same type |
| `variant-of` | experiment, exploration | same type |
| `uses` | experiment, exploration | result (existing data it analyses); experiment, exploration (its outputs: a checkpoint, a dataset) |
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
  one `suggested-by`. An audit `audits` exactly one conclusion or lead. A
  Claude-authored conclusion or lead has an `origin` (and `user_words` when
  the origin is `user`). This is checked at creation only, so older nodes
  without them stay valid.
- **Freezing** (`nb freeze`) requires `spec`, `execution`, and a path to an
  active goal; for an experiment also at least one complete prediction; and
  at least one `variant-of` or `uses` link, or `fresh` (see "What a design
  builds on" under [Types](#types)). While
  `freeze_gate` is on it also requires a clear [freeze gate](#the-freeze-gate).
- **Frozen specs are immutable.** After freezing, `title`, `spec`,
  `execution` and `predictions` cannot change. Only `deviations`, `runs`,
  `verdicts` (through the verdict commands only), `body`, `refs`, `tags`,
  links (see above) and status may change. A
  deviation is a change to the procedure (a run killed and restarted, a
  different seed count); a new analysis is a new node.
- **Results** are added only to a frozen experiment or exploration (`nb
  result` adds the result and the `produces` link). A result's fields never
  change, except that `reviews` is appended to by `nb confirm`, `nb add` (a
  user-authored conclusion or lead) and `nb nothing-yet`; `nb invalidate` sets
  it `invalidated` with a required reason. Invalidating a result withdraws the
  verdicts judged on it (see [Verdicts](#verdicts)). A `done` experiment takes
  no more results: a rerun is a new experiment, `variant-of` the old one,
  with its own frozen design.
- **Conclusions** must derive from at least one valid result produced by an
  experiment. Results of explorations may be listed as context but cannot be
  the only basis. Leads may be suggested by results of either tier.
- **Established claims are append-only.** A `supported` conclusion, an
  `active` decision or goal changes only by supersession or a status change
  with a reason; its other fields are frozen except `body`, `refs` and
  `tags`. To reword an active goal, add a new goal that supersedes it.
- **Status changes need evidence where they assert something.** A
  hypothesis's status follows [hypothesis status](#hypothesis-status) and is
  not set by `nb status` except to `superseded`. A pending goal, conclusion,
  lead or decision leaves `pending` only through `nb confirm` or `nb reject`,
  never `nb status`. A question becomes `answered` only if a
  `supported` conclusion `answers` it, and `settled` only if an `active`
  decision `affects` it: `answered` means the project found out, `settled`
  means it chose without establishing a fact. `abandoned`, `parked`, `dropped`,
  `rejected` and an experiment's `abandoned` need `--reason`. An experiment
  becomes `done` automatically when every predicted hypothesis has a current
  verdict, and not otherwise. An exploration becomes `done` by `nb status`
  once it has at least one result, as before. A `done` experiment returns to
  `frozen` if invalidation withdraws one of its verdicts (logged).
- **Audits** are immutable once added. An audit never changes the audited
  conclusion or lead; a `concerns` or `unsound` verdict appears in `prime` and
  `lint` for the user to act on; only the latest audit of a node counts. While
  `audit_before_confirm` is on, a Claude-authored conclusion or lead cannot be
  confirmed unless its latest audit is **current**: the node's own fields,
  other than `tags`, `refs` and `log`, are unchanged since that audit's
  `audited_at`.
- **Unlinking** is allowed only while the source node is in its initial
  status (draft, open, pending), and never for the required links above.
  A mistaken `supports` or `contradicts` link on any node (a result, an
  established conclusion) is removed with `nb retract`, which is gated and
  records the reason in the node's log. Removing a link that a node requires
  is refused like any other write that introduces a validation error.

## Closing the loop

A result goes through three steps before the project moves on: its
experiment's hypotheses get verdicts, the user reviews it, and anything
concluded from it is audited and confirmed. The freeze gate makes sure none
of these is skipped.

```text
nb result --verdict ...   ->  hypotheses supported/refuted, experiment done   (automatic)
nb brief <res>            ->  facts shown, user gives their read
  conclusion/lead drafted from the user's words  ->  audit  ->  nb confirm   (gated)
  or: nb nothing-yet <res>                                                  (gated)
```

### Verdicts

A verdict applies an experiment's frozen decision rule to a result. It is
recorded with the result (`nb result <exp> ... --verdict <hyp> <verdict>
<basis>`, once per predicted hypothesis) or added later (`nb verdict`).

- Only an experiment's predicted hypotheses get verdicts, and only from a
  valid, non-interim result of that experiment. Explorations have none. If any
  `--verdict` names a hypothesis the experiment does not predict, or is
  otherwise invalid, the whole `nb result` is refused.
- `basis` is required: the measured value and the bound from the rule
  (`jsd_tp 0.312 >= 0.295; refuted band`). The value must appear in the
  result's summary or metrics; `nb` checks only that `basis` is non-empty, and
  the auditor sweep checks the rest.
- The verdict applies at once (see [hypothesis status](#hypothesis-status)).
  When every predicted hypothesis has a current verdict, the experiment
  becomes `done`.
- Adding a verdict for a hypothesis that has no current verdict from this
  experiment is not gated; that is the normal, automatic path, used late only
  for backfilling. Any second verdict for the same hypothesis from the same
  experiment, whether from the same result or another one, is a replacement:
  `nb verdict ... --replace --reason R`, gated, appended with `replaces: true`.
- Verdicts on a `retrospective` experiment are marked `retro` in `show`,
  `brief` and `audit`: the rule was written after the results existed.
- Invalidating a result withdraws its verdicts: they stop being current, and
  the hypothesis status and experiment status are recomputed.

### Hypothesis status

A hypothesis's status is derived, not stored by hand. It is a function of the
**set** of current verdicts on it, one per experiment that tests it. The order
in which verdicts were recorded, and the clocks of the machines that recorded
them, play no part.

- `superseded` once a newer hypothesis supersedes it. Verdicts no longer
  change it.
- Otherwise:

| Current verdicts | Status |
|---|---|
| none, or only `inconclusive` | `open` |
| at least one `supported`, no `refuted` | `supported` |
| at least one `refuted`, no `supported` | `refuted` |
| both `supported` and `refuted` | `contested` |

An inconclusive verdict never cancels a conclusive one, and one refuting
verdict against any number of supporting ones is `contested`: there is no
majority rule. `nb show <hyp>` lists which experiments are on each side.

A contested hypothesis is a lint warning and stays contested until the
evidence changes by an explicit act: `nb invalidate` a result that was flawed,
or supersede the hypothesis with a narrower one that the experiments agree on
("holds at 30k steps or more"). `nb` never picks a side.

`nb` recomputes the status after every write that adds or withdraws a verdict
(result, verdict, invalidate, sync) and logs each change with the tally that
caused it.

Verdicts are the only way a hypothesis is decided. A conclusion may link
`supports` or `contradicts` to a hypothesis, but confirming it does not change
the hypothesis; a hypothesis no experiment has tested is decided by designing
one (`--retro` if the results already exist).

Legacy: `nb confirm --also <hyp>` used to let a conclusion set a hypothesis's
status, stored as a `confirm-also` entry in the hypothesis's log. `nb` no
longer writes these and refuses the command. Each entry already in a notebook
counts as one vote, `supported` or `refuted`, alongside the verdicts.

### Review

Every valid, non-interim result is reviewed with the user. Reviews are
recorded in the result's `reviews` list, an append-only list of
`{date, author, kind, by?, note?}`; a result is **reviewed** once the list is
non-empty, and it stays reviewed whatever happens to the node that reviewed it
later (superseded, refuted, dropped). Entries are written by:

- `nb confirm` of a conclusion or lead: `kind: "confirmed"`, `by: <id>`, on
  every result it rests on (`derived-from` or `suggested-by`). A pending
  draft writes nothing, so the review finishes only when the user confirms; a
  rejected draft never writes one;
- `nb add` of a user-authored conclusion or lead, which is established at
  once: the same entry;
- `nb nothing-yet <res>... [--note N]`: `kind: "nothing-yet"`. Gated: only the
  user decides there is nothing to conclude.

A review covers whatever results the conclusion rests on, so one conclusion
drawn across five runs reviews all five. A result marked "nothing yet" can
still back a conclusion later. Results of abandoned experiments still need a
review ("nothing yet" is enough).

The review starts from [`nb brief`](#brief). Claude shows it, asks for the
user's read, and holds its own read until the user has given theirs or asked
for it. A conclusion drafted from the user's read has `origin: user` and the
user's words in `user_words`.

### The freeze gate

While `freeze_gate` is on, `nb freeze` is refused if any of these exist, and
the error lists them by id and title:

- a frozen experiment with a valid, non-interim result but a predicted
  hypothesis without a verdict;
- a valid, non-interim result that is not reviewed.

Experiments and explorations that are frozen but have no results yet do not
block: they are running in parallel. Interim results do not block, but an
experiment or exploration whose only results are interim and older than
`pending_days` is listed under "Needs closing" in `prime` and warned by
`lint`, so `--interim` cannot quietly hold work open. The gate is
enforced by `nb` itself, so it applies to the user's own `nb freeze` as well as
Claude's. `freeze_gate` defaults to off; a notebook with a backlog turns it on
once the backlog is reviewed.

### Brief

`nb brief <res>` prints what the user needs in order to draw a conclusion
from a result. It is built by fixed rules, so the same graph always gives the
same brief; Claude does not choose what goes in it. It follows links only and
does no text matching: a result that should appear but does not is a missing
link, fixed with `nb link`. Tiers, in order:

1. **This result:** its experiment, the verdicts judged on it with their
   basis, and its summary.
2. **Directly linked:** results of experiments on the same `variant-of` chain
   (both directions); `uses` in both directions, whether the link points at
   a result or at the experiment or exploration that produced it; and the
   results of other experiments testing the same hypotheses.
3. **Same question:** other results under the questions this result's
   hypotheses address or its exploration investigates.

Each item is one line: id, the name of the experiment or exploration that
produced it (its title, shortened), verdict and basis where there is one
(marked `retro` on a retrospective experiment), and review state
(`unreviewed`, `pending: <id>` when only a pending draft rests on it,
`nothing yet`, or the confirmed conclusion or lead that reviewed it). Interim
results are marked `interim`; invalidated results are left out of tiers 2-3.
`nb brief` on an interim or invalidated result works and says so in its
first line.
After the tiers come the established and pending conclusions and leads that
rest on any listed result, and the open questions involved. Each tier shows at
most `brief_tier_limit` items, most recent
first except the variant-of chain, which is in chain order, then
`(+N more: nb brief <res> --all)`. Nothing is left out silently.

```text
# Brief: res-0kbx  Run 19 (run 18 with mean loss and clip 12): villin jsd_tp 0.247 ...
experiment exp-9qe0 (done)  verdict hyp-yp39 supported: jsd_tp 0.247 in 0.227-0.267
## Directly linked
res-v0n5  Run 18: run 13 at 30k steps ...       hyp-68h6 supported   reviewed: nothing yet
res-8fe6  Two-state proteins with run 19 ...    (exploration)        unreviewed
## Same question (q-35qb: Does adding ONE_cath1 ...)
res-d148  Run 17: run 16 with 10k steps ...     hyp-qc5b refuted     unreviewed
(+4 more: nb brief res-0kbx --all)
## Conclusions and leads on these results
(none)
```

### Audit

`nb audit <con|lead>` prints the bundle an auditor needs, and nothing else:

- the node, including `origin` and `user_words`;
- every result it rests on, with summary, metrics and provenance;
- for each of those results, its experiment's frozen spec, predictions,
  decision rules, verdicts and deviations;
- the other results of those experiments that the node does not cite;
- results added to those experiments, or with links to the same hypotheses
  and questions, since the node was created;
- the other conclusions and leads on the same questions and hypotheses;
- the brief's linked tiers for each cited result.

The **auditor** is a subagent (`agents/nb-auditor.md`) with read-only tools
(`nb show`, `context`, `brief`, `audit`, `query` and file reads for artifacts).
It is given only the bundle, never the conversation, and it checks:

| Check | Question |
|---|---|
| backed | Is every number and claim in the title and rationale in a cited result? |
| rule-faithful | Do claims about hypotheses match the verdicts and the frozen rules? For a retrospective experiment, was the rule plausibly not fitted to the result? |
| scoped | Is the claim no broader than the data (`scope`)? |
| one claim | Is it one claim? |
| complete | Are uncited results of the same experiments, invalidated results and deviations accounted for? Searching the notebook itself (`nb query --text`), is there a relevant result the node ignores because it is not linked? Report it as a missing link. |
| consistent | Does it contradict a supported conclusion or a later result? |
| alternatives | Are obvious alternatives missing from `alternatives`? |
| faithful | For `origin: user`: does the draft add, drop or shift anything relative to `user_words`? |

It returns a verdict (`sound`, `concerns`, `unsound`) and findings, one line
per failed check. Claude records them with `nb add audit` (not gated: an
audit only adds a warning). The auditor's model is `auditor_model`.

`nb` cannot launch a subagent. It enforces only that a current audit exists
before `nb confirm` on a Claude-authored conclusion or lead
(`audit_before_confirm`); the skill has Claude run the auditor as soon as it
drafts one. A sweep (`/nb-audit`) audits every supported
conclusion; a cross-conclusion problem, such as two that contradict, is
recorded as an audit on the more recent one, citing the other.

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
| `nb confirm` | Making a pending goal, conclusion, lead or decision established, and marking the questions named with `--also` as answered. |
| `nb invalidate` | Withdrawing a result. |
| `nb retract` | Withdrawing a piece of evidence (a `supports` or `contradicts` link). |
| `nb verdict --replace` | Overriding how a frozen rule was applied. |
| `nb nothing-yet` | Closing a review without a conclusion; only the user can decide there is nothing to conclude. |
| `nb config set` | Changing thresholds, gates and run-gating patterns. |

Plugins cannot ship permission rules, so the gate is a plugin PreToolUse hook
(`hooks/gate.py`) that returns `ask` for these commands. A user running `nb`
in their own terminal is not prompted. (The freeze gate in
[Closing the loop](#the-freeze-gate) is separate: `nb` enforces it on every
writer.)

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
| A `supported` conclusion whose latest audit has verdict `concerns` or `unsound` | warn |
| A `supported` conclusion has fewer than `min_results_supported` derived-from results | warn |
| A verdict judged on an interim result, or on a result the experiment did not produce | error |
| A `done` experiment has a predicted hypothesis without a current verdict (expected in notebooks from before verdicts, until backfilled with `nb verdict`) | warn |
| An experiment or exploration whose only results are interim and older than `pending_days` | warn |
| A `supported` or `refuted` hypothesis has neither a verdict nor a `supported` conclusion behind it that agrees; an `answered` question no longer has a `supported` conclusion behind it (it was superseded or refuted); a `settled` question no longer has an `active` decision | warn |
| A hypothesis is `contested`: current verdicts from different experiments both support and refute it | warn |
| A valid, non-interim result has been unreviewed for more than `pending_days` (reported whether or not `freeze_gate` is on) | warn |
| A pending conclusion or lead whose latest audit has verdict `concerns` or `unsound` | warn |
| An `open` question has no path to an active goal (its goal was superseded and it was not re-linked, parked or abandoned) | warn |
| A pending node is older than `pending_days` | warn |
| A result's provenance commit is not reachable from any ref (squashed or deleted branch) | warn |
| A result backing a `supported` conclusion has an artifact path that no longer exists | warn |

**Path to a goal** follows these edges upward: result → (produced by)
experiment or exploration; experiment → `tests` → hypothesis; exploration →
`investigates` → question; hypothesis → `addresses` → question; question →
`refines` → question or goal. `nb path <id>` prints every such path.

**Lineage** follows how ideas came about: a hypothesis, experiment or
exploration `spawned` by a lead, or a question `raised` by a lead, comes from
that lead; the lead comes from
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
| `freeze_gate` | false | Enforce the [freeze gate](#the-freeze-gate). |
| `audit_before_confirm` | true | A Claude-authored conclusion or lead needs an up-to-date audit before `nb confirm`. |
| `auditor_model` | `sonnet` | Model the auditor subagent runs on. |
| `brief_tier_limit` | 8 | Items per brief tier before "(+N more)". |

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
con-8fz1  Run-1 ControlNet ignores q direction        claude, from your read, audit sound, 2026-10-28
## Needs closing
res-d148  Run 17: run 16 with 10k steps ...           unreviewed (hyp-qc5b refuted)
exp-maca  Run 14: run 13 with half the fast-folder draws   result in, verdict missing
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

Sections: active goals; pending nodes, with origin and audit verdict for
conclusions and leads; needs closing (unreviewed results and experiments
missing verdicts, oldest first, shown whether or not `freeze_gate` is on);
frozen experiments and explorations
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
| `nb add <type> <title> [--body TEXT\|-] [--ref R]... [--tag T]... [--link REL:ID]... [type flags]` | Create a node; print its id on stdout and `added <type> <id>: <title>` on stderr, so `$(nb add ...)` still captures the id and a reader sees what it is. Type flags: `--prediction` (hypothesis); `--spec`, `--exec`, `--retro` (experiment), `--spec`, `--exec` (exploration); `--rationale`, `--scope`, `--alternatives`, `--confidence`, `--from RES`..., `--origin user\|claude`, `--user-words TEXT\|-` (conclusion: `derived-from`); `--rationale`, `--from RES`..., `--origin`, `--user-words` (lead: `suggested-by`); `--rationale`, `--reject ALT`..., `--revisit-if` (decision); `--of ID`, `--verdict`, `--findings`, `--auditor` (audit). A flag shown with `...` is repeated once per value. |
| `nb predict <exp> <hyp> --prediction P --metric M --rule R` | Add a prediction and the `tests` link (draft only). |
| `nb link <from> <rel> <to>` / `nb unlink <from> <rel> <to>` | Add or remove an edge. |
| `nb set <id> <field> <value>` | Change a mutable field. `--append` adds to a list field. |
| `nb status <id> <status> [--reason R]` | Change status, subject to the rules above. |
| `nb freeze <id>` | Freeze an experiment or exploration; prints the id and title. Gated, and refused while the [freeze gate](#the-freeze-gate) is blocked. |
| `nb deviate <id> <text>` | Record a deviation on a frozen experiment or exploration. |
| `nb result <exp> <summary> [--interim] [--verdict HYP VERDICT BASIS]... [--run-dir D] [--artifact P]... [--ext-id X]... [--metrics FILE] [--commit SHA] [--tag T]... [--link supports\|contradicts:ID]...` | Record a result with provenance and apply its verdicts; print its id on stdout and the title, verdicts and any status changes on stderr. |
| `nb verdict <res> <hyp> <verdict> --basis B [--replace --reason R]` | Add a verdict judged on an existing result (backfilling), or replace one (`--replace`, gated). |
| `nb nothing-yet <res>... [--note N]` | Record that the user reviewed these results and has nothing to conclude yet. Gated. |
| `nb confirm <id> [--also <id>]...` | Establish a pending node; apply its supersessions; with `--also`, mark open questions the conclusion `answers` as `answered`. `nb show` on a pending conclusion lists the follow-ons available. A hypothesis is never a follow-on: it follows its verdicts. Gated; the prompt names each follow-on. |
| `nb reject <id> --reason R` | Reject a pending node (`rejected`, or `dropped` for a lead). |
| `nb invalidate <res> --reason R` | Invalidate a result. Gated. |
| `nb retract <from> supports\|contradicts <to> --reason R` | Remove a mistaken evidence link from any node; logged. Gated. |
| `nb config set <key> <value>` | Change config. Gated. |

### Read

| Command | Output |
|---|---|
| `nb show <id>` | The node with its outgoing and incoming edges. |
| `nb prime [--hook-json] [--max-chars N]` | See [Prime](#prime). |
| `nb context <id> [--depth N]` | The node plus its neighbourhood (default depth 1, both directions), one line per node. |
| `nb path <id>` | Every path to a goal, and the lineage with leads marked. |
| `nb pending` | Pending nodes awaiting the user, plus unreviewed results and experiments missing verdicts. |
| `nb brief <res> [--all]` | See [Brief](#brief). |
| `nb audit <con\|lead>` | The audit bundle; see [Audit](#audit). |
| `nb gate` | Whether `nb freeze` would pass the freeze gate now, and if not, what blocks it. |
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
- **PreToolUse** on every Bash call runs `hooks/gate.py` (no `if` filter:
  it would miss `nb` called by path and commands that unset `CLAUDECODE`; a
  call that mentions neither exits in about 30 ms). It scans the command
  text for `nb` invoked by name or path followed by a gated verb, and
  returns `permissionDecision: "ask"`. The reason shown to the user names the
  node and what approving it means: for `freeze`, the title, predictions,
  decision rules, and what the design builds on, by name ("variant of run 18;
  uses run 19's outputs", or "fresh"); for `confirm`, the claim, scope, confidence and who
  proposed it. It also asks for any command that unsets or overrides
  `CLAUDECODE`. A false match (the verb inside a quoted string) only costs an
  extra prompt. Everything else passes through with no output.
  For `freeze` it first runs `nb gate`; if the gate is blocked it returns
  `deny` with what blocks, rather than asking the user to approve a write `nb`
  would refuse. For `confirm` the reason also shows the origin, the user's
  words, the latest audit verdict with its findings, and each `--also`
  follow-on.
- **Skill** `lab-notebook`: when and how to record, the rules above in short,
  and a command cheat sheet. Its `allowed-tools` pre-approves read commands
  only. It sets how Claude talks about the graph: name a node by what it is
  first and give the id after ("run 17, the 10k-step version of run 16
  (exp-pb59)"), and never ask the user to decide about a bare id.
- **Agent** `nb-auditor` (`agents/nb-auditor.md`): see [Audit](#audit).
- **Command** `/nb-audit`: the audit sweep.

## Later phases (not specified yet)

- **Run gating (phase 3).** A PreToolUse hook blocks commands matching
  `run_patterns` unless prefixed with `NB_EXP=<frozen id>` or `NB_SCRATCH=1`.
  A PostToolUse hook appends a run attempt to the experiment and injects:
  report the facts first; record the result with its verdicts under the
  frozen rule; show `nb brief` and ask for the user's read, holding Claude's own
  read until the user has given theirs or asked for it; launch nothing further
  without asking.
- **Design skill (phase 4)**, with `nb check <exp>` (structural checks on a
  draft design: path to goal, redundancy, contradicting conclusions, ignored
  leads, `kt check` on relied-on concepts). There is no `nb similar`: related
  work is found through links, and the auditor searches for missing ones.
- `source` nodes holding a citation key that must resolve in Zotero.

## Deliberately not decided yet

- Whether conclusion-strength rules should ever block rather than warn.
- Whether `prime` should rank open questions by activity instead of recency.
- Whether a design may declare at freeze that it replaces an earlier
  experiment as the test of a hypothesis, so that a better rerun does not
  leave the hypothesis `contested`.
