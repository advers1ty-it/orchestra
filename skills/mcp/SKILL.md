---
name: mcp
description: "Connect external services and local programs over MCP (GitHub, GitLab, Supabase, Neon, Notion, Linear, Sentry, Stripe, Cloudflare, Datadog, PostHog, Unreal Engine, Unity, Godot, Blender, FreeCAD, GIMP, PostgreSQL, MongoDB, Redis, Grafana, Playwright, filesystem, OAuth services). Uses the mcp tool and ready presets: ask the user only for the token, folder or project, never for command, args or transport when a preset exists."
version: 2.0.0
author: Orchestra
categoria: base
origine: base
---

# MCP

The `mcp` tool already knows the configuration of the most-used services.
Do not ask the user for a server name, transport, command, package or URL
when a preset covers the service. Ask only for the value the user owns:
usually one token, one folder, or one project path.

## First: read the catalog

```
mcp(azione="preset")
```

Returns `id`, name, transport, whether it uses OAuth, documentation, and
the fields the user must provide. To inspect one preset:

```
mcp(azione="preset", preset="github")
```

Never invent a preset id. If the service is not in the catalog, say so
and follow "No preset" below.

## Flow for a covered service

1. Identify the service from the user's request.
2. Read its preset. If a field is missing, ask for that field only, in
   one message. For a token, give the exact page from `dove` and the
   minimum permissions. Never ask the user to paste a token if the
   preset uses OAuth (`notion`, `remoto`): that flow opens the browser.
3. Add it with the preset and the values:

   ```
   mcp(azione="aggiungi", preset="github",
       valori={"token": "<the token the user provided>"})
   ```

   Do not pass `transport`, `command`, `args`, `url` or `headers` for a
   preset: the preset already contains them. The tool returns only the
   configured key names, never the secret.
4. Connect and verify:

   ```
   mcp(azione="connetti", id="github")
   mcp(azione="tools", id="github")
   ```

   A connection is successful only if the result says `ok` and the
   server exposes at least one tool, resource or prompt. If it fails,
   report the exact error; do not say "connected" from the fact that the
   config was written.
5. Tell the user which tools became available. The remote tools are
   named `mcp_<server>__<tool>` and can be used in later turns.

## Presets

The catalog is the authoritative list (over 50 presets). These are the
families; never assume a preset exists without reading it first.

- Online with a token: `github`, `gitlab`, `supabase`, `neon`,
  `datadog`, `sentry`, `stripe`, `firecrawl`, `exa`, `context7`,
  `huggingface`, `cloudflare`, `airtable`, `resend`, `semgrep`,
  `posthog`, `pagerduty`, `linear`. Ask only for the token; it goes in
  `valori` and is stored in the private config, never printed.
- Online without a token: `deepwiki` (public repositories), `twilio`
  (documentation only).
- OAuth through `npx mcp-remote`: `notion`, `atlassian`, `clickup`,
  `netlify`, `miro`, `paypal`. No token; the first connect opens the
  browser. Requires Node/npx. Some providers do not allow generic
  clients: if the browser flow says the client is not registered, say so
  and do not invent a client id.
- `remoto`: generic OAuth bridge for another remote MCP URL.
- Local programs/apps: `unreal`, `godot`, `blender`, `unity`, `freecad`,
  `gimp`, `krita`, `inkscape`, `jetbrains`, `obsidian`. The app and its
  plugin/addon must be installed and running; some presets ask for a
  project or folder.
- Local data and infrastructure: `postgres`, `sqlite`, `mongodb`,
  `redis`, `grafana`, `terraform`, `elasticsearch`. Prefer read-only
  roles/tokens; PostgreSQL is a preview and Redis has no built-in
  read-only mode.
- Local utilities: `playwright`, `filesystem`, `memory`,
  `sequential-thinking`, `fetch`, `git`, `time`, `chrome-devtools`,
  `desktop-commander`. `desktop-commander` is powerful: mention that it
  can read files and run commands. Confine `git` and `filesystem` to a
  project folder; never expose a home directory or whole drive unless
  the user explicitly asks. For `filesystem`, `git`, `desktop-commander`,
  databases, Terraform and filesystem the UI requires an explicit
  confirmation both before adding and before pressing Connetti; it does
  not auto-connect, and `connect_all`/startup also skip them. The tool's
  `connetti` action also goes through the permission gate for these
  presets. Never bypass those confirmations.

For a local program, adding the config can succeed while connecting
fails because the editor/app is not running. Report that distinction:
"config added, connection failed" is not "connected".

Many local presets need Node 24+ (npx reference servers), `uv` (uvx
presets) or Docker (Terraform). If the command is missing, report the
missing prerequisite; do not install software without asking.

For `filesystem` and any other stdio preset, Orchestra asks the user to
confirm running the local command. Explain that the confirmation is
about executing `npx` locally, not about the remote service.

## No preset

Only when the catalog has nothing for the service:

1. Read the official documentation and identify the transport and the
   exact command/URL. Do not guess.
2. For a remote server with a static token use `transport="http"` (or
   `"sse"` only if the docs require it), `url`, and `headers`.
3. For a local server use `transport="stdio"`, `command` and `args`.
4. Add with `azione="aggiungi"` and connect, then verify as above.

Slack, Asana, Figma, HubSpot, Dropbox and Vercel require a
pre-registered app or a client allowlist and are not covered by a
preset yet. Google Workspace also needs its own OAuth setup. Say that
plainly instead of inventing a token header.

## Safety and cleanup

- Treat a token as a secret: never echo it in the final answer, in a
  log, or in a command line. Put it only in `valori`/`headers`/`env`.
- Do not enable a server that can write to a production service without
  telling the user. Prefer read-only tokens or documented read-only
  endpoints when they exist.
- `mcp(azione="rimuovi", id=...)` removes the local configuration only:
  it does not revoke the token or delete remote data. Say so.
- If the user asks to disconnect, use `disconnetti`; the config remains
  and can be reconnected later.
