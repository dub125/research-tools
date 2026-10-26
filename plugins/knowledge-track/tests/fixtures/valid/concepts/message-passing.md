---
id: message-passing
title: Message passing (GNN layer update)
kind: concept
level: 3
last_evidenced: 2026-09-14
aliases: [neighbourhood aggregation, MPNN]
tags: [ml, gnn]
requires: [graph-basics]
part-of: [graph-neural-networks]
related: [attention-mechanism]
contrasts-with: [label-propagation]
evidence:
  - "2026-09-14 observed: implemented GCN layer in gnn/main.py"
  - "2026-06-02 explained-back: described the update rule in own words during review"
  - "2026-05-20 exposed: Claude walked through the Gilmer et al. message passing framework"
created: 2026-06-02
updated: 2026-09-14
---
Each node updates its state from an aggregate of messages from its neighbours.
