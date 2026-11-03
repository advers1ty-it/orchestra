---
name: code-search
description: Use when you need to find code, a symbol, a message or a file in the project. Search before reading; never guess paths.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Code Search

A project is too big to read. Find the few lines that matter, then
read only those.

## Tools

- `search_text` — content search. Returns `file:line: text`.
  Options: `pattern` (text or regex), `path`, `glob` (e.g. `*.py`),
  `max_results`, `case_sensitive`, `context`.
- `find_files` — name/path search with a glob (`*.ts`,
  `src/**/test_*.py`). Without wildcards it matches names containing
  the string.
- `read_file` — only after you know which file and which lines.

## How

1. If you know the name, `find_files`. If you know a word that must
   appear, `search_text`.
2. Start narrow: pass `path` (a folder) and `glob` (an extension).
   A search across everything is slower and returns other people's
   code from `node_modules`.
3. Add `context=1` or `2` only when the matching line alone is
   ambiguous. Context multiplies the output.
4. Read the file around the hit with `read_file` and `start_line` /
   `end_line`, not the whole file.

## Rules

- Never say "it does not exist" from a search that hit the scan
  limit: the result says the scan was incomplete. Narrow it and
  search again.
- A regex with `(`, `[`, `*`, `+`, `?` must be valid; if the error
  says the regex is broken, that is the problem, not an empty
  project. Escape literal characters.
- `.env`, `.ssh`, keys and `.git/config` are never searched or
  read. Do not try to work around it.
- Searching is cheap; guessing a path is expensive. Search first.
