---
name: browser-use
description: Use when the job needs a real rendered page: open it, read it, screenshot it. Never claim what you did not load.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Browser Use

Some pages need rendering: JavaScript content, visual checks,
things `web_leggi` cannot see. Tools: `browser_apri` (open),
`browser_render` (read rendered text), `browser_screenshot`
(see the page).

## How

1. `browser_apri` with the exact URL, then `browser_render`
   to read: rendered text is the truth, the raw HTML is not.
2. For anything visual (layout, styling, "does it look
   right"), `browser_screenshot` and look: markup that was
   never seen has never worked.
3. One page at a time: open, read, close the loop before the
   next URL. Five open guesses beat no verification never.

## Rules

- Never describe page content you did not load in this
  session: no cached memories of how a page "usually" looks.
- Dynamic content may need a moment: if the render is empty
  or a loader, wait and re-render once before concluding.
- Downloads, uploads, payments, and anything with side
  effects: confirm with the user first, then act once.
