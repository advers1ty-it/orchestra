---
name: mcp
description: "Client MCP: connessione a server MCP esterni (Supabase, Unreal, Godot, ecc.) che espongono tool. Usa il tool `mcp`."
version: 1.0.0
author: Orchestra
categoria: base
origine: base
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
- `aggiungi`: aggiunge un server (nome, transport, command, args, env, url). Per `stdio`, `command` e `args` avviano un processo locale; per HTTP usa `url` e il transport supportato dal tool.
- `rimuovi`: rimuove un server configurato (id/nome); non disinstalla il software né elimina dati del server remoto.
- `connetti` / `disconnetti`: connessione.
- `connetti_tutti`: connette tutti i server abilitati.

## Note
- I server `stdio` vengono avviati come subprocess. I loro tool diventano strumenti nativi con prefisso `mcp_<server>__<tool>` e sono disponibili nei turni successivi.
- I server abilitati vengono connessi automaticamente all'avvio di Orchestra; verificane lo stato con `mcp` → `stato` o `lista`.
- La UI "MCP" permette configurazione grafica.
- Tratta `command`, `args`, `env` e `url` come configurazione eseguibile/di rete: usa solo server fidati e non inserire segreti nei campi visibili o nei log.
