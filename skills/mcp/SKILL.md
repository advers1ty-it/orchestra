---
name: mcp
description: "MCP client: connect to external MCP servers (Supabase, Unreal, Godot, etc.) that expose tools. Uses the `mcp` tool."
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# mcp

Manage external MCP servers with the `mcp` tool.

## When to use it
- The user wants to connect a program that exposes an MCP server (Supabase, Unreal, Godot, filesystem, etc.).
- A tool is needed that Orchestra does not have natively.

## Actions
- `lista`: lists the configured servers and their state.
- `tools`: lists the remote tools available.
- `stato`: full state.
- `aggiungi`: adds a server (nome, transport, command, args, env, url). For `stdio`, `command` and `args` start a local process; for HTTP use `url` and the transport the tool supports.
- `rimuovi`: removes a configured server (id/nome); it does not uninstall the software nor delete data on the remote server.
- `connetti` / `disconnetti`: connect and disconnect.
- `connetti_tutti`: connects every enabled server.

## Notes
- `stdio` servers are started as subprocesses. Their tools become native tools with the prefix `mcp_<server>__<tool>` and are available in later turns.
- Enabled servers are connected automatically when Orchestra starts; check their state with `mcp` -> `stato` or `lista`.
- The "MCP" UI allows graphical configuration.
- Treat `command`, `args`, `env` and `url` as executable/network configuration: use only trusted servers and never put secrets in visible fields or in logs.
