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
from orchestra import skills as skills_mod  # noqa: E402
from orchestra.mcp_trasporti import _risolvi_comando, _risposta_da_sse  # noqa: E402
from orchestra.tools import ToolRegistry  # noqa: E402

FAKE = os.path.join(RADICE, "tests", "_mcp_fake.py")
PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("\n== il comando stdio viene risolto nel PATH ==")
finto_nome = "orch-mcp-finto"
if os.name == "nt":
    finto_percorso = os.path.join(TMP, finto_nome + ".cmd")
    with open(finto_percorso, "w", encoding="utf-8", newline="\n") as f:
        f.write("@echo off\nexit /b 0\n")
else:
    finto_percorso = os.path.join(TMP, finto_nome)
    with open(finto_percorso, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(finto_percorso, 0o755)
vecchio_path = os.environ.get("PATH", "")
os.environ["PATH"] = TMP + os.pathsep + vecchio_path
try:
    risolto = _risolvi_comando(finto_nome)
finally:
    os.environ["PATH"] = vecchio_path
check("un comando nel PATH viene risolto al percorso vero",
      os.path.normcase(os.path.abspath(risolto))
      == os.path.normcase(os.path.abspath(finto_percorso)), risolto)
check("un comando inesistente resta com'e'",
      _risolvi_comando("orch-mcp-non-esiste") == "orch-mcp-non-esiste")


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
check("almeno due tool elencati", r.get("tools") >= 2, str(r))
check("una risorsa elencata", r.get("resources") == 1, str(r))
check("un prompt elencato", r.get("prompts") == 1, str(r))
check("il protocollo viene dal server", r.get("protocol") == "2024-11-05",
      str(r.get("protocol")))

tools = {t["name"]: t for t in mcp.list_tools()}
check("il tool arriva prefissato", "echo" in tools, str(sorted(tools)))
echo = tools["echo"]["prefixed"]
check("la chiamata risponde", "ECHO: ciao" in mcp.call_tool(echo, {"text": "ciao"}),
      mcp.call_tool(echo, {"text": "ciao"}))
# Il server stdio non deve ricevere l'ambiente del padre: un server MCP
# aggiunto per sbaglio non deve poter leggere le chiavi API.
os.environ["CANARY_MCP"] = "segreto-del-padre"
letto = mcp.call_tool(tools["env"]["prefixed"], {"nome": "CANARY_MCP"})
check("il server stdio non vede i segreti del padre",
      "segreto-del-padre" not in str(letto), repr(letto))
del os.environ["CANARY_MCP"]
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

print("\n== il tool mcp non aggiunge un server stdio senza conferma ==")

from orchestra.tools import _guard  # noqa: E402
from orchestra.tools.mcp import tool_mcp  # noqa: E402

t = tool_mcp()

print("\n== preset pronti: solo il dato dell'utente ==")
from orchestra import mcp_preset  # noqa: E402

elementi = {p["id"]: p for p in mcp_preset.catalogo()}
attesi = {
    "github", "gitlab", "supabase", "neon", "notion", "linear", "sentry",
    "stripe", "datadog", "firecrawl", "exa", "context7", "huggingface",
    "cloudflare", "airtable", "resend", "semgrep", "deepwiki", "posthog",
    "pagerduty", "twilio", "elasticsearch", "atlassian", "clickup",
    "netlify", "miro", "paypal", "playwright", "filesystem", "unreal",
    "godot", "blender", "unity", "freecad", "gimp", "krita",
    "inkscape", "jetbrains", "obsidian", "postgres", "sqlite",
    "mongodb", "redis", "grafana", "terraform", "memory",
    "sequential-thinking", "fetch", "git", "time", "chrome-devtools",
    "desktop-commander", "remoto",
}
check("il catalogo copre i servizi e i programmi attesi",
      attesi.issubset(elementi), str(sorted(attesi - set(elementi))))
check("ogni preset ha una categoria valida",
      all(p.get("categoria") in ("servizio", "programma", "dati", "utility")
          for p in elementi.values()),
      str({p: x.get("categoria") for p, x in elementi.items()}))
locali = ("playwright", "filesystem", "unreal", "godot", "blender",
          "unity", "freecad", "gimp", "krita", "inkscape", "jetbrains",
          "obsidian", "postgres", "sqlite", "mongodb", "redis", "grafana",
          "terraform", "memory", "sequential-thinking", "fetch", "git",
          "time", "chrome-devtools", "desktop-commander")
check("i programmi e gli strumenti locali sono marcati come locali",
      all(elementi[p].get("locale") for p in locali),
      str({p: elementi[p].get("locale") for p in locali}))
potenti = ("filesystem", "git", "desktop-commander", "postgres", "sqlite",
           "mongodb", "redis", "grafana", "terraform")
check("i preset locali potenti chiedono una conferma esplicita",
      all(elementi[p].get("richiede_conferma") for p in potenti),
      str({p: elementi[p].get("richiede_conferma") for p in potenti}))
check("i preset non potenti non chiedono conferma",
      not elementi["github"].get("richiede_conferma")
      and not elementi["memory"].get("richiede_conferma"),
      str({p: elementi[p].get("richiede_conferma") for p in ("github", "memory")}))
check("il client riconosce i preset che richiedono conferma",
      mcp.config_richiede_conferma({"preset": "git"})
      and not mcp.config_richiede_conferma({"preset": "memory"}))
check("una vecchia config senza preset viene riconosciuta da id/nome",
      mcp.config_richiede_conferma({"id": "git"})
      and mcp.config_richiede_conferma({"name": "Git"})
      and not mcp.config_richiede_conferma({"id": "normal-server"}))
_vecchio_load = mcp._load_config
mcp._load_config = lambda: [{
    "id": "git-solo", "name": "Git",
    "transport": "stdio", "command": "comando-che-non-deve-partire",
}]
try:
    _res = mcp.connect_all()
finally:
    mcp._load_config = _vecchio_load
check("connect_all non avvia da solo un preset potente",
      len(_res) == 1 and _res[0].get("skipped") is True
      and _res[0].get("id") == "git-solo", str(_res))
rotti = []
for pid, p in elementi.items():
    valori = {c["nome"]: "valore-di-prova" for c in p.get("campi", [])}
    try:
        cfg = mcp_preset.configura(pid, valori)
        if not cfg.get("transport"):
            raise ValueError("trasporto assente")
    except Exception as e:  # noqa: BLE001 - il test raccoglie tutti i preset rotti
        rotti.append(f"{pid}: {type(e).__name__}: {e}")
check("tutti i preset generano una config completa", not rotti, str(rotti))
check("Notion passa da OAuth, non da un token da incollare",
      elementi["notion"].get("oauth") is True
      and elementi["notion"].get("campi") == [], str(elementi["notion"]))
check("il catalogo non espone la config esecutiva",
      "headers" not in elementi["github"]
      and "url" not in elementi["github"], str(elementi["github"]))

cfg_gh = mcp_preset.configura("github", {"token": "segreto-di-prova"})
check("GitHub diventa una config HTTP completa",
      cfg_gh.get("transport") == "http"
      and cfg_gh.get("url", "").startswith("https://api.githubcopilot.com"),
      str(cfg_gh))
check("il token finisce nell'header giusto",
      (cfg_gh.get("headers") or {}).get("Authorization")
      == "Bearer segreto-di-prova", str(cfg_gh.get("headers")))
check("il preset resta scritto nella config",
      cfg_gh.get("preset") == "github", str(cfg_gh))

errore = ""
try:
    mcp_preset.configura("github", {})
except ValueError as e:
    errore = str(e)
check("senza token il preset dice quale dato manca",
      "token" in errore and "GitHub" in errore, errore)

cfg_fs = mcp_preset.configura("filesystem", {"cartella": "D:/progetti/app"})
check("il filesystem vede solo la cartella passata",
      cfg_fs.get("command") == "npx"
      and (cfg_fs.get("args") or [])[-1] == "D:/progetti/app",
      str(cfg_fs.get("args")))
cfg_rem = mcp_preset.configura("remoto", {"url": "https://mcp.esempio.test/mcp"})
check("il ponte OAuth generico conserva l'URL",
      "https://mcp.esempio.test/mcp" in (cfg_rem.get("args") or []),
      str(cfg_rem.get("args")))
cfg_ue = mcp_preset.configura("unreal")
check("Unreal punta al server HTTP locale dell'editor",
      cfg_ue.get("transport") == "http"
      and cfg_ue.get("url") == "http://127.0.0.1:8000/mcp"
      and not cfg_ue.get("headers"), str(cfg_ue))
cfg_godot = mcp_preset.configura("godot", {"progetto": "D:/giochi/app"})
check("Godot usa il progetto e il bridge npx",
      cfg_godot.get("command") == "npx"
      and "@npgamedev/godot-mcp-server" in (cfg_godot.get("args") or [])
      and (cfg_godot.get("env") or {}).get("GODOT_MCP_PROJECT_PATH")
      == "D:/giochi/app", str(cfg_godot))
cfg_blender = mcp_preset.configura("blender")
check("Blender usa uvx, non un comando indovinato",
      cfg_blender.get("command") == "uvx"
      and (cfg_blender.get("args") or []) == ["mcp-for-blender"],
      str(cfg_blender))

cfg_gl = mcp_preset.configura("gitlab", {"token": "gl-token"})
check("GitLab usa il token nell'header Bearer",
      cfg_gl.get("url") == "https://gitlab.com/api/v4/mcp"
      and (cfg_gl.get("headers") or {}).get("Authorization")
      == "Bearer gl-token", str(cfg_gl.get("headers")))
cfg_pd = mcp_preset.configura("pagerduty", {"token": "pd-token"})
check("PagerDuty usa lo schema Token token=",
      (cfg_pd.get("headers") or {}).get("Authorization")
      == "Token token=pd-token", str(cfg_pd.get("headers")))
cfg_es = mcp_preset.configura("elasticsearch",
                             {"kibana": "https://k.example",
                              "token": "es-token"})
check("Elasticsearch compila URL e header ApiKey",
      cfg_es.get("url") == "https://k.example/api/agent_builder/mcp"
      and (cfg_es.get("headers") or {}).get("Authorization")
      == "ApiKey es-token", str(cfg_es))
cfg_obs = mcp_preset.configura("obsidian", {"token": "obs-token"})
check("Obsidian mette la API key nell'ambiente",
      (cfg_obs.get("env") or {}).get("OBSIDIAN_API_KEY") == "obs-token",
      str(cfg_obs.get("env")))
cfg_pg = mcp_preset.configura(
    "postgres", {"url": "postgresql://u:p@localhost/db"})
check("PostgreSQL usa la connessione in ambiente, non in chat",
      cfg_pg.get("command") == "npx"
      and (cfg_pg.get("env") or {}).get("POSTGRES_MCP_CONNECTION_STRING")
      == "postgresql://u:p@localhost/db", str(cfg_pg.get("env")))
cfg_mdb = mcp_preset.configura("mongodb", {"url": "mongodb://localhost/db"})
check("MongoDB parte in sola lettura",
      "--readOnly" in (cfg_mdb.get("args") or [])
      and (cfg_mdb.get("env") or {}).get("MDB_MCP_CONNECTION_STRING")
      == "mongodb://localhost/db", str(cfg_mdb))
cfg_sql = mcp_preset.configura("sqlite", {"dsn": "sqlite:///D:/x.db"})
check("SQLite passa il DSN a DBHub",
      "@bytebase/dbhub@latest" in (cfg_sql.get("args") or [])
      and "sqlite:///D:/x.db" in (cfg_sql.get("args") or []),
      str(cfg_sql.get("args")))
cfg_graf = mcp_preset.configura(
    "grafana", {"url": "http://localhost:3000", "token": "g-token"})
check("Grafana usa URL e service token separati",
      (cfg_graf.get("env") or {}).get("GRAFANA_URL")
      == "http://localhost:3000"
      and (cfg_graf.get("env") or {}).get("GRAFANA_SERVICE_ACCOUNT_TOKEN")
      == "g-token", str(cfg_graf.get("env")))
cfg_atl = mcp_preset.configura("atlassian")
check("Atlassian passa dal ponte OAuth",
      cfg_atl.get("command") == "npx"
      and "mcp-remote" in (cfg_atl.get("args") or [])
      and "https://mcp.atlassian.com/v2/mcp" in (cfg_atl.get("args") or []),
      str(cfg_atl.get("args")))
cfg_unity = mcp_preset.configura("unity")
check("Unity usa il bridge MCP for Unity",
      cfg_unity.get("command") == "uvx"
      and "mcp-for-unity" in (cfg_unity.get("args") or []),
      str(cfg_unity.get("args")))
cfg_jb = mcp_preset.configura("jetbrains")
check("JetBrains punta al server HTTP dell'IDE",
      cfg_jb.get("transport") == "http"
      and cfg_jb.get("url", "").endswith(":64342/stream"), str(cfg_jb))
cfg_mem = mcp_preset.configura("memory")
check("Memory usa il server reference",
      cfg_mem.get("command") == "npx"
      and "@modelcontextprotocol/server-memory" in (cfg_mem.get("args") or []),
      str(cfg_mem.get("args")))
cfg_tf = mcp_preset.configura("terraform")
check("Terraform usa l'immagine ufficiale, non un comando inventato",
      cfg_tf.get("command") == "docker"
      and "hashicorp/terraform-mcp-server:1.4.1" in (cfg_tf.get("args") or []),
      str(cfg_tf.get("args")))

out = t.handler(azione="preset")
check("il tool espone il catalogo", "github" in out and "token" in out, out[:300])
out = t.handler(azione="preset", preset="github")
check("il tool spiega un preset solo", "personal access token" in out, out[:300])
out = t.handler(azione="aggiungi", preset="github",
                valori={"token": "segreto-preset-test"})
check("il preset aggiunge senza chiedere comando o URL",
      "aggiunto" in out.lower(), out)
check("il token non torna nel contesto",
      "segreto-preset-test" not in out, out)
voce_gh = next((s for s in mcp.list_servers() if s["id"] == "github"), None)
check("la config preset e' stata scritta",
      voce_gh is not None and voce_gh.get("preset") == "github",
      str(voce_gh))
check("la lista non rimanda la config esecutiva dei preset",
      voce_gh is not None and not voce_gh.get("args")
      and not voce_gh.get("url"), str(voce_gh))
mcp.remove_server("github")

# Il flag non e' salvato nella config: si ricava dal catalogo attuale.
# Per questo vale anche per i server aggiunti prima che esistesse la
# conferma, purche' abbiano il preset nella configurazione.
cfg_git_test = mcp_preset.configura("git", {"cartella": "D:/progetti/prova"})
mcp.add_server(cfg_git_test)
voce_git_test = next((s for s in mcp.list_servers() if s["id"] == "git"), None)
check("un preset potente gia' aggiunto risulta da confermare",
      voce_git_test is not None
      and voce_git_test.get("richiede_conferma") is True,
      str(voce_git_test))
mcp.remove_server("git")

# Anche una vecchia config senza `preset`, riconosciuta dal nome, non
# deve esporre gli argomenti (che possono contenere un DSN o un token).
mcp.add_server({"id": "git-legacy", "name": "Git", "transport": "stdio",
                "command": "comando-finto", "args": ["--token", "segreto"]})
voce_legacy = next((s for s in mcp.list_servers()
                    if s["id"] == "git-legacy"), None)
check("una vecchia config potente non espone gli args nella lista",
      voce_legacy is not None
      and voce_legacy.get("richiede_conferma") is True
      and not voce_legacy.get("args")
      and voce_legacy.get("command") is None, str(voce_legacy))
mcp.remove_server("git-legacy")

print("\n== la skill mcp usa il catalogo ==")
radice_skill = os.path.join(RADICE, "skills")
indice_skill = skills_mod.Indice(radice_skill)
skill_mcp = indice_skill.get("mcp")
check("la skill mcp e' nell'indice", skill_mcp is not None)
servizi = (skill_mcp.descrizione.lower() if skill_mcp else "")
check("la descrizione nomina i servizi coperti",
      all(s in servizi for s in ("github", "gitlab", "supabase", "neon",
                                 "notion", "linear", "sentry", "stripe",
                                 "cloudflare", "datadog", "posthog",
                                 "playwright", "filesystem", "unreal",
                                 "unity", "godot", "blender", "freecad",
                                 "gimp", "postgres", "mongodb", "redis",
                                 "grafana")), servizi)
check("la skill insegna a partire dal catalogo",
      "azione=\"preset\"" in (skill_mcp.corpo if skill_mcp else ""),
      (skill_mcp.corpo if skill_mcp else "")[:200])
prompt_skill = indice_skill.prompt("collega notion via mcp")
check("la skill entra nel prompt quando si parla di MCP",
      "mcp:" in prompt_skill, prompt_skill[:300])

_guard.set_permission_gate(None)
out = t.handler(azione="aggiungi", nome="gate-test", transport="stdio",
                command=sys.executable, args=[FAKE])
check("senza gate il server stdio viene rifiutato", "NON AGGIUNTO" in out, out)


class GateFinto:
    def chiedi_all_utente(self, *a, **k):
        return True


_guard.set_permission_gate(GateFinto())
out = t.handler(azione="aggiungi", nome="gate-test", transport="stdio",
                command=sys.executable, args=[FAKE])
check("con il consenso il server viene aggiunto", "aggiunto" in out.lower(), out)
mcp.remove_server("gate-test")
_guard.set_permission_gate(None)

print("\n== il tool mcp non connette un preset potente senza conferma ==")

cfg_git_tool = mcp_preset.configura("git", {"cartella": "D:/progetti/prova"})
cfg_git_tool["id"] = "git-tool-test"
mcp.add_server(cfg_git_tool)
_guard.set_permission_gate(None)
out = t.handler(azione="connetti", id="git-tool-test")
check("senza gate il preset potente non viene connesso",
      "NON CONNESSO" in out and "conferma" in out.lower(), out)


class GateNo:
    def __init__(self):
        self.chiamate = []

    def chiedi_all_utente(self, *a, **k):
        self.chiamate.append(a)
        return False


gate_no = GateNo()
_guard.set_permission_gate(gate_no)
out = t.handler(azione="connetti", id="git-tool-test")
check("il rifiuto del gate blocca la connessione",
      "NON CONNESSO" in out and len(gate_no.chiamate) == 1, out)

import orchestra.tools.mcp as tool_mcp_mod  # noqa: E402

vecchio_connect_tool = tool_mcp_mod.connect
chiamate_connect = []
tool_mcp_mod.connect = lambda sid, timeout=20.0: (
    chiamate_connect.append(sid) or {"ok": True, "tools": 0})
_guard.set_permission_gate(GateFinto())
out = t.handler(azione="connetti", id="git-tool-test")
check("con il consenso esplicito il tool connette il preset",
      chiamate_connect == ["git-tool-test"]
      and json.loads(out).get("ok") is True, out)
tool_mcp_mod.connect = vecchio_connect_tool
mcp.remove_server("git-tool-test")

# Un server non-preset non deve ricevere un prompt in piu'.
mcp.add_server({"id": "normal-tool", "name": "normal-tool",
                "transport": "stdio", "command": sys.executable,
                "args": [FAKE]})
gate_no = GateNo()
_guard.set_permission_gate(gate_no)
chiamate_connect = []
tool_mcp_mod.connect = lambda sid, timeout=20.0: (
    chiamate_connect.append(sid) or {"ok": True, "tools": 0})
out = t.handler(azione="connetti", id="normal-tool")
check("un server normale non chiede la conferma dei preset",
      not gate_no.chiamate and chiamate_connect == ["normal-tool"]
      and json.loads(out).get("ok") is True, out)
tool_mcp_mod.connect = vecchio_connect_tool
mcp.remove_server("normal-tool")
_guard.set_permission_gate(None)

SERVER_GIU.set()
server.shutdown()

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
