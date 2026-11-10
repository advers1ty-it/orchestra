"""Client MCP (Model Context Protocol).

Permette a Orchestra di connettersi a server MCP esterni — stdio, HTTP
streamable o SSE — ed esporre i loro tool come strumenti nativi. Le
configurazioni stanno in `mcp_servers.json` nella cartella dati.

TRE COSE CHE QUI SONO DIVERSE DA PRIMA

1. Il trasporto e' separato dal protocollo (`mcp_trasporti.py`): aggiungere
   HTTP o SSE non ha ricopiato l'handshake, e non esistono tre initialize
   leggermente diversi.
2. Risorse e prompt fanno parte del protocollo, non solo i tool. Di un
   server si leggono `resources/list` + `resources/read` e `prompts/list`
   + `prompts/get`, e la capacita' dichiarata in `initialize` decide se
   chiederli: un server che non li ha non deve rispondere -32601 a ogni
   connessione.
3. Se il canale muore, ci si riconnette e si rifa' l'handshake. Solo un
   errore di trasporto lo giustifica: un tool che risponde "argomento
   sbagliato" non si risolve riavviando il server, e ritentarlo
   raddoppierebbe l'errore.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any

from .dati import cartella_dati, percorso
from .segreti import scrivi_privato
from .mcp_trasporti import (
    PROTOCOLLO,
    ErroreMCP,
    ErroreTrasporto,
    Trasporto,
    crea,
)


def _path() -> str:
    return percorso("mcp_servers.json")


def _load_config() -> list[dict[str, Any]]:
    p = _path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("servers"), list):
        return data["servers"]
    return []


def _save_config(servers: list[dict[str, Any]]) -> None:
    # Il file contiene anche gli `env` dei server: puo' contenere chiavi.
    cartella_dati()
    scrivi_privato(_path(), json.dumps({"servers": servers}, indent=2,
                                      ensure_ascii=False))


class Connessione:
    """Un server MCP connesso: trasporto, capacita', tool, risorse, prompt."""

    def __init__(self, sid: str, cfg: dict[str, Any]) -> None:
        self.sid = sid
        self.cfg = cfg
        self.name = cfg.get("name") or sid
        self.trasporto: Trasporto = crea(cfg)
        self.tools: list[dict[str, Any]] = []
        self.resources: list[dict[str, Any]] = []
        self.prompts: list[dict[str, Any]] = []
        self.capabilities: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}
        self.protocol = PROTOCOLLO
        self.initialized = False
        self.error = ""
        self.riconnessioni = 0

    def start(self, timeout: float = 20.0, *, riconnessione: bool = False) -> bool:
        self.error = ""
        if not self.trasporto.start(timeout):
            self.error = self.trasporto.error or "trasporto non avviato"
            return False
        try:
            r = self.trasporto.request("initialize", {
                "protocolVersion": PROTOCOLLO,
                "capabilities": {"roots": {"listChanged": False}},
                "clientInfo": {"name": "Orchestra", "version": "0.5"},
            }, timeout=timeout)
            if not isinstance(r, dict):
                raise ErroreTrasporto("risposta initialize non valida")
            self.protocol = str(r.get("protocolVersion") or PROTOCOLLO)
            self.capabilities = r.get("capabilities") or {}
            self.server_info = r.get("serverInfo") or {}
            self.trasporto.request("notifications/initialized", {},
                                   timeout=5.0, notify=True)
            tr = self.trasporto.request("tools/list", {}, timeout=timeout)
            if isinstance(tr, dict):
                self.tools = list(tr.get("tools") or [])
            # Le capacita' decidono cosa chiedere. Se un server le omette
            # ma implementa resources/*, si perde la lista: meglio di
            # chiedere a ogni server due metodi che non ha.
            if "resources" in self.capabilities:
                self._carica_risorse(timeout)
            if "prompts" in self.capabilities:
                self._carica_prompt(timeout)
            self.initialized = True
            if riconnessione:
                self.riconnessioni += 1
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"handshake fallito: {type(e).__name__}: {e}"
            self.stop()
            return False

    def _carica_risorse(self, timeout: float) -> None:
        try:
            r = self.trasporto.request("resources/list", {}, timeout=timeout)
            if isinstance(r, dict):
                self.resources = list(r.get("resources") or [])
        except ErroreMCP as e:
            # -32601: il server dichiara la capacita' ma non il metodo.
            # Non e' un motivo per non usare il server.
            if e.codice != -32601:
                raise

    def _carica_prompt(self, timeout: float) -> None:
        try:
            r = self.trasporto.request("prompts/list", {}, timeout=timeout)
            if isinstance(r, dict):
                self.prompts = list(r.get("prompts") or [])
        except ErroreMCP as e:
            if e.codice != -32601:
                raise

    def request(self, method: str, params: Any = None,
                timeout: float = 30.0) -> Any:
        if not self.initialized:
            raise ErroreTrasporto(f"{self.name}: non connesso")
        return self.trasporto.request(method, params, timeout=timeout)

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None,
                  timeout: float = 60.0) -> Any:
        return self.request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        }, timeout=timeout)

    def stop(self) -> None:
        try:
            self.trasporto.stop()
        except Exception:  # noqa: BLE001
            pass
        self.initialized = False


_connections: dict[str, Connessione] = {}
_lock = threading.Lock()


def _server_id(cfg: dict[str, Any]) -> str:
    return str(cfg.get("id") or cfg.get("name") or uuid.uuid4().hex[:8])


def list_servers() -> list[dict[str, Any]]:
    out = []
    for cfg in _load_config():
        sid = _server_id(cfg)
        conn = _connections.get(sid)
        out.append({
            "id": sid,
            "name": cfg.get("name") or sid,
            "transport": cfg.get("transport") or "stdio",
            "command": cfg.get("command"),
            "args": cfg.get("args") or [],
            "url": cfg.get("url"),
            "enabled": bool(cfg.get("enabled", True)),
            "connected": bool(conn and conn.initialized),
            "error": (conn.error if conn else ""),
            "tools": (len(conn.tools) if conn else 0),
            "resources": (len(conn.resources) if conn else 0),
            "prompts": (len(conn.prompts) if conn else 0),
            "protocol": (conn.protocol if conn else ""),
            "reconnects": (conn.riconnessioni if conn else 0),
        })
    return out


def _find_config(sid: str) -> dict[str, Any] | None:
    for cfg in _load_config():
        if _server_id(cfg) == sid:
            return cfg
    return None


def add_server(cfg: dict[str, Any]) -> dict[str, Any]:
    servers = _load_config()
    sid = _server_id(cfg)
    cfg = dict(cfg)
    cfg["id"] = sid
    servers = [s for s in servers if _server_id(s) != sid]
    servers.append(cfg)
    _save_config(servers)
    return cfg


def remove_server(sid: str) -> bool:
    servers = _load_config()
    nuovi = [s for s in servers if _server_id(s) != sid]
    if len(nuovi) == len(servers):
        return False
    disconnect(sid)
    _save_config(nuovi)
    return True


def _apri(sid: str, cfg: dict[str, Any], timeout: float,
          *, riconnessione: bool = False) -> tuple[Connessione | None, str]:
    """Apre e fa l'handshake. Ritorna (connessione, errore da mostrare)."""
    try:
        conn = Connessione(sid, cfg)
    except ValueError as e:
        return None, str(e)
    if not conn.start(timeout, riconnessione=riconnessione):
        errore = conn.error or "connessione fallita (vedi i log del server)"
        conn.stop()
        return None, errore
    return conn, ""


def connect(sid: str, timeout: float = 20.0) -> dict[str, Any]:
    cfg = _find_config(sid)
    if cfg is None:
        return {"ok": False, "error": "server sconosciuto"}
    disconnect(sid)
    conn, errore = _apri(sid, cfg, timeout)
    if conn is None:
        return {"ok": False, "error": errore}
    with _lock:
        _connections[sid] = conn
    _aggiorna_cache()
    return {"ok": True, "error": "", "tools": len(conn.tools),
            "resources": len(conn.resources), "prompts": len(conn.prompts),
            "transport": cfg.get("transport") or "stdio",
            "protocol": conn.protocol}


def _riconnetti(sid: str, timeout: float = 20.0) -> Connessione | None:
    """Riapre un server morto. None se non si riesce (e lo dice)."""
    cfg = _find_config(sid)
    if cfg is None:
        return None
    with _lock:
        vecchia = _connections.pop(sid, None)
    if vecchia is not None:
        vecchia.stop()
    conn, _errore = _apri(sid, cfg, timeout,
                         riconnessione=vecchia is not None)
    if conn is None:
        return None
    with _lock:
        _connections[sid] = conn
    _aggiorna_cache()
    return conn


def disconnect(sid: str) -> bool:
    with _lock:
        conn = _connections.pop(sid, None)
    if conn is not None:
        conn.stop()
        _aggiorna_cache()
        return True
    return False


def _connessione(sid: str) -> Connessione | None:
    with _lock:
        return _connections.get(sid)


def connect_all(timeout: float = 20.0) -> list[dict[str, Any]]:
    out = []
    for cfg in _load_config():
        if not cfg.get("enabled", True):
            continue
        sid = _server_id(cfg)
        out.append({"id": sid, **connect(sid, timeout=timeout)})
    return out


_tool_cache: list[dict[str, Any]] = []
_resource_cache: list[dict[str, Any]] = []
_prompt_cache: list[dict[str, Any]] = []
_cache_lock = threading.Lock()


def _prefixed(server: str, tool: str) -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_"
                   for c in (server + "__" + tool))
    if not safe.startswith("mcp_"):
        safe = "mcp_" + safe
    return safe


def _aggiorna_cache() -> None:
    global _tool_cache, _resource_cache, _prompt_cache
    nuova_t: list[dict[str, Any]] = []
    nuova_r: list[dict[str, Any]] = []
    nuova_p: list[dict[str, Any]] = []
    for sid, conn in list(_connections.items()):
        if not (conn and conn.initialized):
            continue
        cfg = _find_config(sid) or {}
        server_name = cfg.get("name") or sid
        for t in conn.tools or []:
            tname = t.get("name")
            if not tname:
                continue
            nuova_t.append({
                "server_id": sid,
                "server": server_name,
                "name": tname,
                "prefixed": _prefixed(server_name, tname),
                "description": t.get("description") or "",
                "inputSchema": t.get("inputSchema") or {
                    "type": "object", "properties": {}},
            })
        for r in conn.resources or []:
            uri = r.get("uri")
            if not uri:
                continue
            nuova_r.append({
                "server_id": sid,
                "server": server_name,
                "uri": uri,
                "name": r.get("name") or uri,
                "description": r.get("description") or "",
                "mimeType": r.get("mimeType") or "",
            })
        for p in conn.prompts or []:
            nome = p.get("name")
            if not nome:
                continue
            nuova_p.append({
                "server_id": sid,
                "server": server_name,
                "name": nome,
                "description": p.get("description") or "",
                "arguments": p.get("arguments") or [],
            })
    with _cache_lock:
        _tool_cache = nuova_t
        _resource_cache = nuova_r
        _prompt_cache = nuova_p


def list_tools() -> list[dict[str, Any]]:
    with _cache_lock:
        return [dict(t) for t in _tool_cache]


def list_resources(sid: str | None = None) -> list[dict[str, Any]]:
    with _cache_lock:
        risorse = [dict(r) for r in _resource_cache]
    return [r for r in risorse if not sid or r["server_id"] == sid]


def list_prompts(sid: str | None = None) -> list[dict[str, Any]]:
    with _cache_lock:
        prompt = [dict(p) for p in _prompt_cache]
    return [p for p in prompt if not sid or p["server_id"] == sid]


def _testo_da_contenuto(contenuto: Any) -> str:
    if not isinstance(contenuto, list):
        return json.dumps(contenuto, ensure_ascii=False, default=str)
    parti: list[str] = []
    for c in contenuto:
        if not isinstance(c, dict):
            parti.append(str(c))
            continue
        tipo = c.get("type")
        if tipo == "text":
            parti.append(str(c.get("text") or ""))
        elif tipo == "image":
            parti.append(f"[immagine {c.get('mimeType') or '?'}]")
        elif tipo == "resource":
            risorsa = c.get("resource") or {}
            uri = risorsa.get("uri") if isinstance(risorsa, dict) else ""
            parti.append(f"[risorsa {uri}]")
        elif tipo == "audio":
            parti.append(f"[audio {c.get('mimeType') or '?'}]")
        else:
            parti.append(json.dumps(c, ensure_ascii=False, default=str))
    return "\n".join(parti)


def call_tool(prefixed: str, arguments: dict[str, Any] | None = None) -> str:
    with _cache_lock:
        info = next((t for t in _tool_cache if t["prefixed"] == prefixed), None)
    if info is None:
        return f"tool MCP sconosciuto: {prefixed}"
    sid = info["server_id"]
    conn = _connessione(sid)
    if conn is None or not conn.initialized:
        conn = _riconnetti(sid)
        if conn is None:
            return f"server MCP non connesso: {info['server']}"
    try:
        res = conn.call_tool(info["name"], arguments or {})
    except ErroreTrasporto as e:
        # Il canale e' morto: si riapre e si riprova UNA volta. Se anche
        # la seconda fallisce, il problema non e' il canale e ritentare
        # sarebbe solo un terzo errore.
        conn = _riconnetti(sid)
        if conn is None:
            return (f"il server MCP '{info['server']}' si e' disconnesso e "
                    f"la riconnessione non e' riuscita: {e}")
        if not any(t.get("name") == info["name"] for t in conn.tools):
            return (f"il server MCP '{info['server']}' e' stato riconnesso "
                    f"ma non offre piu' il tool '{info['name']}'")
        try:
            res = conn.call_tool(info["name"], arguments or {})
        except Exception as e2:  # noqa: BLE001
            return f"errore MCP dopo la riconnessione: {type(e2).__name__}: {e2}"
    except Exception as e:  # noqa: BLE001
        return f"errore MCP: {type(e).__name__}: {e}"
    if isinstance(res, dict):
        content = res.get("content")
        if content is not None:
            testo = _testo_da_contenuto(content)
            if res.get("isError"):
                testo = "ERRORE: " + (testo or str(res))
            return testo or json.dumps(res, ensure_ascii=False)
        return json.dumps(res, ensure_ascii=False)
    return str(res)


def read_resource(uri: str, sid: str | None = None) -> str:
    """Il contenuto di una risorsa, per URI. Senza sid si cerca fra tutte."""
    with _cache_lock:
        risorse = list(_resource_cache)
    candidate = [r for r in risorse if r["uri"] == uri
                 and (not sid or r["server_id"] == sid)]
    if not candidate:
        return f"risorsa MCP sconosciuta: {uri}"
    info = candidate[0]
    server = info["server_id"]
    conn = _connessione(server) or _riconnetti(server)
    if conn is None:
        return f"server MCP non connesso: {info['server']}"

    def _leggi(c: Connessione) -> Any:
        return c.request("resources/read", {"uri": uri})

    try:
        res = _leggi(conn)
    except ErroreTrasporto as e:
        conn = _riconnetti(server)
        if conn is None:
            return (f"il server MCP '{info['server']}' si e' disconnesso e "
                    f"la riconnessione non e' riuscita: {e}")
        res = _leggi(conn)
    except Exception as e:  # noqa: BLE001
        return f"errore MCP: {type(e).__name__}: {e}"
    contenuti = (res or {}).get("contents") if isinstance(res, dict) else None
    if not isinstance(contenuti, list):
        return json.dumps(res, ensure_ascii=False, default=str)
    parti: list[str] = []
    for c in contenuti:
        if not isinstance(c, dict):
            parti.append(str(c))
        elif isinstance(c.get("text"), str):
            parti.append(c["text"])
        elif c.get("blob"):
            parti.append(f"[contenuto binario {c.get('mimeType') or '?'}, "
                         f"{len(str(c['blob']))} caratteri base64]")
        else:
            parti.append(json.dumps(c, ensure_ascii=False, default=str))
    return "\n".join(parti)


def get_prompt(nome: str, argomenti: dict[str, Any] | None = None,
               sid: str | None = None) -> str:
    """Un prompt del server, gia' riempito con gli argomenti."""
    with _cache_lock:
        prompt = list(_prompt_cache)
    candidate = [p for p in prompt if p["name"] == nome
                 and (not sid or p["server_id"] == sid)]
    if not candidate:
        return f"prompt MCP sconosciuto: {nome}"
    info = candidate[0]
    server = info["server_id"]
    conn = _connessione(server) or _riconnetti(server)
    if conn is None:
        return f"server MCP non connesso: {info['server']}"

    def _prendi(c: Connessione) -> Any:
        return c.request("prompts/get", {"name": nome,
                                         "arguments": argomenti or {}})

    try:
        res = _prendi(conn)
    except ErroreTrasporto as e:
        conn = _riconnetti(server)
        if conn is None:
            return (f"il server MCP '{info['server']}' si e' disconnesso e "
                    f"la riconnessione non e' riuscita: {e}")
        res = _prendi(conn)
    except Exception as e:  # noqa: BLE001
        return f"errore MCP: {type(e).__name__}: {e}"
    if not isinstance(res, dict):
        return str(res)
    righe: list[str] = []
    if res.get("description"):
        righe.append(str(res["description"]))
    for m in res.get("messages") or []:
        if not isinstance(m, dict):
            continue
        ruolo = m.get("role") or "?"
        contenuto = m.get("content")
        testo = (contenuto.get("text") if isinstance(contenuto, dict)
                 else contenuto)
        righe.append(f"[{ruolo}] {testo}")
    return "\n".join(righe) or json.dumps(res, ensure_ascii=False, default=str)


def registra_tool_nel_registro(registry) -> None:
    try:
        from .tools import Tool
    except Exception:  # noqa: BLE001
        from .tools.__init__ import Tool
    for info in list_tools():
        nome = info["prefixed"]
        schema = info.get("inputSchema") or {"type": "object", "properties": {}}
        if nome in registry:
            continue

        def _handler(_n=nome, **kwargs):
            return call_tool(_n, kwargs)

        tool = Tool(
            name=nome,
            description=f"[MCP:{info['server']}] {info.get('description') or info['name']}",
            schema=schema,
            handler=_handler,
        )
        try:
            registry.registra(tool)
            registry.attiva(tool.name)
        except Exception:  # noqa: BLE001
            pass


def stato() -> dict[str, Any]:
    return {
        "servers": list_servers(),
        "tools": list_tools(),
        "resources": list_resources(),
        "prompts": list_prompts(),
    }
