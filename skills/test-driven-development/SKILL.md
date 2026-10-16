---
name: test-driven-development
description: Use when adding a feature or fixing a bug. Failing test first, then the code that passes it.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Test-Driven Development

RED – GREEN – REFACTOR. The order is the method; no shortcuts.

## RED: the failing test

Write the test before the code and run it with `run_shell`
(`pytest` or `python tests/...`). It must fail, and for the
right reason: a test failing on a broken import proves nothing.
Read the error and ask "is this the behavior I want to change?"
— if yes, the test is good.

## GREEN: the minimum that passes

Write the smallest code that passes. No generalizations, no
"while I'm at it". If passing requires gutting half the
project, the test is saying the design is wrong: listen before
forcing it.

## REFACTOR: clean up on green

Only now: better names, no duplication, short functions.
Re-run the tests after every touch. A refactor that breaks a
test is not a refactor, it is a second task in disguise.

## Where and how here

Tests live in `tests/test_*.py` and run with `run_shell`.
Before closing, the full suite (`python tests/run_all.py`)
must stay green: a new test never justifies an old broken one.
