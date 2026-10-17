---
name: memoria
description: Use when something should be remembered beyond this turn. Search first, one fact per entry, never personal data dumps.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Memory

Memory (`memoria` tool: cerca, aggiungi, modifica, elenca, elimina)
survives sessions. What enters it shapes every future turn:
write little, write well.

## Actions

- `cerca` before adding: a duplicate fact is noise, and noise
  in memory taxes every later session.
- `aggiungi`: one standalone sentence per fact, with the
  subject explicit ("The project builds with..."). No
  pronouns pointing at this conversation.
- `modifica` when a fact is stale or half-wrong: rewrite it in
  place. Do NOT `elimina` + `aggiungi` — that loses the date and
  the origin, and you end up with a duplicate the dedup cannot
  see.
- `elenca` to audit: if you cannot defend an entry's future
  usefulness in one sentence, `elimina` it.

## What belongs

- Stable user facts: name, role, standing preferences.
- Stable project facts: paths that do not move, commands
  that always apply, decisions already taken.
- Nothing else. No turn-by-turn logs, no secrets, no API
  keys, no tokens — ever. No temporary state, no "to do".

## What does not

- Trivial or easily re-discovered facts.
- Procedures: those belong in skills, which load only when
  relevant. Memory loads always, so it stays small.
- Anything the user did not say and the project does not
  show: never invent memories.
