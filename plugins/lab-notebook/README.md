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
$ nb result exp-czx5 "rho = -0.02; 7.8x enrichment in the transition region" \
    --run-dir runs/tse/villin_holdout --ext-id 4tydmwr6
res-9kdx
$ nb path exp-czx5
exp-czx5 -> hyp-e5f7 -> q-qrt0 -> goal-ae90  (active)
```

`nb prime` is the briefing Claude sees at session start; `nb context <id>`,
`nb path <id>`, `nb query` and `nb show <id>` pull more on demand. `nb lint`
checks the whole graph. Every read command takes `--json`.

## Who can do what

`author` is recorded from the environment: commands run by Claude (inside
Claude Code's Bash tool) are `claude`, everything else is `user`. Goals,
conclusions, leads and decisions that Claude adds start `pending`. Five
commands are yours to approve: `nb freeze` (approve an experiment design),
`nb confirm` (establish a pending node), `nb invalidate` (withdraw a result),
`nb retract` (remove a mistaken supports/contradicts link) and
`nb config set`. A PreToolUse hook makes Claude Code ask you before
Claude runs any of them, showing what you would be approving (for a freeze:
the predictions and decision rules). Per the Claude Code docs a hook's "ask"
still prompts in auto mode; in bypass mode (`--dangerously-skip-permissions`)
it probably does not.

At session start a hook runs `nb prime`, a briefing capped at 4,000
characters: active goals, pending items, experiments in flight, open
questions, recent conclusions and active leads. It prints nothing in a repo
without a notebook. The `lab-notebook` skill tells Claude when and how to
record, and pre-approves read-only commands (`nb show`, `context`, `path`,
`query`, `pending`, `prime`, `lint`, `log`) while it is active; to allow them
everywhere, add e.g. `Bash(nb show *)` to `permissions.allow` in your
settings.

## Tests

```
python3 plugins/lab-notebook/tests/test_nb.py
```

`tests/fixtures/bioemu.py` models a real project (bioemu-kinetics) as a
sequence of `nb` calls and is replayed by the tests.
