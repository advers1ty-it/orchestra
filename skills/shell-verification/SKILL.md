---
name: shell-verification
description: Use when work must be checked by running it: tests, builds, scripts, commands. Verify, do not guess.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Shell and Verification

Code that is not run has not worked. `run_shell` is how you
know.

## How

1. Run the smallest command that exercises the change: a single
   test file, a single build target, a single script invocation.
2. Read stdout and stderr fully. Exit code 0 is not enough: a
   test that prints "0 passed" still exited 0.
3. On failure, read the error, fix one thing, re-run the same
   command. Do not change the command to make it pass.
4. Before closing, run the full suite when it exists
   (`python tests/run_all.py` here) to catch collateral damage.

## Platform

- Windows: the separator is ` && `, not `;`. With cmd.exe, `;`
  runs only the first command and reports success — the second
  vanishes silently.
- Prefer relative paths inside the project; they do not trigger
  the permission prompt.
- A command that touches a path outside the working folder asks
  the user (four choices); sensitive paths are denied without
  asking.

## Rules

- Never report "it works" without having run it after the last
  edit. The last edit is always the one that breaks it.
- Do not invent commands or flags. If unsure, check `--help`
  or the docs first.
- Long-running or destructive commands (installs, deletes,
  migrations) need explicit user confirmation before running.
- If a tool is missing, install it with `run_shell` and verify
  the import; if there is no network, say so and work local-only.