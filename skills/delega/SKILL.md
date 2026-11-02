---
name: delega
description: Use when a job splits into independent parts. Hand each to a sub-agent with minimal context, one level only; delega_multi runs several at once.
version: 1.1.0
author: Orchestra
categoria: base
origine: base
---

# Delegation

Two tools, same kind of child: `delega` runs one and waits;
`delega_multi` takes a list of `obiettivi` and runs them together.
Children start with empty windows (`obiettivo` required, `contesto`
optional) and return only a final summary: what they send back is
what you get.

## When

- Independent workstreams: `delega_multi`, not a `delega` per part.
- One step whose result decides the next step: `delega`.
- Reasoning-heavy subtasks that would flood this context.
- Never for a single tool call, user interaction, or durable
  work: subagents cannot ask questions and die with the session.

## How

- One level only: children cannot delegate further. Pass
  everything the child needs in `contesto` — it knows nothing
  of this conversation, including output language and style.
- One task, one child: vague goals return vague summaries.
- `delega_multi` returns one block per child, in the same order as
  the list, and the results are **separate**: merging them is your
  decision, not the tool's. Default: 3 children at a time, the whole
  group capped at 240s (`timeout_s`, 30–900).
- A child that runs out of time comes back as `scaduto`, not
  `errore`: it may have done half the work. Don't read a `scaduto`
  block as an answer; if you still need it, delegate it again.
- Children share your working folder. Parallel readers are fine;
  several writers on the same files are not — split by file, or run
  them one at a time.
- A child can raise a permission prompt on its own (it is leaving
  the folder). The answer covers that path for that child; it does
  not grant its siblings anything.
- Their summaries are self-reports, not verified facts. For
  external side effects (uploads, publishes, remote writes),
  demand a verifiable handle (URL, ID, path) and check it
  yourself before reporting success.

## Rules

- One `delega_multi` call with N objectives beats N `delega`
  calls: same children, one wait instead of N.
- Only truly dependent steps wait for each other.
- Merging N child results? Aggregate programmatically
  (count, dedupe, sort) instead of eyeballing — and say what you
  dropped.
- A child claiming completion without evidence gets its work
  re-checked, not trusted.
- In autonomous goals `delega_multi` has no retry with alternative
  models: to retry a child, delegate it again with `delega`.
