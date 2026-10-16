---
name: systematic-debugging
description: Use when a bug survives the first fix or its origin is unclear. Find the root cause before touching code.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Systematic Debugging

Fixing symptoms moves the bug. Work in four phases, one hypothesis
at a time.

## 1. Reproduce

Find the smallest command that shows the bug and run it with
`run_shell`. If it does not reproduce on command, you have an
impression, not a bug. Record the exact output, never a summary
from memory.

## 2. Narrow down

Bisect: split what works from what breaks, then halve again.
Read the code with `read_file` before changing it — never edit
a file you have not read. For regressions, `git log` and
`git blame` show what changed last: regressions almost always
live there.

## 3. Root cause

State it in one sentence: "X happens because Y". If the sentence
contains "and also", it is not the root: go one level deeper.
If two fixes in two places seem necessary, the real cause is
still missing.

## 4. Fix and verify

One fix, then re-run the phase-1 command: it must pass. Then
check for collateral damage — same bug, same family, in the
file and its siblings. Done means the reproduction passes and
nothing else broke.
