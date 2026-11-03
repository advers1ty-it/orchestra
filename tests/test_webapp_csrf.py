"""Il server locale non deve ubbidire a una pagina di un altro sito.

La modalita' remota ha un token, ma il server acceso in locale no: una
pagina qualsiasi aperta nel browser puo' fare una POST verso
127.0.0.1:8737 e comandare l'agente. Il browser manda `Origin`, quindi il
server confronta `Origin` con `Host` e rifiuta il resto.

Qui si verificano tre cose, con un server HTTP vero: la POST cross-site
viene rifiutata, quella stessa-origine passa, e il login ha un limite di
tentativi (senza, il token si prova a forza bruta).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "_probe_csrf")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import LLMResponse, webapp  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


class Provider:
    name = "csrf-demo"
    model = "m"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="ok", model="m")


app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app.env = {"ORCHESTRA_MODEL": "m", "ORCHESTRA_PROVIDER": "csrf-demo"}
app.ready = True
app.error = ""
app.remoto_attivo = False
app.token_remoto = "token-di-prova-123"
app.session = Session(provider=Provider(), registry=default_registry(),
                      system_prompt="SYS",
                      config=webapp.LoopConfig(max_iterations=2))
webapp.Handler.app = app

s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
httpd = webapp.ThreadingHTTPServer(("127.0.0.1", PORT), webapp.Handler)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


# Il thread del server parte in parallelo: senza questa attesa la prima
# richiesta puo' cadere prima che la porta accetti, e il test fallisce a
# intermittenza accusando il codice sbagliato.
def attendi_server(secondi: float = 10.0) -> bool:
    import time
    fine = time.time() + secondi
    while time.time() < fine:
        try:
            with urllib.request.urlopen(BASE + "/api/state", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.05)
    return False


if not attendi_server():
    raise SystemExit("il server di prova non ha accettato connessioni")


def post(path: str, corpo: dict, headers: dict | None = None):
    dati = json.dumps(corpo).encode()
    ultimo = None
    # Su Windows, con tante connessioni ravvicinate su loopback, il
    # riuso del 4-tuple puo' chiudere una connessione nuova: e' un
    # difetto del test (un browser tiene la connessione aperta), non
    # del server. Si riprova la stessa richiesta.
    for tentativo in range(3):
        req = urllib.request.Request(BASE + path, data=dati, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Connection": "close",
                                              **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            testo = e.read().decode()
            e.close()
            try:
                return e.code, json.loads(testo)
            except ValueError:
                return e.code, {"raw": testo}
        except (ConnectionAbortedError, ConnectionResetError) as e:
            ultimo = e
            import time
            time.sleep(0.1 * (tentativo + 1))
    raise ultimo  # type: ignore[misc]


print("== una pagina di un altro sito non comanda il server ==")

codice, corpo = post("/api/system", {"prompt": "CATTIVO"},
                     {"Origin": "http://sito-malevolo.example"})
check("POST cross-site rifiutata", codice == 403, f"{codice} {corpo}")
check("il motivo e' esplicito", "origine" in str(corpo.get("error", "")),
      str(corpo))
check("il prompt non e' cambiato", app.session.agent.system_prompt == "SYS",
      app.session.agent.system_prompt)

codice, corpo = post("/api/system", {"prompt": "CATTIVO"},
                     {"Sec-Fetch-Site": "cross-site",
                      "Origin": BASE})
check("Sec-Fetch-Site cross-site basta da solo", codice == 403,
      f"{codice} {corpo}")

codice, corpo = post("/api/system", {"prompt": "CATTIVO"},
                     {"Origin": "null"})
check("Origin null rifiutata", codice == 403, f"{codice} {corpo}")

print("\n== la stessa origine passa ==")

codice, corpo = post("/api/system", {"prompt": "NUOVO"}, {"Origin": BASE})
check("POST stessa-origine accettata", codice == 200, f"{codice} {corpo}")
check("il prompt e' stato applicato",
      app.session.agent.system_prompt == "NUOVO",
      app.session.agent.system_prompt)

# Anche senza Origin (curl, script) la richiesta passa: non e' un browser,
# e il token resta l'autorizzazione per chi arriva da fuori.
codice, corpo = post("/api/system", {"prompt": "SENZA-ORIGIN"})
check("client senza Origin accettato", codice == 200, f"{codice} {corpo}")

print("\n== il login non si prova a forza bruta ==")

app.token_remoto = "token-di-prova-123"
codici = [post("/api/login", {"token": "sbagliato"}, {"Origin": BASE})[0]
          for _ in range(7)]
check("i primi tentativi sbagliati danno 401", codici[:6] == [401] * 6,
      str(codici))
check("oltre la soglia arriva 429", codici[-1] == 429, str(codici))

codice, corpo = post("/api/login", {"token": "token-di-prova-123"},
                     {"Origin": BASE})
check("il limite vale anche per il token giusto", codice == 429,
      f"{codice} {corpo}")

print("\n== l'analisi del tempo non e' nel codice ==")

import inspect  # noqa: E402

sorgente = inspect.getsource(webapp.Handler._gate_remoto)
check("il token si confronta a tempo costante", "compare_digest" in sorgente)

httpd.shutdown()

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
