# lab-notebook

A per-project record of what the project is trying to find out, what it did,
what it found and what it concluded: goals, questions, hypotheses,
experiments, explorations, results, conclusions, leads, decisions and audits,
as a typed graph. It exists to keep AI-assisted research honest: experiments
must trace back to an active goal, results are facts with provenance,
conclusions must rest on experiment results, and anything Claude proposes
stays pending until you confirm it.

The format and rules are defined in [SPEC.md](SPEC.md). The `nb` CLI is the
only writer.

## Install

```
/plugin marketplace add <path-or-url-to-research-tools>
/plugin install lab-notebook@research-tools
```

The plugin's `bin/` directory is put on the Bash tool's PATH while the plugin
is enabled, so `nb` works as a bare command. Claude Code only.

## First run

In the project's git repository:

```
nb init
```

This creates the ref `refs/notebook/data`. Nothing is checked out: the
notebook is the same on every branch and worktree. If the repo has an
`origin` remote, `nb init` also adds a fetch refspec and a pre-push hook so
the notebook syncs when you push code; `nb sync` does it by hand. In a fresh
clone, run `nb init` once to fetch the notebook.

## Example

```
$ nb add goal "Condition BioEmu on endpoints and committor to sample the TSE"
goal-ae90
$ nb add question "Does a committor-conditioned fine-tune sample the TSE at the requested q?" --link refines:goal-ae90
q-qrt0
$ nb add hypothesis "The ControlNet places samples at the requested committor" \
    --prediction "realized q tracks requested q on the held-out protein" --link addresses:q-qrt0
hyp-e5f7
$ nb add experiment "ControlNet run 1 on villin holdout" --spec "..." --exec command
exp-czx5
$ nb predict exp-czx5 hyp-e5f7 --prediction "rho(q_req, q_real) > 0.5" \
    --metric "Spearman rho over 512 samples per q_req" --rule "supported if rho > 0.5"
$ nb freeze exp-czx5          # your approval: the design is now immutable
exp-czx5
$ nb result exp-czx5 "rho = -0.02; 7.8x enrichment in the transition region" \
    --verdict hyp-e5f7 refuted "rho -0.02 <= 0.5" --run-dir runs/tse/villin_holdout --ext-id 4tydmwr6
res-9kdx
$ nb brief res-9kdx            # what you need to give your read of the result
$ nb nothing-yet res-9kdx      # or a conclusion drafted from your read
$ nb path exp-czx5
exp-czx5 -> hyp-e5f7 -> q-qrt0 -> goal-ae90  (active)
```

Commands that create a node (`nb add`, `nb result`, `nb freeze`) print the id
on stdout and the title on stderr, so `$(nb add ...)` captures just the id.

`nb prime` is the briefing Claude sees at session start; `nb context <id>`,
`nb path <id>`, `nb query`, `nb brief <res>` and `nb show <id>` pull more on
demand. `nb lint` checks the whole graph. Every read command takes `--json`.

## Closing the loop

A result goes through three steps before the project moves on (SPEC.md,
"Closing the loop"):

1. **Verdicts.** `nb result <exp> ... --verdict <hyp> <supported|refuted|inconclusive> "<value vs bound>"`
   applies the experiment's frozen decision rule, once per predicted
   hypothesis. The hypothesis's status follows at once, and the experiment
   becomes `done` when every predicted hypothesis has a verdict. You no
   longer set these with `nb status`. `nb verdict` adds a verdict later;
   replacing one (`--replace --reason`) is yours to approve. Invalidating a
   result withdraws its verdicts and recomputes both statuses.
2. **Review.** Every result is reviewed with you. Claude shows `nb brief <res>`,
   a fixed summary of the result and everything linked or possibly related to
   it, asks for your read and holds its own until you have given yours or
   asked for it. A conclusion or lead drafted from your words records them
   (`--origin user --user-words`). If there is nothing to conclude yet, you
   run or approve `nb nothing-yet <res>`.
3. **Audit and confirm.** Before you confirm a conclusion or lead Claude
   drafted, the `nb-auditor` subagent (sonnet by default, `auditor_model`)
   checks it against `nb audit <id>`, the evidence bundle and nothing else, and
   Claude records the result with `nb add audit`. `nb confirm` refuses a draft
   whose latest audit is missing or older than its last change. `/nb-audit`
   runs the same check over every supported conclusion.

The **freeze gate** (`nb config set freeze_gate true`, off by default) makes
`nb freeze` refuse while any result is unreviewed or a frozen experiment with
a result is missing a verdict. It applies to your own `nb freeze` too.
`nb gate` shows what blocks it. Experiments still running (no results yet)
and `--interim` results do not block. A notebook from before verdicts starts
with every result unreviewed, so turn the gate on once that backlog is
reviewed.

## Who can do what

`author` is recorded from the environment: commands run by Claude (inside
Claude Code's Bash tool) are `claude`, everything else is `user`. Goals,
conclusions, leads and decisions that Claude adds start `pending`. Seven
commands are yours to approve: `nb freeze` (approve an experiment design),
`nb confirm` (establish a pending node, and with `--also` the hypothesis or
question changes it allows), `nb invalidate` (withdraw a result),
`nb retract` (remove a mistaken supports/contradicts link),
`nb verdict --replace` (override how a frozen rule was applied),
`nb nothing-yet` (close a review without a conclusion) and `nb config set`.
A PreToolUse hook makes Claude Code ask you before Claude runs any of them,
showing what you would be approving (for a freeze: the predictions and
decision rules; for a confirm: the claim, whether it came from your read or
Claude's, your words, the latest audit and each `--also` change). A freeze
that the freeze gate would refuse is denied outright, with what blocks it.
Per the Claude Code docs a hook's "ask"
still prompts in auto mode; in bypass mode (`--dangerously-skip-permissions`)
it probably does not.

At session start a hook runs `nb prime`, a briefing capped at 4,000
characters: active goals, pending items (with whose read they are and their
audit verdict), what needs closing (unreviewed results, missing verdicts),
experiments in flight, open questions, recent conclusions and active leads.
It prints nothing in a repo without a notebook. The `lab-notebook` skill
tells Claude when and how to record, and pre-approves read-only commands
(`nb show`, `context`, `path`, `query`, `pending`, `prime`, `lint`, `log`,
`brief`, `audit`, `gate`) while it is active; to allow them
everywhere, add e.g. `Bash(nb show *)` to `permissions.allow` in your
settings.

## Tests

```
python3 plugins/lab-notebook/tests/test_nb.py
```

`tests/fixtures/bioemu.py` models a real project (bioemu-kinetics) as a
sequence of `nb` calls and is replayed by the tests.
