---
name: storico
description: Use when the user refers to something discussed in a past session ("that thing we talked about", "how did we do X"). Search history before answering.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Past Conversations

Some answers live in earlier sessions, not in memory. Memory is for
stable facts; history is for what actually happened.

## When

- The user says "that thing we talked about", "as we did before",
  "like last time", "do you remember when...".
- A task seems to repeat a previous one and the earlier approach
  might save work.
- You need to recover a decision, a command, or a file path from
  a past chat.

## How

1. `storico_cerca` with a query of 2-4 specific words (the topic,
   a filename, an error message). Vague queries return noise.
2. Read the returned excerpts: they cite the session and the turn.
   Do not treat a summary as the full exchange — open the session
   if the detail matters.
3. Cross-check against the current repo state: past commands may
   have been run in a different tree.

## Rules

- Never invent a past conversation. If `storico_cerca` returns
  nothing, say so and proceed from the present.
- Do not dump whole sessions into context: quote the one line that
  answers, then stop.
- History is read-only: it informs the answer, it is not a source
  of truth for the current code. Verify before acting.
- One search, then decide. Re-searching with the same words is
  not progress.