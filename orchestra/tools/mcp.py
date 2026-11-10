"""Tool `mcp`: gestione client MCP (server, connessioni, tool)."""
from __future__ import annotations

import json

from ..mcp import (
    list_servers, add_server, remove_server, connect, disconnect,
    connect_all, list_tools, list_resources, list_prompts, read_resource,
    get_prompt, stato,
)


def tool_mcp():
    def handler(azione: str = "lista", **kwargs) -> str:
        a = (azione or "lista").strip().lower()
        if a in ("lista", "list", "servers"):
            return json.dumps(list_servers(), ensure_ascii=False, indent=2)
        if a in ("tools", "strumenti"):
            return json.dumps(list_tools(), ensure_ascii=False, indent=2)
        if a in ("risorse", "resources"):
            return json.dumps(list_resources(kwargs.get("id")),
                              ensure_ascii=False, indent=2)
        if a in ("risorsa", "leggi_risorsa", "read_resource"):
            uri = kwargs.get("uri") or kwargs.get("risorsa")
            if not uri:
                return "errore: uri richiesto"
            return read_resource(str(uri), kwargs.get("id"))
        if a in ("prompt", "prompts"):
            if kwargs.get("nome") or kwargs.get("prompt"):
                nome = kwargs.get("nome") or kwargs.get("prompt")
                return get_prompt(str(nome),
                                  kwargs.get("argomenti") or {},
                                  kwargs.get("id"))
            return json.dumps(list_prompts(kwargs.get("id")),
                              ensure_ascii=False, indent=2)
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
                "headers": kwargs.get("headers") or {},
                "enabled": kwargs.get("enabled", True),
            }
            if not cfg["name"]:
                return "errore: nome richiesto"
            if cfg["transport"] == "stdio" and not cfg["command"]:
                return "errore: command richiesto per stdio"
            if cfg["transport"] in ("http", "sse") and not cfg["url"]:
                return f"errore: url richiesto per {cfg['transport']}"
            if cfg["transport"] == "stdio":
                # Un server stdio e' un processo locale: la policy della
                # shell vale anche qui, e serve una conferma esplicita
                # dell'utente. Senza, un bot senza `run_shell` poteva
                # aggiungere un server e farsi eseguire un comando.
                from .. import policy as policy_mod
                from ._guard import _gate
                comando = str(cfg.get("command") or "").strip()
                argomenti = [str(a) for a in (cfg.get("args") or [])]
                blocco = policy_mod.motivo_blocco(" ".join([comando] + argomenti))
                if blocco:
                    return f"NON AGGIUNTO: {blocco}"
                gate = _gate()
                if gate is None:
                    return ("NON AGGIUNTO: un server MCP stdio esegue un "
                            "programma locale; serve una conferma dell'utente.")
                dettaglio = (f"{cfg['name']}: {comando} "
                             f"{' '.join(argomenti)}")[:200]
                # Il soggetto della domanda e' il server, non il percorso
                # dell'eseguibile: un Python in Program Files non e' un
                # file di sistema che il gate deve vietare a priori.
                if not gate.chiedi_all_utente(str(cfg["name"]),
                                              "eseguire un server MCP",
                                              dettaglio):
                    return "NON AGGIUNTO: permesso non concesso."
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
        return ("azioni: lista, tools, risorse, risorsa, prompt, stato, "
                "aggiungi, rimuovi, connetti, disconnetti, connetti_tutti")

    # Ogni parametro qui sotto aveva il TIPO e niente descrizione: lo
    # schema diceva al modello che `args` era una lista di stringhe, ma
    # non che fossero gli argomenti del processo del server. Un
    # parametro senza descrizione e' un parametro che il modello
    # riempie a caso, o omette.
    schema = {
        "type": "object",
        "properties": {
            "azione": {"type": "string", "default": "lista",
                       "description": (
                           "What to do: lista (list servers), tools, "
                           "risorse (resources), risorsa (read one resource), "
                           "prompt, stato (status), aggiungi (add), rimuovi "
                           "(remove), connetti (connect), disconnetti "
                           "(disconnect), connetti_tutti (connect all). "
                           "Default: lista."
                       )},
            "nome": {"type": "string",
                     "description": (
                         "Server name (for aggiungi) or prompt name (for "
                         "prompt)."
                     )},
            "id": {"type": "string",
                   "description": (
                       "Id of an already configured server, to target it "
                       "with the other actions."
                   )},
            "transport": {"type": "string",
                          "enum": ["stdio", "http", "sse"],
                          "description": (
                              "How to reach the server: stdio (a local "
                              "process), http or sse (a URL)."
                          )},
            "command": {"type": "string",
                        "description": (
                            "Executable to launch (stdio only), e.g. "
                            "`npx` or `python`."
                        )},
            "args": {"type": "array", "items": {"type": "string"},
                     "description": (
                         "Arguments of `command`, one per item, e.g. "
                         "['-y', '@modelcontextprotocol/server-filesystem', "
                         "'D:/progetti']"
                     )},
            "env": {"type": "object",
                    "description": (
                        "Extra environment variables for the server "
                        "process, e.g. {\"API_KEY\": \"...\"}."
                    )},
            "url": {"type": "string",
                    "description": "Server URL (http and sse only)."},
            "headers": {"type": "object",
                        "description": (
                            "HTTP headers sent with every request (http "
                            "and sse), e.g. an Authorization token."
                        )},
            "uri": {"type": "string",
                    "description": (
                        "URI of the resource to read, for azione=risorsa."
                    )},
            "argomenti": {"type": "object",
                          "description": (
                              "Arguments of the prompt, for azione=prompt: "
                              "{name: value} as the prompt declares them."
                          )},
            "enabled": {"type": "boolean",
                        "description": (
                            "Whether the server starts enabled (default "
                            "true)."
                        )},
        },
    }
    from ..tools import Tool
    return Tool(name="mcp", description=(
        "MCP client management: list, add and remove servers (stdio, http, "
        "sse), connect and disconnect them, list their tools, resources and "
        "prompts. Tools of connected servers become native tools with the "
        "mcp_ prefix."),
        schema=schema, handler=handler)
