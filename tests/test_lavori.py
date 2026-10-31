"""I lavori durevoli: la coda che sopravvive al processo.

La promessa di `lavori.py` e' precisa, e si puo' verificare tutta senza
rete:

1. gli stati sono una macchina a stati, non un'etichetta;
2. il claim e' atomico anche con piu' consumatori;
3. un processo che muore lascia il lavoro su disco;
4. al riavvio i lavori in attesa ripartono e quelli a meta' diventano
   `interrotto`, non vengono rieseguiti alla cieca;
5. il pannello puo' riprovare un lavoro interrotto, e le rotte HTTP
   fanno quello che dice il pannello.

Il test gira in una cartella dati temporanea: non tocca i lavori veri.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

_TMP = tempfile.mkdtemp(prefix="orchestra_lavori_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orchestra import bots as bt  # noqa: E402
from orchestra import lavori as lv  # noqa: E402
from orchestra import webapp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def attendi(pred, timeout=6.0):
    scadenza = time.time() + timeout
    while time.time() < scadenza:
        if pred():
            return True
        time.sleep(0.02)
    return False


def stato(job):
    voce = lv.ottieni(job["id"])
    return voce["stato"] if voce else ""


class SessioneFinta:
    """Registra i compiti ricevuti e risponde subito.

    Non c'e' un Agent: il consumatore legge `snapshot()` e `busy`, quindi
    bastano questi tre metodi per provare la ripresa senza rete e senza
    modello.
    """

    def __init__(self):
        self.busy = False
        self.messaggi = []
        self.inviati = []
        self.annullata = False
        self._lock = threading.Lock()

    def send(self, testo):
        with self._lock:
            self.inviati.append(testo)
            self.messaggi.append({"role": "user", "content": testo})
            self.messaggi.append({"role": "assistant",
                                  "content": "risposta a " + testo})
        return True

    def snapshot(self):
        with self._lock:
            return {"messages": list(self.messaggi)}

    def cancel(self):
        self.annullata = True


print("\n[1] La macchina a stati")

j1 = lv.accoda("bot", "7", {"testo": "primo"}, titolo="primo",
               max_tentativi=2)
j2 = lv.accoda("bot", "7", {"testo": "secondo"}, titolo="secondo")
check("un lavoro nuovo e' in attesa", j1["stato"] == "in_attesa",
      str(j1["stato"]))
check("il payload e' quello scritto",
      (j1.get("payload") or {}).get("testo") == "primo", str(j1.get("payload")))
check("il titolo e' salvato", j1.get("titolo") == "primo")

w1 = lv.prossimo("bot", "7")
check("il claim restituisce il piu' vecchio",
      bool(w1) and w1["id"] == j1["id"], str(w1 and w1["id"]))
check("il claim lo mette in corso", stato(j1) == "in_corso", stato(j1))
check("il claim conta il tentativo",
      bool(w1) and w1["tentativi"] == 1, str(w1 and w1["tentativi"]))
w2 = lv.prossimo("bot", "7")
check("il claim successivo prende il secondo, non lo stesso",
      bool(w2) and w2["id"] == j2["id"], str(w2 and w2["id"]))
check("una coda vuota non inventa un lavoro",
      lv.prossimo("bot", "7") is None)
check("la coda non e' globale: un'altra chiave e' separata",
      lv.prossimo("bot", "8") is None)
check("il secondo tentativo e' indipendente",
      bool(w2) and w2["tentativi"] == 1)

fatto = lv.completa(j1["id"], "risultato primo")
check("completare chiude il lavoro",
      bool(fatto) and fatto["stato"] == "completato", str(fatto))
check("il risultato e' salvato",
      bool(fatto) and fatto["risultato"] == "risultato primo")
check("completare due volte non riscrive",
      lv.completa(j1["id"], "altro") is None)
lv.completa(w2["id"], "fatto")

print("\n[2] Fallimento, retry e annullamento")

f1 = lv.accoda("bot", "11", {"testo": "fallisce"}, max_tentativi=1)
w = lv.prossimo("bot", "11")
fallito = lv.fallisci(f1["id"], "provider rotto")
check("fallire chiude con l'errore",
      bool(fallito) and fallito["stato"] == "fallito", str(fallito))
check("l'errore e' quello scritto",
      bool(fallito) and fallito["errore"] == "provider rotto")
check("un lavoro fallito non si riprende da solo",
      lv.prossimo("bot", "11") is None)
check("fallire di nuovo non cambia un lavoro chiuso",
      lv.fallisci(f1["id"], "altro")["errore"] == "provider rotto")

ri = lv.riprova(f1["id"])
check("riprova lo rimette in attesa",
      bool(ri) and ri["stato"] == "in_attesa", str(ri))
check("riprova alza il tetto dei tentativi",
      bool(ri) and ri["max_tentativi"] > ri["tentativi"],
      str(ri and (ri["tentativi"], ri["max_tentativi"])))
w = lv.prossimo("bot", "11")
check("riprovato, riparte",
      bool(w) and w["tentativi"] == 2, str(w and w["tentativi"]))
lv.completa(w["id"], "al secondo tentativo")

f2 = lv.accoda("bot", "12", {"testo": "riprova automatico"},
               max_tentativi=2)
w = lv.prossimo("bot", "12")
r = lv.fallisci(f2["id"], "errore temporaneo", riprova=True)
check("riprova=True rimette in attesa finche' ci sono tentativi",
      bool(r) and r["stato"] == "in_attesa", str(r))
w = lv.prossimo("bot", "12")
r = lv.fallisci(f2["id"], "errore definitivo", riprova=True)
check("esauriti i tentativi resta fallito",
      bool(r) and r["stato"] == "fallito", str(r))

a1 = lv.accoda("bot", "13", {"testo": "da annullare"})
ann = lv.annulla(a1["id"])
check("annullare un lavoro in attesa lo chiude",
      bool(ann) and ann["stato"] == "annullato", str(ann))
check("un annullato non viene eseguito",
      lv.prossimo("bot", "13") is None)
check("annullarlo due volte non e' possibile",
      lv.annulla(a1["id"]) is None)
check("un annullato non si riprova con il tasto sbagliato",
      lv.riprova(a1["id"]) is None)

a2 = lv.accoda("bot", "14", {"testo": "annulla in corsa"})
lv.prossimo("bot", "14")
ann2 = lv.annulla(a2["id"])
check("annullare un lavoro in corso lo chiude",
      bool(ann2) and ann2["stato"] == "annullato", str(ann2))
check("il consumatore che finisce dopo non lo riapre",
      lv.completa(a2["id"], "troppo tardi") is None)

print("\n[3] Ordine, tetto e riepilogo")
for testo in ("a", "b", "c"):
    lv.accoda("bot", "15", {"testo": testo})
presi = []
while True:
    w = lv.prossimo("bot", "15")
    if w is None:
        break
    presi.append((w.get("payload") or {}).get("testo"))
    lv.completa(w["id"], "ok")
check("la coda rispetta l'ordine FIFO", presi == ["a", "b", "c"], str(presi))

lv.accoda("bot", "16", {"testo": "uno"}, limite=2)
lv.accoda("bot", "16", {"testo": "due"}, limite=2)
try:
    lv.accoda("bot", "16", {"testo": "tre"}, limite=2)
    rifiutato = False
except RuntimeError:
    rifiutato = True
check("il tetto della coda rifiuta il lavoro in piu'", rifiutato)

lv.accoda("bot", "17", {"testo": "chiuso"}, limite=1)
w = lv.prossimo("bot", "17")
lv.completa(w["id"], "fatto")
accettato = True
try:
    lv.accoda("bot", "17", {"testo": "dopo"}, limite=1)
except RuntimeError:
    accettato = False
check("il tetto conta solo i lavori attivi", accettato)

lv.accoda("bot", "18", {"testo": "completato"})
w = lv.prossimo("bot", "18")
lv.completa(w["id"], "una risposta")
f = lv.accoda("bot", "18", {"testo": "fallito"}, max_tentativi=1)
w = lv.prossimo("bot", "18")
lv.fallisci(f["id"], "un errore")
r = lv.riassunto("bot", "18")
check("il riepilogo conta i completati",
      r.get("completati") == 1, str(r.get("conteggi")))
check("il riepilogo conta i falliti",
      r.get("falliti") == 1, str(r.get("conteggi")))
check("il riepilogo espone l'ultimo terminale",
      bool(r.get("ultimo")) and r["ultimo"]["stato"] == "fallito",
      str(r.get("ultimo")))
check("il riepilogo espone il lavoro riprovabile",
      bool(r.get("riprovabile")) and r["riprovabile"]["id"] == f["id"],
      str(r.get("riprovabile")))
check("il riepilogo non inventa un lavoro in corso",
      r.get("in_corso") == 0 and r.get("in_corso_id") == 0, str(r))

# Il pulsante Riprova non deve sparire solo perche' davanti al lavoro
# interrotto ci sono venti compiti andati bene.
for i in range(21):
    j = lv.accoda("bot", "18", {"testo": f"dopo {i}"})
    w = lv.prossimo("bot", "18")
    lv.completa(w["id"], "ok")
r = lv.riassunto("bot", "18")
check("un lavoro riprovabile vecchio resta visibile",
      bool(r.get("riprovabile")) and r["riprovabile"]["id"] == f["id"],
      str(r.get("riprovabile")))
check("il riepilogo conta anche lo storico fuori dai venti recenti",
      r.get("completati") == 22, str(r.get("conteggi")))

lv.elimina_chiave("bot", "18")
check("eliminare una chiave toglie il suo storico",
      lv.riassunto("bot", "18").get("completati") == 0)

print("\n[4] Claim atomico con piu' consumatori")
job_conc = lv.accoda("bot", "19", {"testo": "uno solo"})
esiti = []
barriera = threading.Barrier(8)


def consumatore():
    barriera.wait()
    try:
        esiti.append(lv.prossimo("bot", "19"))
    except Exception as e:  # noqa: BLE001
        esiti.append(e)


fili = [threading.Thread(target=consumatore) for _ in range(8)]
for f in fili:
    f.start()
for f in fili:
    f.join(timeout=20)
vinti = [e for e in esiti if isinstance(e, dict)]
errori = [e for e in esiti if isinstance(e, Exception)]
check("otto consumatori, nessun errore", not errori, str(errori[:1]))
check("solo un consumatore vince il lavoro", len(vinti) == 1,
      f"{len(vinti)} vincitori su {len(esiti)}")
check("il vincitore ha il lavoro giusto",
      bool(vinti) and vinti[0]["id"] == job_conc["id"])
vinto = lv.ottieni(job_conc["id"])
check("il lavoro e' in corso una volta sola",
      bool(vinto) and vinto["stato"] == "in_corso"
      and vinto["tentativi"] == 1, str(vinto))
if vinto:
    lv.completa(vinto["id"], "ok")

print("\n[5] Un processo che muore lascia il lavoro su disco")
job_crash = lv.accoda("bot", "20", {"testo": "meta' strada"})
script = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from orchestra import lavori as lv
j = lv.prossimo("bot", "20")
print(json.dumps({"id": j["id"] if j else None}))
sys.stdout.flush()
os._exit(17)
"""
proc = subprocess.run(
    [sys.executable, "-c", script, ROOT],
    env=dict(os.environ),
    capture_output=True, text=True, timeout=30,
)
check("il processo figlio e' morto a meta'", proc.returncode == 17,
      f"exit {proc.returncode}: {proc.stderr[-300:]}")
try:
    preso_dal_figlio = json.loads((proc.stdout or "").strip().splitlines()[-1])
except (ValueError, IndexError):
    preso_dal_figlio = {}
check("il figlio aveva preso il lavoro",
      preso_dal_figlio.get("id") == job_crash["id"], str(proc.stdout[-300:]))
check("dopo la morte il lavoro e' ancora in corso",
      stato(job_crash) == "in_corso", stato(job_crash))

interrotti = lv.interrompi_in_corso("bot")
check("il recupero trova il lavoro interrotto", interrotti >= 1,
      str(interrotti))
check("il lavoro orfano diventa interrotto",
      stato(job_crash) == "interrotto", stato(job_crash))
voce = lv.ottieni(job_crash["id"])
check("l'interruzione porta il motivo",
      bool(voce) and "riavvio" in voce.get("errore", ""),
      str(voce and voce.get("errore")))
check("un lavoro interrotto non riparte da solo",
      lv.prossimo("bot", "20") is None)

check("un lavoro interrotto si puo' riprovare",
      (lv.riprova(job_crash["id"]) or {}).get("stato") == "in_attesa")
w = lv.prossimo("bot", "20")
check("riprovato, il lavoro riparte", bool(w) and w["id"] == job_crash["id"])
lv.completa(w["id"], "fatto dopo il crash")

# Le sezioni precedenti lasciano apposta delle code (il tetto di
# sezione 3 non consuma i due lavori ammessi). Il riavvio di sezione 6
# guarda TUTTE le chiavi, quindi quelle code renderebbero il conteggio
# dipendente dal fatto che il loro consumatore abbia gia' finito: un
# test a intermittenza. Si tolgono prima di isolare il caso che conta.
for _chiave in ("7", "8", "11", "12", "13", "14", "15", "16",
                "17", "18", "19", "20"):
    lv.elimina_chiave("bot", _chiave)

print("\n[6] Il server riprende le code dopo un avvio")
bot = bt.crea("Durevole", persona="prova")
ident = int(bot["id"])
sess = SessioneFinta()

app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app.env = {}
app.session = None
app.remoto_attivo = False
app.token_remoto = ""
app._bots_fili = {}
app._bots_fili_lock = threading.RLock()
app._bots_runtime = {ident: {"sessione": sess}}
app._sessione_bot = lambda b: sess  # type: ignore[method-assign]

orfano = lv.accoda("bot", str(ident), {"testo": "turno a meta'"})
w = lv.prossimo("bot", str(ident))  # simula il processo morto
check("il lavoro orfano e' in corso prima del riavvio",
      bool(w) and w["id"] == orfano["id"], str(w and w["id"]))
in_attesa = lv.accoda("bot", str(ident), {"testo": "riprendi dopo il boot"})

ripresi = app._riprendi_lavori_bot()
check("il riavvio marca il lavoro a meta'", ripresi >= 1, str(ripresi))
check("il lavoro a meta' resta interrotto",
      stato(orfano) == "interrotto", stato(orfano))
ok = attendi(lambda: stato(in_attesa) == "completato")
check("il lavoro in attesa riparte da solo", ok, stato(in_attesa))
check("il turno interrotto non viene rieseguito alla cieca",
      "turno a meta'" not in sess.inviati, str(sess.inviati))
check("il turno ripreso e' quello giusto",
      sess.inviati == ["riprendi dopo il boot"], str(sess.inviati))
check("la risposta del turno finisce nel lavoro",
      (lv.ottieni(in_attesa["id"]) or {}).get("risultato")
      == "risposta a riprendi dopo il boot")

prima = len(sess.inviati)
ripresi2 = app._riprendi_lavori_bot()
time.sleep(0.2)
check("un secondo riavvio non duplica il lavoro",
      ripresi2 == 0 and len(sess.inviati) == prima,
      f"{ripresi2}, {sess.inviati}")

nuovo = app.riprova_lavoro(orfano["id"])
check("il pannello rimette in coda l'interrotto",
      (nuovo or {}).get("stato") in ("in_attesa", "in_corso"), str(nuovo))
ok = attendi(lambda: stato(orfano) == "completato")
check("il lavoro riprovato arriva in fondo", ok, stato(orfano))
check("il turno riprovato e' stato eseguito",
      "turno a meta'" in sess.inviati, str(sess.inviati))

# Annullare un lavoro che sta aspettando la sessione non deve fermare
# il turno dell'utente che la sta usando.
da_fermare = lv.accoda("bot", str(ident), {"testo": "in attesa della sessione"})
lv.prossimo("bot", str(ident))
sess.busy = True
annullato = app.annulla_lavoro(da_fermare["id"])
check("annullare un lavoro in corso lo chiude",
      (annullato or {}).get("stato") == "annullato", str(annullato))
check("annullarlo non ferma la sessione dell'utente",
      sess.annullata is False)
sess.busy = False

try:
    app.riprova_lavoro(999999)
    mancante = False
except ValueError:
    mancante = True
check("riprovare un lavoro inesistente e' un errore chiaro", mancante)

print("\n[7] Le rotte HTTP del pannello")
server = None
try:
    porta = socket.socket()
    porta.bind(("127.0.0.1", 0))
    PORT = porta.getsockname()[1]
    porta.close()
    webapp.Handler.app = app
    server = webapp.ThreadingHTTPServer(("127.0.0.1", PORT), webapp.Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.2)
    BASE = f"http://127.0.0.1:{PORT}"

    def richiesta(percorso, corpo=None):
        dati = None
        intestazioni = {}
        if corpo is not None:
            dati = json.dumps(corpo).encode("utf-8")
            intestazioni["Content-Type"] = "application/json"
        req = urllib.request.Request(
            BASE + percorso, data=dati, headers=intestazioni,
            method="POST" if dati else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    stato_http, d = richiesta("/api/lavori")
    check("GET /api/lavori risponde anche senza query",
          stato_http == 200 and isinstance(d.get("lavori"), list),
          f"{stato_http} {str(d)[:120]}")

    stato_http, d = richiesta(f"/api/lavori?tipo=bot&chiave={ident}")
    check("GET /api/lavori risponde", stato_http == 200 and d.get("ok") is True,
          f"{stato_http} {str(d)[:120]}")
    check("la rotta filtra per chiave",
          all(x.get("chiave") == str(ident) for x in (d.get("lavori") or [])),
          str(d.get("lavori")))

    stato_http, d = richiesta(f"/api/lavori?tipo=bot&chiave={ident}&limite=1")
    check("la rotta rispetta il limite",
          stato_http == 200 and len(d.get("lavori") or []) == 1,
          str(d.get("lavori")))

    da_annullare = lv.accoda("bot", "888", {"testo": "da fermare"})
    stato_http, d = richiesta("/api/lavori/annulla",
                              {"id": da_annullare["id"]})
    check("POST /api/lavori/annulla chiude il lavoro",
          stato_http == 200 and (d.get("lavoro") or {}).get("stato")
          == "annullato", f"{stato_http} {str(d)[:160]}")
    stato_http, d = richiesta("/api/lavori/annulla",
                              {"id": da_annullare["id"]})
    check("annullare due volte risponde 409", stato_http == 409, str(stato_http))

    da_riprovare = lv.accoda("bot", "889", {"testo": "da riprovare"})
    lv.prossimo("bot", "889")
    lv.interrompi_in_corso("bot")
    stato_http, d = richiesta("/api/lavori/riprova",
                              {"id": da_riprovare["id"]})
    check("POST /api/lavori/riprova accetta un interrotto",
          stato_http == 200 and (d.get("lavoro") or {}).get("stato")
          in ("in_attesa", "in_corso"), f"{stato_http} {str(d)[:160]}")

    stato_http, d = richiesta("/api/lavori/riprova", {"id": 999999})
    check("riprovare un lavoro inesistente risponde 400",
          stato_http == 400, str(stato_http))
finally:
    if server is not None:
        server.shutdown()
        server.server_close()

shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
