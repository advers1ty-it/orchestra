---
name: cron
description: "Scheduled jobs: create, edit and delete cron jobs that run objectives or shell commands on a schedule. Uses the `cron` tool."
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# cron

Use the `cron` tool to schedule recurring or one-shot runs.

## When to use it
- The user asks for a recurring activity (for example "every day at 9", "Monday morning", "every hour").
- For a one-off activity, do not create a cron rule that could repeat: use a goal with `--not-before <epoch>`, or ask when to run it if the time is unclear.
- Automating reports, backups, periodic checks.

## Actions
- `lista`: lists the jobs.
- `crea`: creates a job. Parameters: name, schedule, action_type (goal/shell), objective or command, profile, enabled.
- `modifica`: changes fields of a job (id required).
- `elimina`: removes a job.
- `abilita`/`disabilita`: toggle.
- `esegui`: runs a job now.
- `dettagli`: details of one job.
- `stato`: state of the cron scheduler.
- `avvia_scheduler`/`ferma_scheduler`: starts/stops the daemon.

## Schedule
5-field cron expression: `minute hour day month weekday`.
Shortcuts: `@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly`, `@reboot` (once, at startup).

Examples:
- every day at 9: `0 9 * * *`
- every Monday at 8: `0 8 * * 1`
- every 15 minutes: `*/15 * * * *`
- every hour: `@hourly`

## Notes
- Jobs of type goal start an objective (they cost tokens). Shell jobs run a command.
- The cron scheduler starts by itself when the server starts (30s interval). It can be stopped from the Cron panel or through the tool.
- To edit or delete, use the id returned by `lista`/`crea`.
