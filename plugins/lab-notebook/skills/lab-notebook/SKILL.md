---
name: lab-notebook
description: Use when research work in a repo with a lab notebook (nb) touches goals, questions, hypotheses, experiment designs, results or conclusions - proposing or designing an experiment, recording a run's result and its verdicts, reviewing a result with the user, recording a decision, or checking what the project already knows before starting something.
allowed-tools: Bash(nb show *), Bash(nb context *), Bash(nb path *), Bash(nb query *), Bash(nb pending *), Bash(nb prime *), Bash(nb lint *), Bash(nb log *), Bash(nb brief *), Bash(nb audit *), Bash(nb gate *)
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

- **The user approves, you propose.** `nb freeze`, `nb confirm`,
  `nb nothing-yet`, `nb invalidate`, `nb retract`, `nb verdict --replace` and
  `nb config set` are the user's decisions. Run them only when the user asks;
  Claude Code will ask them to approve. Never freeze an experiment you
  designed in the same breath as proposing it.
- **Name things, then give the id.** The user does not know what `exp-pb59`
  is. Say "run 17, the 10k-step version of run 16 (exp-pb59)". Never ask the
  user to decide anything about a bare id: restate what is being decided and
  the options in words.
- **One experiment at a time.** After a run, record, review and stop. Do not
  design, freeze or launch a follow-up on your own; suggest it.
- **Facts before readings, and the user's reading first.** A result's summary
  holds only what was measured. When reviewing a result, hold your own read
  until the user has given theirs or asked for yours.
- **Check before you start.** Before proposing an experiment, look at what is
  known: `nb query --text <topic>`, `nb context <question>`, and `nb path` on
  the proposal once drafted. Say if it repeats a done experiment, contradicts
  a supported conclusion, or ignores an active lead.
- **State what a design builds on.** When drafting an experiment or
  exploration, say what it builds on: `--link variant-of:<exp>` when it
  changes an earlier design ("run 18 = run 13 at 30k steps"), `--link
  uses:<exp, xpl or res>` when it uses another's outputs or analyses a result,
  or `--fresh` when it builds on nothing in the notebook. A two-state-style
  check of a run's trained model `uses` that run's experiment (its checkpoint),
  even before the run has results. `nb freeze` refuses a design with none of
  these. The brief follows links only, so it can only show what is linked.
- **Don't dump the graph.** `nb prime` already loaded at session start. Pull
  more with `context`, `path`, `query`, `brief` and `show`.

## Workflows

**Proposing an experiment** (draft, then ask the user to freeze):

```
nb gate                                                         # anything left to close first?
nb add question "..." --link refines:<goal or question>         # if no question fits
nb add hypothesis "<claim>" --prediction "<what should be seen>" --link addresses:<q>
nb add experiment "<title>" --spec "..." --exec command|analysis|manual \
    --link variant-of:<exp> | --link uses:<exp, xpl or res> | --fresh   # what it builds on
nb predict <exp> <hyp> --prediction "..." --metric "..." --rule "supported if ..., refuted if ..., otherwise inconclusive"
nb path <exp>                                                   # must reach an active goal
```

If `nb gate` lists unreviewed results or missing verdicts, tell the user and
close those first; `nb freeze` will be refused until then. Then show the user
the design and the decision rule, and let them freeze it. Data analysis
without a hypothesis is an `exploration` (`--link investigates:<q>`, no
predictions, and the same builds-on links or `--fresh`).

**After a run** (the experiment must be frozen):

1. Record the result and apply the frozen rule to each predicted hypothesis:

   ```
   nb result <exp> "<facts only>" --verdict <hyp> supported|refuted|inconclusive "<value vs bound>" \
       --run-dir <dir> --ext-id <id> --artifact <path> [--metrics file.json]
   ```

   Verdicts apply at once. A hypothesis's status comes from all current
   verdicts on it, in no order: if experiments disagree it is `contested`
   (`nb show <hyp>` lists each side). Tell the user and let them resolve it
   (invalidate a flawed result, or supersede the hypothesis with a narrower
   one); never pick a side yourself. A partial result is `--interim` and gets no
   verdicts. A procedure change during the run is `nb deviate`; analysis
   decided on after freezing is a new exploration that `uses` the result.

2. Report the facts and the verdicts, each with its basis.

3. Review: run `nb brief <res>` and show it as printed. Do not drop lines or
   add commentary. Ask what the user takes from it. Then:
   - **They give a read:** draft conclusions from their words, one claim
     each, with `--origin user --user-words "<their words, verbatim>"`.
     Anything you add beyond their words (scope, alternatives) must be
     visibly yours in the rationale. Then audit (below).
   - **They ask for your read:** give it, labelled as yours. If they want it
     recorded, `--origin claude`. Never use `--origin claude` for a read the
     user did not ask for.
   - **Nothing yet:** `nb nothing-yet <res> --note "<their reason, if any>"`.
   - A read from exploration results alone is a lead, not a conclusion.

4. For an exploration, ask whether more results are expected; if not,
   `nb status <xpl> done`. An experiment closes itself once every hypothesis
   has a verdict. A rerun of a done experiment is a new experiment with
   `--link variant-of:<old>`.

5. Stop. Suggest a next step if there is one; launch nothing.

```
nb add conclusion "<one claim>" --from <res>... --rationale "..." --scope "..." \
    --alternatives "..." --confidence low|medium|high --origin user --user-words "..." \
    [--link answers:<q>] [--link supports|contradicts:<hyp or con>]
nb add lead "<what the results suggest>" --from <res>... --rationale "..." --origin user --user-words "..."
```

`answers` is optional: a finding that turned up along the way needs no
question.

**Audit before confirm.** For each pending conclusion or lead you drafted,
run the `nb-auditor` agent (`lab-notebook:nb-auditor`; pass the model from
`nb config get auditor_model`) with only the output of `nb audit <id>`; do
not pass it the conversation. Record
what it returns with `nb add audit --of <id> --verdict ... --findings ...
--auditor nb-auditor/<model>`, then tell the user the verdict and findings in
words.

Findings are errors or notes. `sound` means no errors.

- **Errors** (a number no cited result holds, a statement that disagrees
  with a verdict or with an uncited result, a scope wider than the data,
  changed user words): fix the draft with the user, or let them reject it.
  Change only what the error names. A changed draft needs a re-audit: run
  `nb audit <id>` again and pass the new bundle, which now holds the previous
  findings and what changed, so the auditor checks only those.
- **Notes** (a missing alternative, a two-claim title, an unlinked result):
  report them to the user and leave the draft alone unless they ask for a
  change. Each edit costs a re-audit.

Stop after one re-audit. If errors remain, show them to the user and let
them decide: fix again, confirm with the audit on record, or reject.

Keep a draft short so the audit has less to question. The title is the one
claim. The rationale gives the evidence (the numbers, each from a cited
result) and how the verdicts came out, in a few sentences. Limits go in
`--scope` and other explanations in `--alternatives`, not in the rationale.
`nb audit <id>` lists, under "Computed by nb", every decimal and percentage
in your draft that no cited result holds; look at it before you run the
auditor and cite the missing result or drop the number.

**Confirming.** `nb show <id>` lists the open questions a conclusion
answers. Ask the user which to mark answered, then run `nb confirm <id>
--also <q>...`. A conclusion never changes a hypothesis: hypotheses follow
their verdicts only.

**Decisions** (a choice, not a finding): `nb add decision "<choice>"
--rationale "..." --reject "<alternative>" --revisit-if "..." --link
based-on:<res or con> --link affects:<question/experiment>`.

**Backfilling past work:** `nb add experiment ... --retro` when the spec and
predictions are written after the results existed; `nb verdict <res> <hyp>
<verdict> --basis "..."` adds a verdict to an existing result.

## Cheat sheet

```
nb prime | nb pending | nb gate | nb lint
nb show <id> | nb context <id> [--depth N] | nb path <id> | nb brief <res> [--all] | nb audit <id>
nb query [--type T] [--status S] [--tag T] [--text S] [--since DATE]
nb status <id> <status> [--reason R]      # parked, abandoned, followed (an active lead), exploration done;
                                          # never for pending nodes or hypotheses
nb link <from> <rel> <to>                 # e.g. variant-of, uses, lead spawns hyp
nb set <id> tags <t> --append             # tags, body, refs; other fields only while draft/open/pending
```

Ids accept any unique prefix (`exp-7k`). Every read command takes `--json`.
