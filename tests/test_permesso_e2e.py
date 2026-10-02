"""Il canale dei permessi, verificato sul server che gira.

La prima versione mandava un messaggio all'agente e sperava che
sbagliasse. L'ha fatto: ha girato un grep dentro la root e si e' fermato
li'. Il test e' fallito, e aveva ragione a fallire — perche' non aveva
provato niente, e un test che passa senza aver provato niente e' peggio
di un test che non esiste.

Ora la domanda parte senza passare da un modello: /api/permesso/prova
genera un'evento vera, e noi guardiamo se arriva all'SSE e se le tre
scelte fanno quello che promettono.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8737"
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


eventi = []
sse_ok = threading.Event()
stop = threading.Event()


def ascolta():
    """Legge l'SSE con un socket grezzo.

    Con urllib l'iterazione bufferizza e gli eventi in tempo reale
    arrivano tardi: il test li contava come persi e il canale sembrava
    rotto mentre funzionava. Un socket grezzo legge quello che arriva,
    che e' l'unica cosa che conta qui.
    """
    try:
        s = socket.create_connection(("127.0.0.1", 8737), timeout=180)
        s.sendall(
            b"GET /api/stream HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8737\r\n"
            b"Accept: text/event-stream\r\n"
            b"Connection: keep-alive\r\n\r\n")
        sse_ok.set()
        buf = b""
        while not stop.is_set():
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return
            buf += chunk
            while b"\n\n" in buf:
                blocco, _, buf = buf.partition(b"\n\n")
                for line in blocco.split(b"\n"):
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    try:
                        eventi.append(json.loads(line[5:].decode("utf-8")))
                    except ValueError:
                        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


_n = [0]


def cartella_pulita():
    """Una cartella nuova ogni volta.

    Rispondere "mai" a un percorso lo mette negli negati per sempre: e'
    il comportamento giusto, ma in un test significa che la verifica
    successiva su quella stessa cartella viene negata all'istante senza
    mai fare la domanda. La prima versione di questo test si sabotava
    cosi' da sola, e falliva senza che nulla fosse rotto.
    """
    _n[0] += 1
    d = os.path.join(tempfile.gettempdir(),
                     "orch-prova-%d-%d" % (os.getpid(), _n[0]))
    os.makedirs(d, exist_ok=True)
    return d


def attendi_domanda(rid, secondi=12):
    t0 = time.time()
    while time.time() - t0 < secondi:
        for e in eventi:
            if (e.get("kind") == "permission_request"
                    and e["data"].get("id") == rid):
                return e["data"]
        time.sleep(0.2)
    return None


print("\n[1] Il server e' in ascolto e l'SSE si apre")
st = post("/api/permessi", {})
print(f"  root: {st.get('root')}")
threading.Thread(target=ascolta, daemon=True).start()
check("l'SSE si apre", sse_ok.wait(timeout=15))
time.sleep(1.0)

print("\n[2] La domanda parte e arriva sull'SSE")
# Anche QUI una cartella nuova, e per la stessa ragione della riga
# sotto: senza, questa prova usa il percorso di default — Documents —
# e se una corsa precedente di questo test ha risposto "mai" su
# quella cartella, il gate la nega SENZA chiedere. Il test non
# falliva, semplicemente non testava niente: si fermava al primo check
# e andava avanti con gli altri.
#
# È la stessa cosa che rende un test non ripetibile: uno stato che
# sopravvive alla corsa. Il server tiene i negati apposta — devono
# sopravvivere — e il test deve quindi cambiare bersaglio, non il
# server.
risp = post("/api/permesso/prova", {"cartella": cartella_pulita()})
check("il server accetta la prova", risp.get("ok") is True, str(risp)[:100])
check("la domanda e' in attesa", risp.get("in_attesa") is True, str(risp))
domanda = attendi_domanda(risp.get("id"))
check("l'evento permission_request e' arrivato", domanda is not None,
      "eventi: " + ", ".join(sorted({e.get("kind", "?") for e in eventi})))
if domanda:
    print(f"  percorso proposto: {domanda.get('percorso')}")
    check("l'evento porta un percorso", bool(domanda.get("percorso")))
    check("porta l'azione", bool(domanda.get("azione")),
          str(domanda.get("azione")))

print("\n[3] Le tre scelte rispondono")
for scelta, nome in (("una_volta", "una volta"),
                     ("sessione", "per sessione"),
                     ("mai", "mai")):
    # Una cartella NUOVA per ogni scelta, e non perche' sia piu' pulito:
    # perche' il gate tiene la concessione per la sessione, e con lo
    # stesso percorso la terza scelta non trova nessuna domanda da
    # aspettare — il gate ha gia' risposto "concesso" alla seconda, e
    # risponde correttamente.
    #
    # Il test si aspettava tre domande su tre scelte diverse, e su due
    # percorsi diversi ne otteneva due: la seconda consumava la
    # concessione anche per la terza. Non e' un difetto del gate: e'
    # esattamente cio' che deve fare. E il test non era mai fallito
    # perche' prima girava su un server che non aveva ancora la
    # concessione per sessione attiva in quel momento.
    r2 = post("/api/permesso/prova", {"cartella": cartella_pulita()})
    ev = attendi_domanda(r2.get("id"))
    if not ev:
        check(f"domanda '{nome}' partita", False, "nessun evento")
        continue
    risposta = post("/api/permesso", {"id": r2.get("id"), "scelta": scelta})
    check(f"risposta '{nome}' accettata", risposta.get("ok") is True,
          str(risposta)[:100])
    time.sleep(0.8)

print("\n[4] Una scelta inesistente viene respinta")
r4 = post("/api/permesso/prova", {"cartella": cartella_pulita()})
attendi_domanda(r4.get("id"))
try:
    r5 = post("/api/permesso", {"id": r4.get("id"), "scelta": "per_sempre"})
    check("una scelta sconosciuta non passa", False, "accettata: " + str(r5)[:70])
except urllib.error.HTTPError as e:
    # 400 e' la risposta giusta: una scelta che non esiste non puo'
    # diventare "concesso perche' non l'ho capita"
    check("una scelta sconosciuta non passa", e.code == 400, str(e.code))
# e la domanda resta appesa, perche' nessuno ha risposto
sospeso = post("/api/permessi", {})
check("la domanda resta in attesa se nessuno risponde",
      r4.get("id") in (sospeso.get("in_attesa") or []),
      str(sospeso.get("in_attesa")))
post("/api/permesso", {"id": r4.get("id"), "scelta": "mai"})

print("\n[5] 'Per sessione' concede e si revoca")
r6 = post("/api/permesso/prova", {})
ev6 = attendi_domanda(r6.get("id"))
if ev6:
    post("/api/permesso", {"id": r6["id"], "scelta": "sessione"})
    time.sleep(0.8)
    dopo = post("/api/permessi", {})
    check("il permesso e' stato ricordato", len(dopo.get("sessione", [])) >= 1,
          str(dopo.get("sessione")))
    if dopo.get("sessione"):
        percorso = dopo["sessione"][0]["percorso"]
        rev = post("/api/permessi", {"revoca": percorso})
        check("il permesso si revoca", rev.get("ok") is True, str(rev)[:80])
else:
    check("la domanda e' arrivata", False, "nessun evento")

print("\n[6] Niente resta appeso")
finale = post("/api/permessi", {})
check("nessuna domanda in attesa", not finale.get("in_attesa"),
      str(finale.get("in_attesa")))

stop.set()
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
