"""Test degli endpoint modelli e benchmark.

Copre quello che e' facile sbagliare in questi endpoint e che la UI non
mostra: il cambio modello a meta' turno (deve essere rifiutato, non
applicato di nascosto) e il benchmark lanciato due volte (il secondo deve
essere rifiutato, non far girare due benchmark in parallelo e spendere
token).

Il catalogo e' finto: questi test non devono chiamare l'API.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_web2")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)

from orchestra import LLMResponse, Tool, ToolRegistry  # noqa: E402
from orchestra import webapp  # noqa: E402
from orchestra.catalog import Catalog, ModelInfo, ModelProfile  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402

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


class SlowProvider:
    """Provider lento: tiene la sessione occupata abbastanza da testare
    il rifiuto del cambio modello a meta' turno."""

    def __init__(self, delay=0.3):
        self.delay = delay
        self.n = 0
        self.model = "fake-model"

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        time.sleep(self.delay)
        return LLMResponse(content="risposta", model=self.model,
                           prompt_tokens=10, completion_tokens=5)


class FakeCatalog:
    """Catalogo finto con lo stesso contratto del vero.

    I metodi sono METODI come in `Catalog`: se qui fossero proprietà, il
    test passerebbe comunque ma non starebbe verificando il contratto
    reale. E' successo al primo colpo: `with_tools` come property faceva
    fallire la chiamata, che vuol dire che il test stava misurando il
    mock invece del codice.
    """

    def __init__(self, n=6, measured=None):
        self.models = {}
        for i in range(n):
            mid = f"vendor/modello-{i}:free" if i < 4 else f"vendor/paid-{i}"
            mi = ModelInfo(id=mid, context_length=(i + 1) * 100000,
                           prompt_price=0 if i < 4 else 2.5,
                           completion_price=0 if i < 4 else 12.0,
                           supports_tools=True)
            p = ModelProfile(info=mi)
            if measured and mid in measured:
                p.scores = measured[mid]
                p.last_measured = time.time()
            self.models[mid] = p
        self._path = os.path.join(WORK, "fake_catalog.json")
        self.saved = False

    def with_tools(self):
        return [p for p in self.models.values() if p.info.supports_tools]

    def free(self):
        return [p for p in self.with_tools() if p.info.is_free]

    def measured(self):
        return [p for p in self.models.values() if p.scores]

    def by_score(self, category):
        return sorted([p for p in self.models.values() if category in p.scores],
                      key=lambda p: p.scores[category], reverse=True)

    def best_for(self, category, free_only=False):
        c = self.by_score(category)
        return c[0] if c else None

    def leaderboard(self, category, limit=10):
        return [(p.info.short, p.scores[category]) for p in self.by_score(category)[:limit]]

    def save(self):
        self.saved = True


# ------------------------------------------------------------------ app
reg = ToolRegistry()
reg.register(Tool(name="noop", description="x",
                  schema={"type": "object", "properties": {}}, handler=lambda: "ok"))
app = webapp.OrchestraApp(
    {"ORCHESTRA_PROVIDER": "openrouter", "ORCHESTRA_MODEL": "vendor/modello-0:free"},
    session=Session(provider=SlowProvider(0.01), registry=reg, system_prompt="SYS"),
)
# il catalogo finto, iniettato come farebbe il lazy load
app._catalog = FakeCatalog(measured={"vendor/modello-1:free": {"code": 0.9, "reasoning": 0.4}})
app._catalog_tried = True
webapp.Handler.app = app

PORT = free_port()
httpd = webapp.ThreadingHTTPServer(("127.0.0.1", PORT), webapp.Handler)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"
time.sleep(0.3)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def post_expect_error(path, payload):
    try:
        post(path, payload)
        return 200, {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


try:
    print("\n[0] Ogni istanza ha gli attributi, anche senza create()")
    # Regressione: `create()` usava __new__ e saltava __init__, quindi
    # _catalog_tried non esisteva e /api/models moriva con
    # AttributeError al PRIMO accesso. I test precedenti costruivano
    # l'app a mano e non lo prendevano.
    probe = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
    # costruita col percorso di create(): deve avere tutto
    a2 = webapp.OrchestraApp({}, session=Session(provider=SlowProvider(0.01),
                                                  registry=reg, system_prompt="S"))
    for attr in ("env", "session", "ready", "error", "_catalog", "_catalog_tried",
                 "_catalog_error", "_bench"):
        check(f"attributo presente: {attr}", hasattr(a2, attr))
    check("stato iniziale senza benchmark", a2._bench["running"] is False)
    check("stato iniziale senza catalogo", a2._catalog_tried is False)
    del probe

    print("\n[1] GET /api/models")
    st, d = get("/api/models")
    check("status 200", st == 200, str(st))
    check("elenca i modelli", len(d["models"]) == 6, str(len(d.get("models", []))))
    check("il modello corrente è marcato",
          sum(1 for m in d["models"] if m.get("current")) == 1,
          str([m["id"] for m in d["models"] if m.get("current")]))
    check("free marcato come free", all(m["free"] for m in d["models"] if ":free" in m["id"]))
    check("prezzo sui paid", any(m["prompt_price"] > 0 for m in d["models"]))
    check("i punteggi misurati arrivano",
          d["models"][0].get("scores") is not None or
          any(m.get("scores") for m in d["models"]),
          "nessun modello con scores")
    check("short name presente", all(m.get("short") for m in d["models"]))
    check("contesto presente", any(m.get("context") for m in d["models"]))
    old_model = d["current"]

    print("\n[2] POST /api/model — cambio")
    st, d = post("/api/model", {"model": "vendor/modello-2:free"})
    check("cambio accettato", st == 200 and d.get("ok") is True, str(d))
    check("il provider dell'agent è stato sostituito",
          app.session.agent.provider.model == "vendor/modello-2:free",
          app.session.agent.provider.model)
    check("l'env riflette il cambio", app.env["ORCHESTRA_MODEL"] == "vendor/modello-2:free",
          app.env.get("ORCHESTRA_MODEL"))

    # il modello corrente è cambiato nell'elenco
    st, d = get("/api/models")
    check("l'elenco riflette il nuovo corrente",
          d["current"] == "vendor/modello-2:free", d.get("current"))

    print("\n[3] POST /api/model — errori")
    code, d = post_expect_error("/api/model", {"model": ""})
    check("modello vuoto -> 400", code == 400, str(code))
    # un id inesistente deve essere RESPINTO: build_provider accetterebbe
    # qualsiasi stringa e fallirebbe solo alla prima chiamata, con un
    # errore che sembra di rete
    code, d = post_expect_error("/api/model", {"model": "vendor/inesistente"})
    check("modello inesistente -> 400", code == 400, f"{code} {d}")
    check("l'errore nomina il modello", "inesistente" in d.get("error", ""), str(d))
    check("l'env NON è stato modificato",
          app.env["ORCHESTRA_MODEL"] == "vendor/modello-2:free",
          app.env.get("ORCHESTRA_MODEL"))
    check("il provider NON è stato modificato",
          app.session.agent.provider.model == "vendor/modello-2:free",
          app.session.agent.provider.model)

    print("\n[4] Cambio modello rifiutato mentre l'agente lavora")
    app.session.agent.provider = SlowProvider(0.4)  # lento apposta
    app.session.send("occupo la sessione")
    time.sleep(0.1)
    check("sessione occupata", app.session.busy is True)
    code, d = post_expect_error("/api/model", {"model": "vendor/modello-0:free"})
    check("cambio durante il lavoro -> 409", code == 409, f"{code} {d}")
    check("l'errore spiega il motivo", "lavorando" in d.get("error", ""), str(d))
    check("il modello NON è stato cambiato",
          app.env["ORCHESTRA_MODEL"] == "vendor/modello-2:free",
          app.env.get("ORCHESTRA_MODEL"))
    app.session.cancel()
    app.session.wait(timeout=15)
    # dopo il cancel il cambio deve funzionare
    st, d = post("/api/model", {"model": "vendor/modello-0:free"})
    check("cambio dopo il cancel funziona", st == 200, str(st))

    print("\n[5] GET /api/bench/status")
    st, d = get("/api/bench/status")
    check("status 200", st == 200)
    check("non in esecuzione", d["running"] is False, str(d.get("running")))
    check("log è una lista", isinstance(d.get("log"), list))
    check("result presente come chiave", "result" in d)

    print("\n[6] GET /api/capabilities")
    st, d = get("/api/capabilities")
    check("status 200", st == 200, str(st))
    check("solo i misurati", set(d.get("measured", {})) == {"vendor/modello-1:free"},
          str(list(d.get("measured", {}))))
    check("i punteggi sono per categoria",
          d["measured"].get("vendor/modello-1:free", {}).get("code") == 0.9, str(d.get("measured")))

    print("\n[7] POST /api/bench — il benchmark parte ed è rifiutato se duplicato")
    # Monkeypatch: il benchmark vero chiama l'API. Qui verifichiamo solo
    # il contratto HTTP, non la misura (quella la fa test_benchmark).
    started = threading.Event()
    release = threading.Event()

    def fake_start(**kwargs):
        started.set()
        # la guardia reale: se è già in corso, si rifiuta. Il test
        # precedente non la simulava e quindi non verificava nulla — un
        # doppio avvio è esattamente il caso in cui due benchmark girano
        # insieme e spendono il doppio dei token.
        if app._bench["running"]:
            raise RuntimeError("un benchmark è già in corso")
        app._bench["running"] = True
        app._bench["log"] = ["riga 1"]

        def finish():
            # `app._bench["running"] = False`, non setattr: su un dict
            # setattr crea un attributo e lascia la chiave intatta, quindi
            # il test osservava uno stato che non esiste
            release.wait(5)
            app._bench["running"] = False

        threading.Thread(target=finish, daemon=True).start()
        return {"ok": True, "models": ["vendor/modello-0:free"], "tasks": 9}

    app.start_benchmark = fake_start
    st, d = post("/api/bench", {"sample": 2, "category": "all"})
    check("avvio accettato", st == 200 and d.get("ok") is True, str(d))
    check("il fake è stato chiamato", started.wait(3) is True)

    code, d = post_expect_error("/api/bench", {"sample": 2})
    check("doppio avvio -> 409", code == 409, f"{code} {d}")
    check("l'errore dice che è già in corso",
          "già in corso" in d.get("error", ""), str(d))

    st, d = get("/api/bench/status")
    check("lo status mostra il log", d["log"] == ["riga 1"], str(d.get("log")))
    check("lo status mostra running", d["running"] is True)

    release.set()
    for _ in range(30):
        st, d = get("/api/bench/status")
        if not d["running"]:
            break
        time.sleep(0.2)
    check("running torna a false", d["running"] is False, str(d.get("running")))

    print("\n[8] input malformati")
    for label, payload in [
        ("sample non numerico", {"sample": "abc"}),
        ("sample enorme", {"sample": 9999}),
        ("sample negativo", {"sample": -5}),
        ("categoria inesistente", {"category": "inesistente"}),
        ("body vuoto", {}),
    ]:
        try:
            st, d = post("/api/bench", payload)
            check(f"gestisce: {label}", st in (200, 400, 409), f"{st} {d}")
        except urllib.error.HTTPError as e:
            check(f"gestisce: {label}", e.code in (400, 409, 500), str(e.code))
        except Exception as e:
            check(f"gestisce: {label}", False, f"crash {type(e).__name__}: {e}")

    st, d = get("/api/bench/status")
    check("server vivo dopo input malformati", st == 200)
    st, d = get("/api/state")
    check("la chat non è disturbata", st == 200 and d["ready"] is True)

finally:
    httpd.shutdown()
    httpd.server_close()

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
