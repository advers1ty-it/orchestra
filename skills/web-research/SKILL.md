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

## If search is not installed

`web_cerca` needs the `ddgs` library (the only network
dependency: `ddgs>=9.0` in requirements.txt). If it answers
that search is not installed, activate it yourself:

1. `run_shell` with `python -m pip install "ddgs>=9.0"`
   (on Windows `py -m pip install "ddgs>=9.0"` if `python`
   is not found).
2. Verify with `run_shell` and
   `python -c "import ddgs; print('ok')"`.
3. Retry the original `web_cerca` once.

If the install fails (no network, no permissions), say so
and keep working local-only: search is optional, the rest
is not.

## Rules

- Cite real URLs you opened, never from memory: an invented
  link is worse than no link.
- Separate "read in the docs" from "deduced": the second
  sentence starts with "probably".
- If sources contradict each other, say so instead of
  silently picking one.
- No search for what you already know: it costs time and
  adds nothing.
