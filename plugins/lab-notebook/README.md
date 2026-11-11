# lab-notebook

A research record for a project you work on with Claude Code. It keeps track
of what the project is trying to find out, which experiments you ran, what
they showed and what you concluded, so that you can trace a conclusion back
to the experiments behind it.

It is a Claude Code plugin with a command-line tool, `nb`. The full format
and rules are in [SPEC.md](SPEC.md).

## What it is for

The table lists the problems the notebook is built for and what it does
about each.

| Problem | What the notebook does |
|---|---|
| Experiment chaining: each run suggests the next, and the work drifts away from the goal | Claude cannot approve its own experiment design. You approve each one (`nb freeze`), and `nb` refuses a design that does not trace back to an active goal. |
| Findings get lost in chat history | `nb` stores each result with the commit, run directory and artifacts it came from, and lists it as unreviewed until you have reviewed it. |
| "We know X" with no record of why | `nb` refuses a conclusion that cites no experiment result. Each hypothesis is judged against a rule you approved before the run. |
| Someone adjusts the rule after seeing the result | `nb` freezes the design and its decision rules, and records a checksum of them, before it accepts a result. |
| Claude's interpretation becomes project fact | Goals, conclusions, leads and decisions that Claude adds stay `pending` until you confirm them. `nb` records whether a conclusion came from your read or Claude's. |
| A result turns out to be wrong | When you invalidate it, `nb` withdraws the verdicts judged on it, and `nb lint` reports the conclusions that cite it. |

The notebook does not hold metrics or configs (those stay in W&B, MLflow or
run directories, and the notebook stores references to them) or task lists.

## How it works

The notebook is a graph of typed entries. Each has a short id such as
`exp-7k2d`, and any unique prefix of an id works in a command.

| Entry | What it is |
|---|---|
| goal | What the project is for. |
| question | Something to find out, under a goal or another question. |
| hypothesis | A claim that could be true or false, with what should be observed if it holds. |
| experiment | A test of one or more hypotheses, each with a prediction, a metric and a decision rule. |
| exploration | Looking at data without a hypothesis. It can suggest leads but cannot back a conclusion on its own. |
| result | What a run produced: facts only, with the commit, run directory and artifacts. |
| conclusion | An interpretation of results. One claim each, with its scope and the alternatives considered. |
| lead | Something worth following up, suggested by a result. |
| decision | A choice the project made, with what it was based on and what was rejected. |
| audit | An independent check of a conclusion or lead against its evidence: a verdict, plus findings marked as errors or notes. |

The notebook keeps two kinds of knowledge apart.

A verdict applies a rule you approved in advance. You freeze an experiment's
decision rule before the run. Whoever records the result applies that rule
and gives each tested hypothesis a verdict (`supported`, `refuted` or
`inconclusive`) along with the measured value and the bound it was compared
to. The rule is free text, so `nb` does not compute the verdict; the auditor
checks that the value appears in the result.

A conclusion is an interpretation: what results add up to, across runs or
beyond one rule. It needs your confirmation, and by default a conclusion that
Claude drafted needs an audit first.

`nb` derives a hypothesis's status from all the current verdicts on it, in no
order:

| Current verdicts | Status |
|---|---|
| none, or only inconclusive | `open` |
| at least one supported, none refuted | `supported` |
| at least one refuted, none supported | `refuted` |
| both | `contested` |

A contested hypothesis stays contested until you invalidate a flawed result
or replace the hypothesis with a narrower one. `nb` never picks a side.

## Install

```
/plugin marketplace add <path-or-url-to-research-tools>
/plugin install lab-notebook@research-tools
```

It needs Python 3 and git, and nothing else. While the plugin is enabled its
`bin/` directory is on the Bash tool's PATH, so `nb` works as a bare command
inside Claude Code. To use `nb` in your own terminal, add
`plugins/lab-notebook/bin` to your PATH.

## First run

In the project's git repository:

```
nb init
```

This creates the notebook on the git ref `refs/notebook/data`. Nothing is
checked out, so the notebook is the same on every branch and worktree, and a
result recorded on a branch you later delete is not lost.

## Example

```
$ nb add goal "Condition BioEmu on endpoints and committor to sample the TSE"
goal-ae90
$ nb add question "Does a committor-conditioned fine-tune sample the TSE at the requested q?" --link refines:goal-ae90
q-qrt0
$ nb add hypothesis "The ControlNet places samples at the requested committor" \
    --prediction "realized q tracks requested q on the held-out protein" --link addresses:q-qrt0
hyp-e5f7
$ nb add experiment "ControlNet run 1 on villin holdout" --spec "..." --exec command --fresh
exp-czx5
$ nb predict exp-czx5 hyp-e5f7 --prediction "rho(q_req, q_real) > 0.5" \
    --metric "Spearman rho over 512 samples per q_req" --rule "supported if rho > 0.5"
$ nb freeze exp-czx5          # your approval: the design can no longer change
exp-czx5
$ nb result exp-czx5 "rho = -0.02; 7.8x enrichment in the transition region" \
    --verdict hyp-e5f7 refuted "rho -0.02 <= 0.5" --run-dir runs/tse/villin_holdout --ext-id 4tydmwr6
res-9kdx
$ nb brief res-9kdx            # the result and everything linked to it, for your read
$ nb nothing-yet res-9kdx      # or a conclusion drafted from your read
$ nb path exp-czx5
exp-czx5 -> hyp-e5f7 -> q-qrt0 -> goal-ae90  (active)
```

Before a design can be frozen it must say what it builds on:

- `--link variant-of:<exp>` when it changes an earlier design;
- `--link uses:<exp, xpl or res>` when it uses another's outputs (a
  checkpoint, a dataset) or analyses an existing result;
- `--fresh` when it builds on nothing in the notebook.

## From result to conclusion

Each result goes through three steps.

1. Record the verdicts. `nb result <exp> ... --verdict <hyp>
   <supported|refuted|inconclusive> "<value vs bound>"` takes one verdict per
   tested hypothesis. `nb` updates the hypothesis's status at once and marks
   the experiment `done` when every tested hypothesis has a verdict.
2. Review the result. Claude shows you `nb brief <res>`: the result plus the
   results linked to it (same chain of variants, same hypotheses, same
   question). `nb` builds the brief by fixed rules from links only, so Claude
   does not choose what goes in it. Claude asks for your read and holds its
   own until you have given yours or asked for it. When Claude drafts a
   conclusion from your words, `nb` stores them verbatim. If there is nothing
   to conclude yet, you approve `nb nothing-yet <res>`.
3. Audit and confirm. Before you confirm a conclusion or lead that Claude
   drafted, the `nb-auditor` subagent checks it against the evidence that
   `nb audit <id>` prints. The auditor sees that output and not the
   conversation. By default `nb confirm` refuses a draft that has no audit or
   that changed since its audit. `/nb-audit` runs the same check over every
   supported conclusion.

   The auditor marks each finding as an error or a note. An error is
   something wrong that it can point to: a number that no cited result
   holds, a statement that disagrees with a verdict or with an uncited
   result, a scope wider than the data. A note is anything else worth
   knowing, such as an alternative explanation the draft leaves out. The
   verdict is `sound` when there are no errors, so `nb lint` warns only about
   claims with an error. `nb audit` itself lists the numbers in a draft that
   no cited result holds. When a draft changes after an audit, the next audit
   checks only whether the errors were fixed and whether the change added new
   ones.

The freeze gate is optional (`nb config set freeze_gate true`, off by
default). While it is on, `nb` refuses a freeze if any result is unreviewed
or a run with a result is missing a verdict, including when you run `nb
freeze` yourself. `nb gate` shows what is blocking. Runs with no result yet
and `--interim` results do not block.

## What Claude can and cannot do

`nb` records who ran each command: `claude` inside Claude Code's Bash tool,
`user` anywhere else. There is no flag to override it. Goals, conclusions,
leads and decisions that Claude adds start `pending`.

Seven commands need your approval when Claude runs them. A hook makes Claude
Code ask you first and shows what you would be approving.

| Command | What you are approving |
|---|---|
| `nb freeze` | An experiment design: its predictions, decision rules and what it builds on. |
| `nb confirm` | A pending goal, conclusion, lead or decision becoming established. With `--also`, the questions it answers are marked answered. |
| `nb invalidate` | Withdrawing a result. |
| `nb retract` | Removing a mistaken supports or contradicts link. |
| `nb verdict --replace` | Overriding how a frozen rule was applied. |
| `nb nothing-yet` | Closing a review with no conclusion. |
| `nb config set` | Changing thresholds and gates. |

According to the Claude Code docs, a hook's "ask" still prompts in auto mode.
In bypass mode (`--dangerously-skip-permissions`) it probably does not; that
is untested.

`nb` tells Claude from you by an environment variable that Claude Code sets.
That stops an assistant that follows the rules. It would not stop a
deliberate attempt to get around it.

## What Claude sees

At session start a hook runs `nb prime`, a briefing capped at 4,000
characters: active goals, items awaiting you, results that need closing, runs
in flight, open questions, recent conclusions, active leads and lint counts.
It prints nothing in a repository without a notebook.

The `lab-notebook` skill tells Claude when and how to record, and pre-approves
the read-only commands while it is active. To allow them everywhere, add
e.g. `Bash(nb show *)` to `permissions.allow` in your settings.

## Working across machines

If the repository has an `origin` remote, `nb init` adds a fetch refspec and a
pre-push hook, so the notebook syncs whenever you push code. `nb sync` does
it by hand. In a fresh clone, run `nb init` once to fetch the notebook.

Two machines can write to the notebook between syncs. `nb sync` merges entry
by entry and field by field. If both sides changed the same field
differently, it writes nothing and lists the conflicts for you to resolve on
one side.

The notebook format has a schema number, currently 2. A newer `nb` upgrades an
older notebook on its next write; an older `nb` refuses a newer notebook.
After an upgrade, update the plugin on every machine before you sync. From
schema 2, `nb` derives hypothesis status by the table above, which can move
some hypotheses to `contested`; `nb lint` lists them.

## Commands

Every read command takes `--json`. Commands that create an entry print its id
on stdout and its title on stderr, so `$(nb add ...)` captures just the id.

| To do this | Use |
|---|---|
| Add an entry | `nb add <type> "<title>" [--link REL:ID] ...` |
| Add a prediction to a draft experiment | `nb predict <exp> <hyp> --prediction P --metric M --rule R` |
| Approve a design | `nb freeze <id>` |
| Note a change from the frozen procedure | `nb deviate <id> "<text>"` |
| Record a result and its verdicts | `nb result <exp> "<facts>" --verdict <hyp> <verdict> "<basis>"` |
| Add a verdict to an existing result | `nb verdict <res> <hyp> <verdict> --basis "<basis>"` |
| Establish or reject something pending | `nb confirm <id>`, `nb reject <id> --reason R` |
| Withdraw a result | `nb invalidate <res> --reason R` |
| See one entry and its links | `nb show <id>` |
| See an entry's neighbourhood | `nb context <id>` |
| See why an entry exists | `nb path <id>` (its route to a goal) |
| Review a result | `nb brief <res>` |
| See what is waiting on you | `nb pending` |
| Search | `nb query [--type T] [--status S] [--tag T] [--text S]` |
| Check the whole notebook | `nb lint` |
| Sync with `origin` | `nb sync` |

The full list is in [SPEC.md](SPEC.md#cli).

## What is in the plugin

| Path | What it is |
|---|---|
| `bin/nb` | The CLI, and the only thing that writes the notebook. |
| `hooks/` | The session-start briefing and the approval hook for gated commands. |
| `skills/lab-notebook/` | Instructions that tell Claude when and how to use `nb`. |
| `agents/nb-auditor.md` | The auditor subagent. |
| `commands/nb-audit.md` | The `/nb-audit` sweep. |
| `SPEC.md` | The data model, storage format and every rule. |
| `tests/` | The test suite. |

## Not built yet

- Run gating. Claude can still launch a training run without going through
  `nb`; the skill tells it not to, and nothing enforces that. SPEC.md lists a
  hook that blocks run commands not tied to a frozen experiment as a later
  phase.
- Computed verdicts. `nb` does not compute a verdict from a metrics file.
  Whoever records the result types the verdict and the measured value.
- A design skill with structural checks on a draft experiment, also listed in
  SPEC.md as a later phase.

## Tests

```
python3 plugins/lab-notebook/tests/test_nb.py
```

The full run takes a few minutes (about three and a half on the machine it
was last run on). To run one class or test,
pass it as an argument: `python3 plugins/lab-notebook/tests/test_nb.py
TestVerdicts`.

`tests/fixtures/bioemu.py` models a real project (bioemu-kinetics) as a
sequence of `nb` calls and is replayed by the tests.
