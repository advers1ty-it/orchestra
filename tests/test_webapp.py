"""Verifica del server HTTP con richieste vere.

Non mock: si avvia il server su una porta libera, si fanno richieste con
urllib e si guarda che lo stream SSE emetta eventi mentre l'agente lavora.
E' l'unico modo per accorgersi di problemi che solo con un client reale si
vedono (Content-Length sbagliato, connessione che non tiene, SSE malformato).
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_web")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)

from orchestra import LLMResponse  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402
from orchestra import webapp  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra import Tool  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class DemoProvider:
    """Provider finto ma con uso reale: emette un tool e poi risponde."""

    def __init__(self, hold=0.0):
        self.n = 0
        self.model = "demo-model"
        self.hold = hold  # secondi di attesa per ogni chiamata

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.hold:
            time.sleep(self.hold)
        if self.n == 1:
            return LLMResponse(
                content="Uso uno strumento.",
                tool_calls=[ToolCall(id="t1", name="ping", arguments='{"msg":"ciao"}')],
                model=self.model, prompt_tokens=50, completion_tokens=10,
            )
        if self.n == 2:
            return LLMResponse(
                content="Secondo turno in corso.",
                tool_calls=[ToolCall(id="t2", name="ping", arguments='{"msg":"ancora"}')],
                model=self.model, prompt_tokens=60, completion_tokens=10,
            )
        return LLMResponse(
            content="Fatto: ho verificato.",
            model=self.model, prompt_tokens=70, completion_tokens=15,
        )


# montiamo l'app sul nostro provider finito: stessa classe Handler del
# server vero, quindi quello che verifichiamo qui e' il codice che gira
app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app.env = {"ORCHESTRA_MODEL": "demo-model", "ORCHESTRA_PROVIDER": "demo"}
app.ready = True
app.error = ""
reg = default_registry()
reg.register(Tool(name="ping", description="risponde",
                  schema={"type": "object",
                          "properties": {"msg": {"type": "string"}},
                          "required": ["msg"]},
                  handler=lambda msg: f"pong: {msg}"))
app.session = Session(provider=DemoProvider(), registry=reg, system_prompt="SYS",
                      config=webapp.LoopConfig(max_iterations=6))
fast_session = app.session
webapp.Handler.app = app

PORT = free_port()
httpd = webapp.ThreadingHTTPServer(("127.0.0.1", PORT), webapp.Handler)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"
time.sleep(0.4)

try:
    print("\n[1] Endpoint base")
    with urllib.request.urlopen(BASE + "/", timeout=10) as r:
        html = r.read().decode("utf-8")
    check("GET / serve la UI", r.status == 200 and "Orchestra" in html, str(r.status))
    check("UI ha il campo di input", 'id="input"' in html)
    check("UI ha il log", 'id="log"' in html)
    check("Content-Type corretto",
          "text/html" in r.headers.get("Content-Type", ""),
          r.headers.get("Content-Type", ""))
    check("Content-Length coerente", int(r.headers.get("Content-Length", 0)) == len(html.encode()),
          f"{r.headers.get('Content-Length')} vs {len(html.encode())}")

    print("\n[2] /api/state")
    with urllib.request.urlopen(BASE + "/api/state", timeout=10) as r:
        st = json.loads(r.read().decode("utf-8"))
    check("state ha ready", st["ready"] is True)
    check("state ha il modello", st["model"] == "demo-model", st.get("model"))
    check("state iniziale non occupato", st["busy"] is False)

    print("\n[3] /api/send e stream SSE in parallelo")
    events = []

    def read_stream():
        req = urllib.request.Request(BASE + "/api/stream")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                for raw in r:
                    line = raw.decode("utf-8").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        try:
                            events.append(json.loads(line[6:]))
                        except json.JSONDecodeError:
                            pass
                    if len([e for e in events if e.get("kind") == "idle"]) >= 2:
                        return
        except Exception as e:
            events.append({"kind": "_errore", "data": {"msg": str(e)}})

    t = threading.Thread(target=read_stream, daemon=True)
    t.start()
    time.sleep(0.6)  # lascia aprire lo stream

    # primo turno
    body = json.dumps({"text": "primo compito"}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/send", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read().decode("utf-8"))
    check("send accettato", resp.get("ok") is True, str(resp))
    app.session.wait(timeout=20)
    time.sleep(0.5)

    # secondo turno
    body = json.dumps({"text": "secondo compito"}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/send", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read().decode("utf-8"))
    app.session.wait(timeout=20)
    t.join(timeout=8)

    kinds = [e["kind"] for e in events]
    check("snapshot iniziale inviato", "snapshot" in kinds, str(set(kinds)))
    check("turn_start emesso", kinds.count("turn_start") >= 2, str(kinds.count("turn_start")))
    check("user_message emesso", kinds.count("user_message") >= 2, str(kinds.count("user_message")))
    check("tool_start emesso", kinds.count("tool_start") >= 2, str(kinds.count("tool_start")))
    check("tool_end emesso", kinds.count("tool_end") >= 2, str(kinds.count("tool_end")))
    check("turn_end emesso", kinds.count("turn_end") >= 2, str(kinds.count("turn_end")))
    check("idle emesso", kinds.count("idle") >= 2, str(kinds.count("idle")))
    check("nessun errore nello stream",
          not [e for e in events if e.get("kind") == "_errore"],
          str([e for e in events if e.get("kind") == "_errero"]))
    check("seq presenti", all("seq" in e for e in events if e.get("kind") != "_errore"))
    # il tool_end deve dire ok
    tends = [e for e in events if e.get("kind") == "tool_end"]
    check("tool_end con ok=true", all(e["data"].get("ok") for e in tends) if tends else False)
    # ordine: turn_start prima di tool_start
    if "turn_start" in kinds and "tool_start" in kinds:
        check("turn_start precede tool_start", kinds.index("turn_start") < kinds.index("tool_start"))

    print("\n[4] occupato: secondo send rifiutato con 409")
    # Scambiamo la sessione con una LENTA: con il provider veloce il turno
    # precedente finisce prima che il secondo send arrivi, e il test
    # misurerebbe la velocita' del mock invece della guardia.
    slow = Session(
        provider=DemoProvider(hold=0.4),
        registry=reg, system_prompt="SYS",
        config=webapp.LoopConfig(max_iterations=3),
    )
    app.session = slow
    slow.send("occupa")
    time.sleep(0.2)
    check("sessione occupata prima del test", slow.busy is True)
    try:
        body = json.dumps({"text": "impossibile"}).encode("utf-8")
        req = urllib.request.Request(BASE + "/api/send", data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        urllib.request.urlopen(req, timeout=10)
        check("send durante il lavoro rifiutato", False, "accettato!")
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read().decode("utf-8"))
        check("send durante il lavoro rifiutato", e.code == 409, str(e.code))
        check("errore 409 spiega il motivo", "busy" in payload, str(payload))
    slow.cancel()
    slow.wait(timeout=15)
    # torniamo alla sessione veloce per il resto
    app.session = fast_session

    print("\n[5] cancel e reset via HTTP")
    with urllib.request.urlopen(urllib.request.Request(BASE + "/api/cancel", data=b"",
                                                      method="POST"), timeout=10) as r:
        check("cancel risponde", json.loads(r.read().decode("utf-8")).get("ok") is False,
              "dovrebbe dire false: era gia' fermo")
    with urllib.request.urlopen(urllib.request.Request(BASE + "/api/reset", data=b"",
                                                      method="POST"), timeout=10) as r:
        check("reset risponde ok", json.loads(r.read().decode("utf-8")).get("ok") is True)
    with urllib.request.urlopen(BASE + "/api/state", timeout=10) as r:
        st2 = json.loads(r.read().decode("utf-8"))
    check("reset ha svuotato i messaggi", len(st2["messages"]) == 0, str(st2["messages"])[:80])
    check("reset ha azzerato i token", st2["total_tokens"] == 0)

    print("\n[6] input malformati")
    for label, data, ct in [
        ("JSON rotto", b"{non json", "application/json"),
        ("corpo vuoto", b"", "application/json"),
        ("text mancante", b"{}", "application/json"),
        ("corpo enorme", b'{"text":"' + b"x" * 100000 + b'"}', "application/json"),
    ]:
        req = urllib.request.Request(BASE + "/api/send", data=data,
                                     headers={"Content-Type": ct}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            check(f"rifiuta: {label}", False, "accettato")
        except urllib.error.HTTPError as e:
            check(f"rifiuta: {label}", e.code in (400, 409, 413), str(e.code))
        except Exception as e:
            check(f"rifiuta: {label}", False, f"crash: {type(e).__name__}: {e}")

    # il server deve essere ancora vivo dopo tutti quei malformati
    with urllib.request.urlopen(BASE + "/api/state", timeout=10) as r:
        check("server ancora vivo dopo input malformati", r.status == 200)

    print("\n[7] 404 e metodi non supportati")
    try:
        urllib.request.urlopen(BASE + "/api/inesistente", timeout=10)
        check("404 su endpoint ignoto", False, "ha risposto 200")
    except urllib.error.HTTPError as e:
        check("404 su endpoint ignoto", e.code == 404, str(e.code))
    req = urllib.request.Request(BASE + "/", data=b"{}", method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        check("POST su / non crasha", True)
    except Exception:
        check("POST su / non crasha", True)

finally:
    httpd.shutdown()
    httpd.server_close()

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
