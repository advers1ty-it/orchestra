---
name: github
description: Use when working with GitHub repositories. Branches, issues, pull requests, reviews, merges via the gh CLI.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# GitHub via gh

Everything goes through the `gh` CLI, run with `run_shell`.
Never narrate clicks from memory: read every state from commands.

## Authentication

`gh auth login` once. Run `gh auth status` before a work
session: an expired token is found at the start, not at push
time.

## Issue → PR → merge cycle

1. `gh issue list` / `gh issue view <n>` for the real context.
2. Branch named after what it does, never work on main directly.
3. Small commits with messages saying why, then push.
4. `gh pr create`: title summarizes, body says what changed
   and how it was verified.
5. `gh pr checks`: merge only on green CI. A red CI ignored
   is a bug sent by mail.
6. `gh pr merge`, then delete the branch.

## Review

`gh pr diff <n>` before any opinion. Inline comments cite
exact lines, not impressions. Approving without reading the
diff is not a review.

## Honest state

On failure, report the exact error and stop: never "it should
have worked" without the output proving it.
