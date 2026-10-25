"""Client MCP (Model Context Protocol).

Permette a Orchestra di connettersi a server MCP esterni (stdio o SSE/HTTP)
ed esporre i loro tool come strumenti nativi. Le configurazioni dei server
sono salvate in `mcp_servers.json` nella cartella dati.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from typing import Any

from .dati import cartella_dati, percorso


def _path() -> str:
    return percorso("mcp_servers.json")


def _load_config() -> list[dict[str, Any]]:
    p = _path()
    if not os.path.exists(p):
        return []
    try:
        data = json.load(open(p, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("servers"), list):
        return data["servers"]
    return []


def _save_config(servers: list[dict[str, Any]]) -> None:
    cartella_dati()
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"servers": servers}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path())


class StdioConnection:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.name = cfg.get("name") or cfg.get("id") or "mcp"
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._next_id = 1
        self._reader: threading.Thread | None = None
        self.tools: list[dict[str, Any]] = []
        self.initialized = False
        self.error = ""

    def start(self, timeout: float = 20.0) -> bool:
        self.error = ""
        try:
            env = dict(os.environ)
            for k, v in (self.cfg.get("env") or {}).items():
                env[str(k)] = str(v)
            cmd = [self.cfg.get("command")] + list(self.cfg.get("args") or [])
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except Exception as e:
            self.error = f"avvio fallito: {type(e).__name__}: {e}"
            return False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            r = self.request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Orchestra", "version": "0.5"},
            }, timeout=timeout)
            if not isinstance(r, dict):
                raise RuntimeError("risposta initialize non valida")
            self.request("notifications/initialized", {}, timeout=5.0, notify=True)
            tr = self.request("tools/list", {}, timeout=timeout)
            if isinstance(tr, dict):
                self.tools = list(tr.get("tools") or [])
            self.initialized = True
            return True
        except Exception as e:
            self.error = f"handshake fallito: {type(e).__name__}: {e}"
            self.stop()
            return False

    def _read_loop(self) -> None:
        try:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = obj.get("id")
                if rid is None:
                    continue
                with self._lock:
                    q = self._pending.get(rid)
                if q is not None:
                    q.put(obj)
        except Exception:
            pass

    def request(self, method: str, params: Any = None, timeout: float = 20.0,
                notify: bool = False) -> Any:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("processo non avviato")
        if notify:
            msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            return None
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            q = queue.Queue()
            self._pending[rid] = q
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            with self._lock:
                self._pending.pop(rid, None)
            raise RuntimeError(f"scrittura fallita: {e}")
        try:
            obj = q.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(rid, None)
            raise RuntimeError(f"timeout dopo {timeout}s su {method}")
        with self._lock:
            self._pending.pop(rid, None)
        if isinstance(obj, dict) and "error" in obj:
            err = obj["error"]
            raise RuntimeError(str(err.get("message") if isinstance(err, dict) else err))
        return obj.get("result") if isinstance(obj, dict) else obj

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None,
                  timeout: float = 60.0) -> Any:
        return self.request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        }, timeout=timeout)

    def stop(self) -> None:
        try:
            if self.proc is not None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        self.proc = None
        self.initialized = False


_connections: dict[str, StdioConnection] = {}
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
            "env": cfg.get("env") or {},
            "url": cfg.get("url"),
            "enabled": bool(cfg.get("enabled", True)),
            "connected": bool(conn and conn.initialized),
            "error": (conn.error if conn else ""),
            "tools": (len(conn.tools) if conn else 0),
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


def connect(sid: str, timeout: float = 20.0) -> dict[str, Any]:
    cfg = _find_config(sid)
    if cfg is None:
        return {"ok": False, "error": "server sconosciuto"}
    disconnect(sid)
    transport = (cfg.get("transport") or "stdio").lower()
    if transport != "stdio":
        return {"ok": False, "error": f"transport '{transport}' non supportato (solo stdio)"}
    if not cfg.get("command"):
        return {"ok": False, "error": "command mancante"}
    conn = StdioConnection(cfg)
    ok = conn.start(timeout=timeout)
    with _lock:
        if ok:
            _connections[sid] = conn
        else:
            _connections.pop(sid, None)
    if ok:
        _aggiorna_tool_cache()
    return {"ok": ok, "error": conn.error, "tools": len(conn.tools)}


def disconnect(sid: str) -> bool:
    with _lock:
        conn = _connections.pop(sid, None)
    if conn is not None:
        conn.stop()
        _aggiorna_tool_cache()
        return True
    return False


def connect_all(timeout: float = 20.0) -> list[dict[str, Any]]:
    out = []
    for cfg in _load_config():
        if not cfg.get("enabled", True):
            continue
        sid = _server_id(cfg)
        out.append({"id": sid, **connect(sid, timeout=timeout)})
    return out


_tool_cache: list[dict[str, Any]] = []
_cache_lock = threading.Lock()


def _prefixed(server: str, tool: str) -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in (server + "__" + tool))
    if not safe.startswith("mcp_"):
        safe = "mcp_" + safe
    return safe


def _aggiorna_tool_cache() -> None:
    global _tool_cache
    nuova: list[dict[str, Any]] = []
    for sid, conn in list(_connections.items()):
        if not (conn and conn.initialized):
            continue
        cfg = _find_config(sid) or {}
        server_name = cfg.get("name") or sid
        for t in conn.tools or []:
            tname = t.get("name")
            if not tname:
                continue
            nuova.append({
                "server_id": sid,
                "server": server_name,
                "name": tname,
                "prefixed": _prefixed(server_name, tname),
                "description": t.get("description") or "",
                "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
            })
    with _cache_lock:
        _tool_cache = nuova


def list_tools() -> list[dict[str, Any]]:
    with _cache_lock:
        return [dict(t) for t in _tool_cache]


def call_tool(prefixed: str, arguments: dict[str, Any] | None = None) -> str:
    info = None
    with _cache_lock:
        for t in _tool_cache:
            if t["prefixed"] == prefixed:
                info = t
                break
    if info is None:
        return f"tool MCP sconosciuto: {prefixed}"
    sid = info["server_id"]
    with _lock:
        conn = _connections.get(sid)
    if conn is None or not conn.initialized:
        return f"server MCP non connesso: {info['server']}"
    try:
        res = conn.call_tool(info["name"], arguments or {})
    except Exception as e:
        return f"errore MCP: {type(e).__name__}: {e}"
    if isinstance(res, dict):
        content = res.get("content")
        if isinstance(content, list):
            parti = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text":
                        parti.append(str(c.get("text") or ""))
                    elif c.get("type") == "image":
                        parti.append(f"[image {c.get('mimeType')}]")
                    elif c.get("type") == "resource":
                        parti.append(str(c.get("resource") or ""))
                    else:
                        parti.append(json.dumps(c, ensure_ascii=False))
                else:
                    parti.append(str(c))
            testo = "\n".join(parti)
            if res.get("isError"):
                testo = "ERRORE: " + (testo or str(res))
            return testo or json.dumps(res, ensure_ascii=False)
        return json.dumps(res, ensure_ascii=False)
    return str(res)


def registra_tool_nel_registro(registry) -> None:
    try:
        from .tools import Tool
    except Exception:
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
        except Exception:
            pass


def stato() -> dict[str, Any]:
    return {
        "servers": list_servers(),
        "tools": list_tools(),
    }
