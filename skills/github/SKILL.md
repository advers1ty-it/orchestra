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
3. Prepare small commits with messages saying why. Never commit unless the user asks.
4. Push or create a PR only when the user explicitly asks for that external side effect.
5. `gh pr create`: title summarizes, body says what changed
   and how it was verified.
6. `gh pr checks`: merge only on green CI. Merge only when the user explicitly asks.
7. Delete a branch only with explicit user authorization; it is destructive.

## Review

`gh pr diff <n>` before any opinion. Inline comments cite
exact lines, not impressions. Approving without reading the
diff is not a review.

## Honest state

On failure, report the exact error and stop: never "it should
have worked" without the output proving it.
