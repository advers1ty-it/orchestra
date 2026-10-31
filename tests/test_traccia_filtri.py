"""I filtri delle tracce, applicati dal database e non dal client.

Il difetto che evitano: la lista e' tagliata (`LIMIT 50`), e filtrare nel
browser dopo averla letta nasconderebbe il turno fallito di ieri dietro
cinquanta turni riusciti di oggi. La domanda "perche' quel task ha
sbagliato" e' quasi sempre su un turno vecchio.

Nessuna rete esterna: il server HTTP e' locale e parla col DB di test.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

_TMP = tempfile.mkdtemp(prefix="orchestra_tracce_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import traccia  # noqa: E402
from orchestra import webapp  # noqa: E402

# `orchestra/__init__.py` migra i file di stato, e fra quelli c'e' lo
# storico: un ORCHESTRA_HOME nuovo puo' nascere con le tracce VERE
# dell'utente. Per un test che conta le righe e' veleno — le asserzioni
# passerebbero o fallirebbero a seconda di cosa ha fatto l'utente ieri.
# Si riparte da un DB vuoto, che e' la premessa del test.
# Il file vero e' `storico.db` (vedi `storico.percorso_db`);
# `storico.sqlite3` e' il nome vecchio, che la migrazione puo' aver
# lasciato accanto. Si tolgono entrambi: qui non si sta testando la
# migrazione, si sta testando il filtro.
for _nome in ("storico.db", "storico.sqlite3"):
    try:
        os.remove(os.path.join(os.environ["ORCHESTRA_HOME"], _nome))
    except OSError:
        pass

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def salva(esito, errori, modello="m"):
    r = traccia.RegistratoreTurno(sessione_id=None)
    r.registra("tool_start", {"name": "read_file", "args": {"path": "a.txt"}})
    r.registra("tool_end", {"name": "read_file", "ok": errori == 0,
                            "result": "errore" if errori else "ok"})
    r.imposta_riepilogo(esito=esito, iterazioni=2, tool_chiamate=1,
                        errori=errori, token=10, modello=modello,
                        evento_finale=esito)
    return r.salva()


print("\n[1] I filtri del modulo")
ok_id = salva("risposta_finale", 0)
time.sleep(0.01)
ko_id = salva("max_iterations", 3)
tutte = traccia.ultime(limite=10)
check("senza filtri ci sono entrambe", len(tutte) == 2, str(tutte))
check("la piu' recente viene prima", tutte[0]["id"] == ko_id,
      str([t["id"] for t in tutte]))

solo_ko = traccia.ultime(limite=10, esito="max_iterations")
check("il filtro esito tiene solo quella", [t["id"] for t in solo_ko] == [ko_id],
      str([t["id"] for t in solo_ko]))
solo_ok = traccia.ultime(limite=10, esito="risposta_finale")
check("e l'altro esito tiene l'altra", [t["id"] for t in solo_ok] == [ok_id],
      str([t["id"] for t in solo_ok]))
solo_errori = traccia.ultime(limite=10, solo_errori=True)
check("solo errori esclude i turni puliti",
      [t["id"] for t in solo_errori] == [ko_id],
      str([t["id"] for t in solo_errori]))
check("i due filtri si combinano",
      traccia.ultime(limite=10, esito="risposta_finale",
                     solo_errori=True) == [])
check("un limite assurdo viene riportato in un intervallo valido",
      len(traccia.ultime(limite=-4)) == 1, str(traccia.ultime(limite=-4)))

print("\n[2] La rotta HTTP usa gli stessi filtri")
app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app.env = {}
app.session = None
app.ready = True
app.error = ""
app.remoto_attivo = False
app.token_remoto = ""
webapp.Handler.app = app

s = socket.socket()
s.bind(("127.0.0.1", 0))
porta = s.getsockname()[1]
s.close()
base = f"http://127.0.0.1:{porta}"
server = webapp.ThreadingHTTPServer(("127.0.0.1", porta), webapp.Handler)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.25)


def get(percorso):
    req = urllib.request.Request(base + percorso)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


try:
    stato, d = get("/api/tracce")
    check("GET /api/tracce risponde", stato == 200 and len(d.get("tracce") or []) == 2,
          f"{stato} {str(d)[:160]}")
    stato, d = get("/api/tracce?esito=max_iterations")
    check("la rotta filtra per esito",
          [t["id"] for t in (d.get("tracce") or [])] == [ko_id],
          f"{stato} {str(d)[:160]}")
    stato, d = get("/api/tracce?errori=1")
    check("la rotta filtra per errori",
          [t["id"] for t in (d.get("tracce") or [])] == [ko_id],
          f"{stato} {str(d)[:160]}")
    stato, d = get("/api/tracce?esito=risposta_finale&errori=1")
    check("i filtri si combinano anche nella rotta",
          (d.get("tracce") or []) == [], f"{stato} {str(d)[:160]}")
    stato, d = get("/api/tracce?limite=abc")
    check("un limite non numerico non rompe la rotta",
          stato == 200 and len(d.get("tracce") or []) == 2,
          f"{stato} {str(d)[:160]}")
finally:
    server.shutdown()
    server.server_close()

print(f"\n{'='*50}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
    sys.exit(1)
print("Tutto verde.")
