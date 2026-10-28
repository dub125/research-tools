---
name: lab-notebook
description: Use when research work in a repo with a lab notebook (nb) touches goals, questions, hypotheses, experiment designs, results or conclusions - proposing or designing an experiment, recording a run's result, interpreting results when asked, recording a decision, or checking what the project already knows before starting something.
allowed-tools: Bash(nb show *), Bash(nb context *), Bash(nb path *), Bash(nb query *), Bash(nb pending *), Bash(nb prime *), Bash(nb lint *), Bash(nb log *)
---

# lab-notebook

The project's research record: what it is trying to find out, what it did,
what it found and what it concluded, as a typed graph on the git ref
`refs/notebook/data`. Write only through `nb`; it validates every write and
records you as the author. Full rules: `SPEC.md` in the plugin directory.

The notebook holds epistemic state only. Work items and how-to facts ("bf16
NaNs in the score head") go to foam; metrics and configs stay in W&B, MLflow
or the run directory, and the notebook stores references to them.

## Rules

- **The user approves, you propose.** `nb freeze` (approving a design),
  `nb confirm` (establishing a pending claim), `nb invalidate` and
  `nb config set` are the user's decisions. Run them only when the user asks
  you to; Claude Code will ask them to approve. Never freeze an experiment you
  designed in the same breath as proposing it.
- **One experiment at a time.** After a run, report and stop. Do not design,
  freeze or launch a follow-up on your own; suggest it.
- **Facts before readings.** A result's summary holds only what was measured.
  Interpretation goes into conclusions or leads, which you add as pending.
- **Check before you start.** Before proposing an experiment, look at what is
  known: `nb query --text <topic>`, `nb context <question>`, and `nb path` on
  the proposal once drafted. Say if it repeats a done experiment, contradicts
  a supported conclusion, or ignores an active lead.
- **Scope claims.** A conclusion says where it holds (`--scope`), what was
  ruled out (`--alternatives`), and how sure (`--confidence`). Prefer a lead
  over a conclusion when the evidence is thin or comes from an exploration.
- **Don't dump the graph.** `nb prime` already loaded at session start. Pull
  more with `context`, `path`, `query` and `show`, not by reading the ref.

## Workflows

**Proposing an experiment** (draft, then ask the user to freeze):

```
nb add question "..." --link refines:<goal or question>      # if no question fits
nb add hypothesis "<claim>" --prediction "<what should be seen>" --link addresses:<q>
nb add experiment "<title>" --spec "<what, on what data, which command>" --exec command|analysis|manual
nb predict <exp> <hyp> --prediction "..." --metric "..." --rule "supported if ..., refuted if ..."
nb path <exp>                                                   # must reach an active goal
```

Then show the user the design and the decision rule, and let them freeze it.
Data analysis without a hypothesis is an `exploration` (`--link
investigates:<q>`, no predictions); its results can only suggest leads.

**After a run** (the experiment must be frozen):

```
nb result <exp> "<facts only>" --run-dir <dir> --ext-id <wandb id> --artifact <path> [--metrics file.json]
```

Provenance (commit, dirty flag) is captured automatically. Report the facts
first; a brief read, clearly labeled as yours, is fine. Record no conclusions
or leads and launch nothing unless the user asks. A procedure change during
the run is `nb deviate <exp> "<what and why>"`. Analysis decided on after
freezing is a new exploration with `--link uses:<result>`, not a deviation.

**Interpreting** (only when asked): read `nb context <question> --depth 2`
first and account for every prior result that bears on it. Then:

```
nb add conclusion "<scoped claim>" --from <res> --rationale "..." --scope "..." \
    --alternatives "..." --confidence low|medium|high --link answers:<q> --link supports|contradicts:<hyp>
nb add lead "<what the results suggest>" --from <res> --rationale "..."
```

Both start pending; tell the user what you added so they can confirm or reject.

**Decisions** (a choice, not a finding): `nb add decision "<choice>"
--rationale "..." --reject "<alternative>" --revisit-if "..." --link
based-on:<res or con> --link affects:<question/experiment>`.

**Backfilling past work:** `nb add experiment ... --retro` when the spec and
predictions are written after the results existed.

## Cheat sheet

```
nb prime | nb pending | nb lint
nb show <id> | nb context <id> [--depth N] | nb path <id>
nb query [--type T] [--status S] [--tag T] [--text S] [--since DATE]
nb status <id> <status> [--reason R]      # answered/settled/parked, done, followed, ...
nb link <from> <rel> <to>                 # e.g. lead spawns hyp, decision affects exp
nb set <id> tags <t> --append             # tags, body, refs; other fields only while draft/open/pending
```

Ids accept any unique prefix (`exp-7k`). Every read command takes `--json`.
