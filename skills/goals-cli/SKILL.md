---
name: goals-cli
description: Use when work is too big for one turn or must survive a restart: create autonomous goals, plans, dependencies, and run the scheduler via the CLI.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Autonomous Goals and Scheduler

Long work lives in goals, not in chat. Goals are persistent on
disk and survive restarts; the scheduler runs them one at a time.

## Commands (via `run_shell`)

- `python -m orchestra.cli goal "objective"` — create and run a
  goal synchronously, prints the id.
- `python -m orchestra.cli goal "objective" --kind piano` — create
  a container plan; closes when its children finish.
- `python -m orchestra.cli goals` — list goals and plans with state.
- `python -m orchestra.cli goals --pronti` — only those ready to run.
- `python -m orchestra.cli goal-next` — run the next ready goal.
- `python -m orchestra.cli scheduler --una-volta` — drain the queue
  and exit (scheduler is off by default to save tokens).

## Dependencies and acceptance

- `--depends-on <id>` — a goal starts only when its dependency
  is `done`; cycles are rejected.
- `--criteri '{"file":"report.md","contiene":"X"}'` — declarative
  acceptance: the goal is not archived as done unless the file
  exists and contains X.
- `--max-attempts N` — retry a failed goal up to N times.
- An interrupted goal (max iterations, errors, budget) becomes
  `failed` with the reason; it is never archived as completed.

## How

1. Break the work into small, independently verifiable goals.
2. Write a plan first (`plan` skill) when the shape is unclear.
3. Create goals with `--depends-on` for ordering; use `--kind piano`
   to group.
4. Run `scheduler --una-volta` (or `goal-next` one at a time) and
   read the printed state.
5. On `failed`, read the reason before retrying; do not just
   re-run.

## Rules

- The scheduler consumes real tokens: it is off by default. Turn it
  on only when the user asks for autonomous work.
- A goal that claims completion without evidence gets re-checked.
- Durable work belongs in goals, not in this chat: the chat dies
  with the session, goals do not.