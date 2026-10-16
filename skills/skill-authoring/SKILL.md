---
name: skill-authoring
description: Use when creating or editing an Orchestra skill. SKILL.md format, frontmatter, verification.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Writing Orchestra Skills

A skill is an instruction the agent follows: if it is wrong,
everything built on it is wrong. Write it carefully.

## Format

One flat folder inside `skills/`, one file:

```
skills/<name>/
  SKILL.md
```

`SKILL.md` has frontmatter plus body:

```
---
name: <folder-name>
description: When to use it. One line, with the trigger.
categoria: base
origine: base
---

# Title

Markdown body: what to do, with which commands.
```

- `description` is all the agent always sees (two lines in
  the prompt): it must say WHEN to use the skill, not what
  it contains.
- The body enters context only when the skill is chosen
  (`skill_leggi`), in full: no secrets, no keys, no personal
  data. Ever.
- `categoria: base` groups shipped skills; `origine: base`
  marks them as reviewed by the developers. Skills the agent
  writes itself live elsewhere and carry proofs instead.

## Content rules

- Real commands, never invented: every cited command must
  exist (agent tool or real CLI), every path must be the
  project's real one.
- Procedures, not essays: numbered steps, each verifiable.
- One skill, one job: a different "when" means two skills.

## Language

Write skills in English: shorter, and easier for the agent
to follow than any other language.

## Verify

After writing, re-read it as a stranger and open it with
`skill_leggi <name>`: the full text must come back.
Then `python tests/test_skills.py` must stay green.
