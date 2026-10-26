---
id: rust-ownership
title: Rust ownership
kind: concept
level: 3
last_evidenced: 2026-09-01
aliases: [borrow checker]
tags: [rust, programming]
evidence:
  - "2026-09-01 observed: refactored a parser to borrow slices instead of cloning"
created: 2026-08-15
updated: 2026-09-01
---
Every value has one owner; borrows are checked at compile time. Deliberate orphan (lint warning).
