---
name: computer-use
description: Use when the job needs the real desktop: click, type, open apps, read the screen. Real actions, verify each one.
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# Computer Use

Some jobs live outside files and browsers: desktop apps,
system dialogs, installers. Tools: `computer_screenshot`
(see), `computer_click` (click), `computer_type` (type),
`computer_open` (open an app). Real side effects every time.

## How

1. `computer_screenshot` first, always: never click from
   memory of a previous screen. UI state goes stale fast.
2. One action, one verification: after click or type, take
   another screenshot and confirm the expected state before
   the next step.
3. Prefer `computer_open` with the app name over navigating
   menus by coordinates: names survive UI restyling, pixels
   do not.
4. Type into the focused field only: click the field first,
   then `computer_type`, then verify the text landed.

## Rules

- Destructive actions (delete, overwrite, send, install)
  get explicit user confirmation first, describing exactly
  what will happen. No confirmation, no click.
- If the screen does not change after an action, stop and
  re-screenshot instead of clicking harder: repeated clicks
  on the wrong spot cause the damage.
- Credentials are never typed from chat and never stored:
  if a login is needed and no saved login exists, stop and
  ask the user.
