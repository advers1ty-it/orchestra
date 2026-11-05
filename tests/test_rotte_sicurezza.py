"""Le rotte HTTP, provate su un server vero (in-process, porta libera).

Era il buco piu' grosso: `rotte_*`, `webapp_rotte` e `webapp` non erano
importati da nessun test, e li' vivono le cose che fanno danno — cookie,
controllo dell'`Origin`, upload, path traversal sui file statici, limiti
di richiesta. Il loop dell'agente aveva suite serie; il bordo HTTP no.

Non si prova che "la pagina si vede": si prova che il server rifiuta
quello che deve rifiutare, che non risponde 500 a un input storto, e che
non serve file fuori da `orchestra/web` — che e' la classe di bug in cui
il server diventa un lettore di file arbitrario.

Server in-process e non nel sottoprocesso del runner: qui servono
risposte deterministiche su 403/400/429, e un server condiviso con altre
suite introdurrebbe lo stato di quelle (turni aperti, rate limit gia'
consumati).
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request

_ROOT_TEST = tempfile.mkdtemp(prefix="rotte-")
os.environ["ORCHESTRA_HOME"] = os.path.join(_ROOT_TEST, "dati")
os.environ["ORCHESTRA_ROOT"] = _ROOT_TEST
os.environ.pop("ORCHESTRA_REMOTE_TOKEN", None)
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import rotte_chat  # noqa: E402
from orchestra import webapp  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# Le rotte che salvano un'impostazione scrivono in `ENV_PATH`, che e'
# un percorso FISSO dentro il repo (`orchestra/.env`): senza questo, il
# test avrebbe riscritto la configurazione vera dell'utente. Il file
# temporaneo e' anche la prova che il salvataggio funziona davvero,
# invece di fidarsi della risposta 200.
ENV_DI_TEST = os.path.join(_ROOT_TEST, "env-test")

# Prima si crea l'app (che LEGGE il .env vero per sapere provider e
# modello), poi si sposta solo la destinazione delle SCRITTURE: se si
# sposta prima, l'app nasce senza configurazione e ogni rotta risponde
# 503 — un test che descrive un'app rotta invece del codice.
app = webapp.OrchestraApp.create(remoto_attivo=False)
rotte_chat.ENV_PATH = ENV_DI_TEST
webapp.Handler.app = app
server = webapp.OrchestraServer(("127.0.0.1", 0), webapp.Handler)
PORT = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
BASE = f"http://127.0.0.1:{PORT}"


def chiama(percorso, *, metodo="GET", dati=None, intestazioni=None):
    """(stato, corpo, content-type). Non solleva sugli errori HTTP."""
    corpo = None
    hdrs = dict(intestazioni or {})
    if dati is not None:
        corpo = json.dumps(dati).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(BASE + percorso, data=corpo, method=metodo,
                                 headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")
    except urllib.error.URLError as e:
        return 0, str(e).encode(), ""


def corpo_testo(corpo):
    return corpo.decode("utf-8", "replace")


try:
    print("\n[1] La pagina si serve, con il tipo giusto")
    stato, corpo, ctype = chiama("/")
    check("GET / risponde 200", stato == 200, str(stato))
    check("e' HTML", "text/html" in ctype, ctype)
    testo = corpo_testo(corpo)
    check("contiene l'interfaccia", "Orchestra" in testo or "<html" in testo.lower(),
          testo[:120])

    stato, corpo, ctype = chiama("/app.css")
    check("il CSS si serve con il suo tipo", stato == 200 and "css" in ctype,
          f"{stato} {ctype}")

    print("\n[2] Una POST da un'altra origine viene rifiutata")
    stato, corpo, _ = chiama("/api/login", metodo="POST", dati={"token": "x"},
                             intestazioni={"Origin": "http://evil.example"})
    check("403 sull'Origin estraneo", stato == 403, str(stato))
    check("il motivo e' detto", "origine" in corpo_testo(corpo).lower(),
          corpo_testo(corpo)[:120])

    # La stessa POST con l'Origin giusto non deve dare 403: il rifiuto
    # precedente era dell'origine, non della rotta.
    stato, corpo, _ = chiama("/api/login", metodo="POST", dati={"token": "x"},
                             intestazioni={"Origin": BASE})
    check("l'origine corretta non prende 403", stato != 403, str(stato))

    print("\n[3] Path traversal: il server non legge fuori da web/")
    for percorso in ("/../.env", "/../orchestra/keys.py", "/..%2f.env",
                     "/%2e%2e/%2e%2e/.env"):
        stato, corpo, _ = chiama(percorso)
        testo = corpo_testo(corpo)
        check(f"{percorso} non espone il file",
              stato in (400, 403, 404) and "ORCHESTRA" not in testo,
              f"{stato} {testo[:80]}")

    print("\n[4] Login: il rate limit ferma i tentativi a raffica")
    esiti = []
    for _ in range(9):
        stato, _, _ = chiama("/api/login", metodo="POST",
                            dati={"token": "sbagliato"},
                            intestazioni={"Origin": BASE})
        esiti.append(stato)
    check("dopo i primi tentativi arriva un 429", 429 in esiti, str(esiti))
    check("non blocca subito (6 al minuto)", esiti[0] != 429, str(esiti))

    print("\n[5] Input storto: 4xx, mai 500")
    casi = [
        ("/api/allega", "POST", {"nome": "x"}),
        ("/api/progetti/file", "POST", {"percorso": "/etc/passwd"}),
        ("/api/lavori/annulla", "POST", {"id": "inesistente"}),
        ("/api/memoria/elimina", "POST", {"id": 999999}),
        ("/api/identita", "POST", {"nome": ""}),
    ]
    for percorso, metodo, dati in casi:
        stato, corpo, _ = chiama(percorso, metodo=metodo, dati=dati,
                                 intestazioni={"Origin": BASE})
        check(f"{percorso}: niente 500", stato != 500,
              f"{stato} {corpo_testo(corpo)[:100]}")
        check(f"{percorso}: risponde qualcosa", stato != 0, str(stato))
        # La risposta deve essere JSON: una pagina d'errore HTML qui
        # vorrebbe dire un'eccezione non gestita travestita da risposta.
        try:
            json.loads(corpo_testo(corpo))
            valido = True
        except ValueError:
            valido = False
        check(f"{percorso}: corpo JSON", valido, corpo_testo(corpo)[:100])

    # Il file di prova che il client chiede deve restare fuori: se il
    # server leggesse `/etc/passwd` lo si vedrebbe nel corpo.
    _, corpo, _ = chiama("/api/progetti/file", metodo="POST",
                         dati={"percorso": "/etc/passwd"},
                         intestazioni={"Origin": BASE})
    check("progetti/file non restituisce un file di sistema",
          "root:" not in corpo_testo(corpo), corpo_testo(corpo)[:120])

    print("\n[5b] Le rotte di automazione e modelli rispondono, senza 500")
    for percorso in ("/api/cron/jobs", "/api/cron/scheduler/status",
                     "/api/modelli", "/api/skill"):
        stato, corpo, _ = chiama(percorso)
        check(f"GET {percorso}: niente 500", stato != 500, f"{stato}")
        check(f"GET {percorso}: 200 con JSON", stato == 200 and bool(corpo),
              f"{stato} {corpo_testo(corpo)[:80]}")

    print("\n[5c] Il tetto di tempo si imposta dall'UI e si legge indietro")
    stato, corpo, _ = chiama("/api/tempo-turno", metodo="POST",
                             dati={"max_secondi_turno": 300},
                             intestazioni={"Origin": BASE})
    check("POST valido: 200", stato == 200, str(stato))
    stato, corpo, _ = chiama("/api/state")
    stato_d = json.loads(corpo_testo(corpo))
    check("lo stato riporta 300 secondi",
          stato_d.get("max_secondi_turno") == 300.0,
          str(stato_d.get("max_secondi_turno")))
    # Salvato, non solo applicato: se non finisce nel file, al riavvio il
    # tetto sparisce e nessuno se ne accorge.
    salvato = ""
    if os.path.exists(ENV_DI_TEST):
        with open(ENV_DI_TEST, encoding="utf-8") as fh:
            salvato = fh.read()
    check("il valore e' scritto nel file di configurazione",
          "ORCHESTRA_MAX_SECONDI_TURNO=300" in salvato, salvato[-120:])
    stato, corpo, _ = chiama("/api/tempo-turno", metodo="POST",
                             dati={"max_secondi_turno": 0},
                             intestazioni={"Origin": BASE})
    check("zero e' accettato (nessun limite)", stato == 200, str(stato))
    stato, corpo, _ = chiama("/api/state")
    check("lo stato riporta zero",
          json.loads(corpo_testo(corpo)).get("max_secondi_turno") == 0.0, "")
    for storto in ("tanto", -5):
        stato, _, _ = chiama("/api/tempo-turno", metodo="POST",
                             dati={"max_secondi_turno": storto},
                             intestazioni={"Origin": BASE})
        check(f"{storto!r}: 400", stato == 400, str(stato))

    # `/api/iterazioni` e' di sola scrittura: la GET deve dire 405 con
    # l'elenco dei metodi, non 200 con un corpo vuoto ne' 500.
    stato, corpo, _ = chiama("/api/iterazioni")
    check("GET /api/iterazioni: 405, non 500", stato == 405, str(stato))
    stato, corpo, _ = chiama("/api/iterazioni", metodo="POST",
                             dati={"max_iterations": 7},
                             intestazioni={"Origin": BASE})
    check("POST /api/iterazioni valido: 200", stato == 200, str(stato))
    stato, corpo, _ = chiama("/api/iterazioni", metodo="POST",
                             dati={"max_iterations": "boh"},
                             intestazioni={"Origin": BASE})
    check("POST /api/iterazioni non numerico: 400", stato == 400, str(stato))

    print("\n[6] JSON rotto: 400, non un'eccezione")
    req = urllib.request.Request(
        BASE + "/api/memoria/aggiungi", data=b"{non json",
        method="POST",
        headers={"Content-Type": "application/json", "Origin": BASE})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            stato = r.status
    except urllib.error.HTTPError as e:
        stato = e.code
    check("JSON invalido -> 400", stato == 400, str(stato))

    print("\n[7] La rotta di stato non trapela segreti")
    stato, corpo, _ = chiama("/api/state")
    testo = corpo_testo(corpo)
    check("GET /api/state risponde 200", stato == 200, str(stato))
    check("nessuna chiave nel corpo", "sk-" not in testo and "API_KEY=" not in testo,
          testo[:200])
finally:
    server.shutdown()
    server.server_close()
    shutil.rmtree(_ROOT_TEST, ignore_errors=True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
