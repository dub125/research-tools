---
description: Audit sweep for the lab notebook - run the nb-auditor on every supported conclusion (or on the ids given) and record each audit
argument-hint: "[con-or-lead-id ...]"
allowed-tools: Bash(nb query *), Bash(nb audit *), Bash(nb show *), Bash(nb config get *)
---

Run an audit sweep over this repository's lab notebook (`nb`).

Targets: $ARGUMENTS

1. If targets are given above, audit those conclusions or leads. Otherwise
   audit every supported conclusion:
   `nb query --type conclusion --status supported --all --json`.
2. Read the auditor model with `nb config get auditor_model`.
3. For each target, run `nb audit <id>` and launch the `lab-notebook:nb-auditor`
   agent with that model. Give it only the bundle text and the instruction to
   audit `<id>`. Do not pass it this conversation or your own opinion of the
   claim. Independent targets can run in parallel.
4. Record each answer as it comes back:
   `nb add audit "Audit of <id>" --of <id> --verdict <verdict> --findings "<findings, one per line>" --auditor nb-auditor/<model>`.
   An audit only adds a warning; it never changes the audited node.
5. Cross-conclusion problems: if the auditor reports that two conclusions
   contradict each other, record it as an audit of the more recently
   confirmed one, citing the other's id in the findings.
6. Report to the user in words, not bare ids: how many claims were audited,
   then every `concerns` or `unsound` verdict with the claim's title, its id
   after the title, and the findings. Say what the user could do about each
   (narrow the claim, supersede it, mark it refuted), and do nothing about it
   yourself.
