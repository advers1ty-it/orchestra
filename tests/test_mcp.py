"""Il client MCP: tre trasporti, risorse, prompt, riconnessione.

I server sono finti e girano qui: uno via stdio (`_mcp_fake.py`), uno HTTP
in-process che parla sia streamable HTTP sia SSE legacy. Un test che
dipendesse da un server MCP esterno non girerebbe offline e non
proverebbe i casi che contano.

I casi che contano:

- i tre trasporti devono produrre la STESSA cosa (tool, risorse, prompt);
- un server che muore deve essere riaperto una volta, e la chiamata deve
  riuscire — non restare appesa fino al timeout;
- un errore del protocollo (argomenti sbagliati) NON deve far
  riconnettere: sarebbe un secondo errore travestito da rimedio.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

TMP = tempfile.mkdtemp(prefix="orchestra_mcp_")
os.environ["ORCHESTRA_HOME"] = os.path.join(TMP, "dati")

from orchestra import mcp  # noqa: E402
from orchestra.mcp_trasporti import _risposta_da_sse  # noqa: E402
from orchestra.tools import ToolRegistry  # noqa: E402

FAKE = os.path.join(RADICE, "tests", "_mcp_fake.py")
PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# ---------------------------------------------------------------------------
# Server finti
# ---------------------------------------------------------------------------

TOOLS = [
    {"name": "echo", "description": "echo back",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}}}},
    {"name": "sse", "description": "risponde in SSE",
     "inputSchema": {"type": "object", "properties": {}}},
]

_SSE_CODA: list = []  # una coda per la sessione SSE legacy


def risultato(method: str, params: dict) -> dict:
    if method == "initialize":
        return {"protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "http-fake", "version": "1"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "resources/list":
        return {"resources": [{"uri": "file:///nota.txt", "name": "nota",
                               "mimeType": "text/plain"}]}
    if method == "resources/read":
        return {"contents": [{"uri": params.get("uri"),
                              "mimeType": "text/plain",
                              "text": "testo della risorsa via http"}]}
    if method == "prompts/list":
        return {"prompts": [{"name": "saluta",
                             "arguments": [{"name": "nome"}]}]}
    if method == "prompts/get":
        nome = (params.get("arguments") or {}).get("nome")
        return {"messages": [{"role": "user", "content": {
            "type": "text", "text": "Ciao " + str(nome)}}]}
    if method == "tools/call":
        nome = params.get("name")
        return {"content": [{"type": "text",
                             "text": f"HTTP-ECHO: {nome} "
                                     f"{(params.get('arguments') or {})}"}],
                "isError": False}
    raise KeyError(method)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    sessione = "sessione-di-prova"

    def log_message(self, *a):  # niente rumore nei test
        pass

    def _invia(self, corpo: bytes, ctype: str, stato: int = 200,
               extra: dict | None = None) -> None:
        self.send_response(stato)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            self._invia(b"{}", "application/json", 400)
            return
        method = body.get("method") or ""
        rid = body.get("id")
        if method.startswith("notifications/"):
            self._invia(b"", "application/json", 202)
            return
        if self.path.startswith("/messages"):
            # Trasporto SSE legacy: la risposta torna sul flusso GET.
            _SSE_CODA.append({"jsonrpc": "2.0", "id": rid,
                              "result": risultato(method,
                                                  body.get("params") or {})})
            self._invia(b"", "application/json", 202)
            return
        try:
            res = risultato(method, body.get("params") or {})
            obj = {"jsonrpc": "2.0", "id": rid, "result": res}
        except KeyError:
            # Un metodo sconosciuto e' un errore JSON-RPC, non un guasto
            # del canale: e' esattamente la distinzione da verificare.
            obj = {"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32601,
                             "message": "metodo sconosciuto"}}
        if method == "tools/call" and (body.get("params") or {}).get("name") == "sse":
            corpo = ("event: message\ndata: " + json.dumps(obj) + "\n\n").encode()
            self._invia(corpo, "text/event-stream")
            return
        extra = {"Mcp-Session-Id": self.sessione} if method == "initialize" else {}
        self._invia(json.dumps(obj).encode(), "application/json", 200, extra)

    def do_DELETE(self):
        self._invia(b"", "application/json", 200)

    def do_GET(self):
        if not self.path.startswith("/sse"):
            self._invia(b"no", "text/plain", 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /messages\n\n")
        self.wfile.flush()
        fine = time.time() + 8
        while time.time() < fine and not SERVER_GIU.is_set():
            if _SSE_CODA:
                obj = _SSE_CODA.pop(0)
                testo = ("event: message\ndata: " + json.dumps(obj) + "\n\n")
                self.wfile.write(testo.encode())
                self.wfile.flush()
            time.sleep(0.02)


SERVER_GIU = threading.Event()
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORTA = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORTA}"

# ---------------------------------------------------------------------------
# stdio
# ---------------------------------------------------------------------------

print("\n== stdio: tool, risorse e prompt dallo stesso server ==")

mcp.add_server({"id": "finto", "name": "finto", "transport": "stdio",
                "command": sys.executable, "args": [FAKE]})
r = mcp.connect("finto", timeout=15)
check("connessione stdio riuscita", r.get("ok"), str(r))
check("due tool elencati", r.get("tools") == 2, str(r))
check("una risorsa elencata", r.get("resources") == 1, str(r))
check("un prompt elencato", r.get("prompts") == 1, str(r))
check("il protocollo viene dal server", r.get("protocol") == "2024-11-05",
      str(r.get("protocol")))

tools = {t["name"]: t for t in mcp.list_tools()}
check("il tool arriva prefissato", "echo" in tools, str(sorted(tools)))
echo = tools["echo"]["prefixed"]
check("la chiamata risponde", "ECHO: ciao" in mcp.call_tool(echo, {"text": "ciao"}),
      mcp.call_tool(echo, {"text": "ciao"}))
check("la risorsa si legge",
      "contenuto della risorsa" in mcp.read_resource("file:///note.txt"),
      mcp.read_resource("file:///note.txt"))
check("il prompt si riempie",
      "Riassumi: testo" in mcp.get_prompt("riassumi", {"testo": "testo"}),
      mcp.get_prompt("riassumi", {"testo": "testo"}))
check("una risorsa sconosciuta non solleva",
      "sconosciuta" in mcp.read_resource("file:///non-esiste.txt"))

print("\n== stdio: un processo morto viene riaperto una volta ==")

crash = tools["crash"]["prefixed"]
prima = mcp._connessione("finto").riconnessioni
esito = mcp.call_tool(crash, {})
check("la chiamata che uccide il server non appende", isinstance(esito, str),
      str(esito))
check("lo dice", "errore" in esito.lower() or "riconness" in esito.lower(),
      str(esito))
check("il server e' stato riconnesso", mcp._connessione("finto") is not None)
dopo = mcp._connessione("finto").riconnessioni
check("il contatore delle riconnessioni e' salito", dopo > prima,
      f"{prima} -> {dopo}")
check("dopo la riconnessione il tool funziona",
      "ECHO: dopo" in mcp.call_tool(echo, {"text": "dopo"}),
      mcp.call_tool(echo, {"text": "dopo"}))
check("i tool sono ancora annunciati", len(mcp.list_tools()) >= 2)
mcp.disconnect("finto")

# ---------------------------------------------------------------------------
# HTTP streamable
# ---------------------------------------------------------------------------

print("\n== HTTP streamable ==")

mcp.add_server({"id": "web", "name": "web", "transport": "http",
                "url": BASE + "/mcp"})
r = mcp.connect("web", timeout=15)
check("connessione http riuscita", r.get("ok"), str(r))
check("il trasporto e' http", r.get("transport") == "http", str(r))
check("due tool via http", r.get("tools") == 2, str(r))

tools = {t["name"]: t for t in mcp.list_tools()
         if t["server_id"] == "web"}
check("il tool http si chiama", "echo" in tools, str(sorted(tools)))
echo_web = tools["echo"]["prefixed"]
check("la chiamata http risponde",
      "HTTP-ECHO: echo" in mcp.call_tool(echo_web, {"text": "x"}),
      mcp.call_tool(echo_web, {"text": "x"}))
check("una risposta in text/event-stream viene letta",
      "HTTP-ECHO: sse" in mcp.call_tool(tools["sse"]["prefixed"], {}),
      mcp.call_tool(tools["sse"]["prefixed"], {}))
check("la risorsa http si legge",
      "testo della risorsa via http" in mcp.read_resource("file:///nota.txt"),
      mcp.read_resource("file:///nota.txt"))
check("il prompt http si riempie",
      "Ciao Ada" in mcp.get_prompt("saluta", {"nome": "Ada"}),
      mcp.get_prompt("saluta", {"nome": "Ada"}))
mcp.disconnect("web")

print("\n== SSE legacy ==")

mcp.add_server({"id": "vecchio", "name": "vecchio", "transport": "sse",
                "url": BASE + "/sse"})
r = mcp.connect("vecchio", timeout=15)
check("connessione SSE riuscita", r.get("ok"), str(r))
tools = {t["name"]: t for t in mcp.list_tools()
         if t["server_id"] == "vecchio"}
check("i tool arrivano anche via SSE", "echo" in tools, str(sorted(tools)))
check("la chiamata SSE risponde",
      "HTTP-ECHO: echo" in mcp.call_tool(tools["echo"]["prefixed"],
                                         {"text": "x"}),
      mcp.call_tool(tools["echo"]["prefixed"], {"text": "x"}))
mcp.disconnect("vecchio")

# ---------------------------------------------------------------------------
# Cose che non devono funzionare per sbaglio
# ---------------------------------------------------------------------------

print("\n== un trasporto sconosciuto non viene indovinato ==")

mcp.add_server({"id": "boh", "name": "boh", "transport": "carrier-pigeon",
                "url": BASE})
r = mcp.connect("boh")
check("la connessione fallisce", not r.get("ok"), str(r))
check("il motivo nomina il trasporto", "carrier-pigeon" in r.get("error", ""),
      str(r.get("error")))
mcp.remove_server("boh")

print("\n== un errore di protocollo non fa riconnettere ==")

mcp.add_server({"id": "web2", "name": "web2", "transport": "http",
                "url": BASE + "/mcp"})
r = mcp.connect("web2")
check("connesso", r.get("ok"), str(r))
conn = mcp._connessione("web2")
try:
    conn.request("metodo/inesistente")
    check("il metodo sconosciuto solleva", False)
except Exception as e:
    check("il metodo sconosciuto solleva", True)
    from orchestra.mcp_trasporti import ErroreMCP, ErroreTrasporto
    check("ed e' un errore di protocollo, non di trasporto",
          isinstance(e, ErroreMCP) and not isinstance(e, ErroreTrasporto),
          type(e).__name__)
check("la connessione e' rimasta la stessa", mcp._connessione("web2") is conn)
mcp.disconnect("web2")

print("\n== nel registro i tool MCP diventano nativi ==")

mcp.add_server({"id": "reg", "name": "reg", "transport": "http",
                "url": BASE + "/mcp"})
mcp.connect("reg")
reg = ToolRegistry()
mcp.registra_tool_nel_registro(reg)
nomi = reg.nomi_attivi()
check("i tool sono nel registro", any(n.startswith("mcp_reg__") for n in nomi),
      str(nomi))
handler = [reg.get(n) for n in nomi if n.startswith("mcp_reg__echo")][0].handler
check("l'handler passa dal client",
      "HTTP-ECHO" in handler(text="y"), handler(text="y"))
mcp.disconnect("reg")

print("\n== il parser SSE ==")

dati = (b'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"a":1}}\n\n'
        b'event: ping\ndata: {}\n\n')
check("trova la risposta con l'id giusto",
      _risposta_da_sse(dati, 7) == {"jsonrpc": "2.0", "id": 7,
                                    "result": {"a": 1}},
      str(_risposta_da_sse(dati, 7)))
check("un id assente non e' una risposta", _risposta_da_sse(dati, 8) is None)

SERVER_GIU.set()
server.shutdown()

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
