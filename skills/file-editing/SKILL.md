---
name: file-editing
description: Use when reading, creating, or modifying files. Exact strings, small edits, verify after every change.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# File Editing

Files are edited by exact match, not by intent. Read first, edit
small, verify after.

## Tools

- `read_file` — read before touching. Always.
- `list_dir` — discover what is there; never guess paths.
- `edit_file` — replace an exact string. First occurrence by
  default; `all=true` for all.
- `write_file` — create a new file or replace a whole one. Last
  resort for edits: rewriting 2000 lines risks every line.

## How

1. `read_file` the target and find the exact text to change,
   including whitespace and indentation.
2. `edit_file` with that exact text. If it says "not found",
   re-read the line — do not retry the same string blindly.
3. `read_file` again to confirm the change landed and nothing
   else moved.
4. For a new file, `write_file` once; for a change, prefer
   `edit_file` even when it takes two calls.

## Rules

- Never edit a file you have not read in this session.
- `edit_file` changes the first occurrence; use `all=true` only
  when every occurrence must change (renames, constant swaps).
- Keep edits minimal: one logical change per call. A diff that
  touches unrelated lines is a second task in disguise.
- Paths outside the working folder ask for permission; sensitive
  paths are denied without asking. Do not route around the gate.
- On Windows, paths use backslashes in the shell but forward
  slashes work in the tools. Prefer relative paths inside the
  project.