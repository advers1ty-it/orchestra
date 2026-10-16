---
name: delega
description: Use when a job splits into independent parts. Hand each to a sub-agent with minimal context, one level only.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Delegation

The `delega` tool spawns sub-agents with their own context
(`obiettivo` required, `contesto` optional). They return only
a final summary: what they send back is what you get.

## When

- Independent workstreams that run in parallel.
- Reasoning-heavy subtasks that would flood this context.
- Never for a single tool call, user interaction, or durable
  work: subagents cannot ask questions and die with the session.

## How

- One level only: children cannot delegate further. Pass
  everything the child needs in `contesto` — it knows nothing
  of this conversation, including output language and style.
- One task, one child: vague goals return vague summaries.
- Their summaries are self-reports, not verified facts. For
  external side effects (uploads, publishes, remote writes),
  demand a verifiable handle (URL, ID, path) and check it
  yourself before reporting success.

## Rules

- Independent calls go in one block; only truly dependent
  steps wait.
- Merging N child results? Aggregate programmatically
  (count, dedupe, sort) instead of eyeballing.
- A child claiming completion without evidence gets its work
  re-checked, not trusted.
