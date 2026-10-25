---
name: mcp
description: "Client MCP: connessione a server MCP esterni (Supabase, Unreal, Godot, ecc.) che espongono tool. Usa il tool `mcp`."
version: 1.0.0
---

# mcp

Gestisci server MCP esterni con il tool `mcp`.

## Quando usarlo
- L'utente vuole collegare un programma che espone un server MCP (Supabase, Unreal, Godot, filesystem, ecc.).
- Serve un tool non nativo di Orchestra.

## Azioni
- `lista`: elenca i server configurati e stato.
- `tools`: elenca i tool remoti disponibili.
- `stato`: stato completo.
- `aggiungi`: aggiunge un server (nome, transport, command, args, env, url).
- `rimuovi`: rimuove un server (id/nome).
- `connetti` / `disconnetti`: connessione.
- `connetti_tutti`: connette tutti i server abilitati.

## Note
- I server stdio vengono avviati come subprocess. I loro tool diventano strumenti nativi con prefisso `mcp_<server>__<tool>` e sono disponibili nei turni successivi.
- La UI "MCP" permette configurazione grafica.
- I server vengono connessi automaticamente all'avvio di Orchestra.
