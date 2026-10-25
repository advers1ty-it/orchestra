---
name: local-web-ui
description: Use when building or touching a local web interface. Plain HTML/CSS/JS only, verify with curl before calling it done.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Local Web UI

Local interfaces: plain HTML, CSS, JavaScript, zero installable
dependencies. If a server is needed, the project's own or
`python -m http.server` — no new toolchain for a check.

## Build

- One file does everything, or a few files with obvious names.
- No frameworks, no build step: the page must open and work
  as it is.
- Error texts and states in the user's language.

## Verify (mandatory)

1. Serve the page and hit it with `run_shell` + `curl`:
   status must be 200 and the body the expected one.
2. If the project has browser tools (`browser_render`,
   `browser_screenshot`, `screenshot_view`), use them to
   actually see the page: markup that "should" work has not
   worked until seen. `screenshot_view` after the capture,
   otherwise the model has a path and not a page.
3. Clean console: no JavaScript errors. A forgotten
   `console.log` is noise, an exception is a bug.

## Never

Never say "it works" without loading the page at least once
after the last edit. The last edit is always the one that
breaks it.
