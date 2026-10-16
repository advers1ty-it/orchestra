---
name: plan
description: Use when a job is too big to do freehand. Write the plan to .orchestra/plans/ first, execute nothing.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Plan

A plan is a markdown file, not a promise. Write it first,
execute later. Never both at once.

## How to write it

1. Read the relevant files with `read_file` before proposing
   steps: a plan written without looking at the code is a wish.
2. Create `.orchestra/plans/<slug>.md` with `write_file`:
   - **Goal**: one sentence, measurable.
   - **Context**: what you already know (files, constraints,
     past decisions).
   - **Steps**: numbered, each small enough to verify alone,
     with the command or file that closes it.
   - **Risks**: what can go wrong and how you would notice.
   - **Final check**: how done is demonstrated (test,
     command, expected output).
3. Stop there. Execute nothing: execution is a separate job
   with its own verification round.

## Rules

- One step = one check. A step without a check is two steps
  with one hidden: split it.
- If writing reveals missing information, put it under risks
  instead of inventing it.
- The plan lives in the repo (`.orchestra/plans/`): the next
  session finds it instead of starting over.
