"""Tool `mcp`: gestione client MCP (server, connessioni, tool)."""
from __future__ import annotations

import json

from ..mcp import (
    list_servers, add_server, remove_server, connect, disconnect,
    connect_all, list_tools, stato,
)


def tool_mcp():
    def handler(azione: str = "lista", **kwargs) -> str:
        a = (azione or "lista").strip().lower()
        if a in ("lista", "list", "servers"):
            return json.dumps(list_servers(), ensure_ascii=False, indent=2)
        if a in ("tools", "strumenti"):
            return json.dumps(list_tools(), ensure_ascii=False, indent=2)
        if a in ("stato", "status"):
            return json.dumps(stato(), ensure_ascii=False, indent=2)
        if a in ("aggiungi", "add"):
            cfg = {
                "name": kwargs.get("nome") or kwargs.get("name"),
                "transport": kwargs.get("transport") or "stdio",
                "command": kwargs.get("command") or kwargs.get("comando"),
                "args": kwargs.get("args") or kwargs.get("argomenti") or [],
                "env": kwargs.get("env") or {},
                "url": kwargs.get("url"),
                "enabled": kwargs.get("enabled", True),
            }
            if not cfg["name"]:
                return "errore: nome richiesto"
            if cfg["transport"] == "stdio" and not cfg["command"]:
                return "errore: command richiesto per stdio"
            c = add_server(cfg)
            return "aggiunto: " + json.dumps(c, ensure_ascii=False)
        if a in ("rimuovi", "remove", "delete"):
            sid = kwargs.get("id") or kwargs.get("nome")
            if not sid:
                return "errore: id/nome richiesto"
            ok = remove_server(str(sid))
            return "rimosso" if ok else "non trovato"
        if a in ("connetti", "connect"):
            sid = kwargs.get("id") or kwargs.get("nome")
            if not sid:
                return "errore: id/nome richiesto"
            return json.dumps(connect(str(sid)), ensure_ascii=False)
        if a in ("disconnetti", "disconnect"):
            sid = kwargs.get("id") or kwargs.get("nome")
            if not sid:
                return "errore: id/nome richiesto"
            ok = disconnect(str(sid))
            return "disconnesso" if ok else "non connesso"
        if a in ("connetti_tutti", "connect_all"):
            return json.dumps(connect_all(), ensure_ascii=False, indent=2)
        return ("azioni: lista, tools, stato, aggiungi, rimuovi, connetti, "
                "disconnetti, connetti_tutti")

    schema = {
        "type": "object",
        "properties": {
            "azione": {"type": "string", "default": "lista"},
            "nome": {"type": "string"},
            "id": {"type": "string"},
            "transport": {"type": "string", "enum": ["stdio", "sse"]},
            "command": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "env": {"type": "object"},
            "url": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
    }
    from ..tools import Tool
    return Tool(name="mcp", description="Gestione client MCP: elenca/aggiungi/rimuovi server MCP, connetti/disconnetti, elenca tool remoti. I tool dei server connessi diventano strumenti nativi (prefisso mcp_).", schema=schema, handler=handler)
