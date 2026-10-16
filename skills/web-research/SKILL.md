---
name: web-research
description: Use when the answer depends on recent or external facts. Search the web, open pages, cite sources.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Web Research

Model memory expires: prices, versions, APIs, news get checked,
not remembered.

## How

1. `web_cerca` with precise queries, better several with
   different words: the first result page always has an opinion.
2. `web_leggi` on pages that promise the answer: search gives
   title plus summary, this gives the page. Summaries never
   suffice for details (signatures, parameters, exact prices).
3. Cross at least two independent sources before asserting.
   One source is hearsay with a URL.

## Rules

- Cite real URLs you opened, never from memory: an invented
  link is worse than no link.
- Separate "read in the docs" from "deduced": the second
  sentence starts with "probably".
- If sources contradict each other, say so instead of
  silently picking one.
- No search for what you already know: it costs time and
  adds nothing.
