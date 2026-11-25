"""Il tool `processo`: avviare un server, guardarlo, scrivergli, fermarlo.

Il difetto che questo file copre, in una riga: `run_shell` ASPETTA e
uccide al timeout, quindi con Orchestra non si poteva avviare un server e
poi aprire la pagina. Il valore di `processo` non e' "esegue un comando":
e' che il comando resta vivo mentre l'agente fa altro.

Percio' l'ultima sezione non controlla le stringhe: avvia un vero
`python -m http.server`, lo interroga via HTTP, e verifica che dopo
`ferma` la porta sia davvero chiusa. Un tool che dice "avviato" e non
serve una pagina non ha risolto niente.

Si prova anche che i permessi non si aggirino: un comando in background
passa dagli STESSI controlli di `run_shell` (policy, confine della root,
comandi distruttivi). Se non fosse cosi', `rm -rf src &` sarebbe la via
per non far comparire nessuna domanda.
"""

import os
import re
import shutil
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request

_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RADICE)
os.environ["ORCHESTRA_ROOT"] = _RADICE
# I test non devono godere del permesso "distruttivi": la prova qui sotto
# verifica proprio che senza quel permesso il comando non parta.
os.environ.pop("ORCHESTRA_CONSENTI_DISTRUTTIVI", None)

from orchestra.tools import applica_profilo, default_registry  # noqa: E402
from orchestra.tools import processi  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


reg = default_registry()
tool = reg.get("processo")

print("[1] Il tool c'e', e le regole d'uso sono nel contratto")
check("processo e' nel registro", tool is not None)
check("e' attivo nel registro di default", "processo" in reg.nomi_attivi(),
      str(sorted(reg.nomi_attivi()))[:120])
for profilo in ("base", "ricerca", "skill", "pieno"):
    r2 = default_registry()
    applica_profilo(r2, profilo)
    check(f"attivo nel profilo {profilo}", "processo" in r2.nomi_attivi(),
          str(sorted(r2.nomi_attivi()))[:160])
desc = tool.description
check("la descrizione dice che run_shell aspetta",
      "run_shell" in desc and "WAIT" in desc.upper())
check("la descrizione elenca le cinque azioni",
      all(a in desc for a in ("avvia", "leggi", "scrivi", "ferma", "elenca")))
check("le azioni sono quelle del codice",
      tool.schema["properties"]["azione"]["enum"] ==
      ["avvia", "leggi", "scrivi", "ferma", "elenca"])
check("ogni parametro del tool ha una descrizione",
      all(bool(p.get("description"))
          for p in tool.schema["properties"].values()))

print("\n[2] Un comando che muore subito lo dice all'avvio")
r = tool.handler(azione="avvia",
                 comando="python -c \"import sys; print('manca-la-porta'); "
                         "sys.exit(7)\"")
check("il messaggio dice che e' uscito subito", "USCITO SUBITO" in r, r[:160])
check("riporta l'exit code vero", "codice 7" in r, r[:160])
check("allega l'output: e' li' che sta la ragione",
      "manca-la-porta" in r, r[:200])
check("non finge un id da leggere piu' tardi",
      "Leggi l'output con" not in r)

print("\n[3] Un comando vivo: id, lettura ripetibile, stop")
r = tool.handler(azione="avvia",
                 comando="python -c \"import time; print('in-ascolto', "
                         "flush=True); time.sleep(60)\"", attesa=2)
check("l'avvio dice che e' vivo", "AVVIATO" in r and "ancora vivo" in r, r[:160])
m = re.search(r"\b(p\d+)\b", r)
pid_tool = m.group(1) if m else ""
check("il messaggio contiene un id", bool(pid_tool), r[:160])
check("indica come leggerlo e come fermarlo",
      "azione=\"leggi\"" in r and "azione=\"ferma\"" in r)
a = tool.handler(azione="leggi", id=pid_tool, righe=20)
b = tool.handler(azione="leggi", id=pid_tool, righe=20)
check("leggi mostra l'output", "in-ascolto" in a, a[:160])
check("leggere due volte da lo stesso risultato (non consuma)",
      a == b, f"{a[:60]!r} != {b[:60]!r}")
f = tool.handler(azione="ferma", id=pid_tool)
check("ferma dice che l'ha fermato", "FERMATO" in f, f[:160])
check("e non e' piu' vivo", not processi.leggi(pid_tool)["vivo"])
e = tool.handler(azione="elenca")
check("elenca non conta piu' processi vivi", e.startswith("0 vivi"), e[:120])
check("ma il processo uscito resta nell'elenco",
      pid_tool in e, e[:200])

print("\n[3b] Si puo' scrivere su stdin, e l'a capo e' controllabile")
cmd_stdin = ("python -u -c \"import sys; print('pronto-stdin', flush=True); "
             "[print('eco:' + riga.rstrip(), flush=True) "
             "for riga in sys.stdin]\"")
s = tool.handler(azione="avvia", comando=cmd_stdin, attesa=1)
check("il lettore di stdin e' vivo", "AVVIATO" in s, s[:160])
msid = re.search(r"\b(p\d+)\b", s)
sid = msid.group(1) if msid else ""
pronto = ""
for _ in range(25):
    pronto = tool.handler(azione="leggi", id=sid, righe=20) if sid else ""
    if "pronto-stdin" in pronto:
        break
    time.sleep(0.1)
check("il processo ha stampato il prompt", "pronto-stdin" in pronto,
      pronto[:200])
w = tool.handler(azione="scrivi", id=sid, testo="ciao") if sid else ""
check("scrivi dice quanti caratteri ha inviato",
      "SCRITTO" in w and "5 caratteri" in w, w[:200])
check("e indica come leggere la risposta",
      'azione="leggi"' in w, w[:200])
eco = ""
for _ in range(25):
    eco = tool.handler(azione="leggi", id=sid, righe=20) if sid else ""
    if "eco:ciao" in eco:
        break
    time.sleep(0.1)
check("il processo ha ricevuto la riga", "eco:ciao" in eco, eco[:200])
lungo = tool.handler(
    azione="scrivi", id=sid,
    testo="x" * (processi.MASSIMO_STDIN + 1)) if sid else ""
check("un testo troppo lungo viene rifiutato",
      "NON SCRITTO" in lungo and "troppo lungo" in lungo, lungo[:200])
senza = tool.handler(azione="scrivi", id=sid, testo="", a_capo=False) if sid else ""
check("si puo' scrivere senza a capo",
      "SCRITTO" in senza and "senza a capo" in senza, senza[:200])
if sid:
    tool.handler(azione="ferma", id=sid)

cmd_line = ("python -u -c \"import sys; riga = sys.stdin.readline(); "
            "print('letto:' + repr(riga), flush=True)\"")
s2 = tool.handler(azione="avvia", comando=cmd_line, attesa=1)
msid2 = re.search(r"\b(p\d+)\b", s2)
sid2 = msid2.group(1) if msid2 else ""
check("il secondo lettore e' vivo", "AVVIATO" in s2, s2[:160])
w1 = tool.handler(azione="scrivi", id=sid2, testo="senza-capo",
                  a_capo=False) if sid2 else ""
check("scrive senza chiudere la riga",
      "SCRITTO" in w1 and "senza a capo" in w1
      and "10 caratteri" in w1, w1[:200])
time.sleep(0.3)
prima = tool.handler(azione="leggi", id=sid2) if sid2 else ""
check("senza a capo il processo aspetta ancora",
      "--- output ---" not in prima, prima[:200])
w2 = tool.handler(azione="scrivi", id=sid2, testo="", a_capo=True) if sid2 else ""
check("il solo a capo completa la riga",
      "SCRITTO" in w2 and "con a capo" in w2, w2[:200])
letto2 = ""
# Il processo puo' essere ancora in avvio sui runner condivisi: il tetto
# copre l'attesa vera, non un numero scelto per far passare il test.
for _ in range(150):
    letto2 = tool.handler(azione="leggi", id=sid2) if sid2 else ""
    if "letto:" in letto2:
        break
    time.sleep(0.1)
if "letto:" not in letto2 or "senza-capo" not in letto2:
    print(f"  DEBUG w1={w1!r} prima={prima!r} w2={w2!r} "
          f"letto2={letto2!r}")
check("il processo ha letto la riga completa",
      "letto:" in letto2 and "senza-capo" in letto2, letto2[:200])
# Il processo stampa e poi esce: aspettare l'uscita evita di provare a
# scrivere nella finestra in cui la pipe e' gia' chiusa ma `poll()`
# risponde ancora vivo. Il caso "scrivi a un processo davvero finito"
# deve arrivare dal controllo esplicito, non da un errore di pipe.
for _ in range(20):
    if not sid2 or not processi.leggi(sid2)["vivo"]:
        break
    time.sleep(0.1)
morto = tool.handler(azione="scrivi", id=sid2, testo="x") if sid2 else ""
check("scrivi a un processo finito lo dice",
      "NON SCRITTO" in morto and "non e' vivo" in morto, morto[:200])
manca = tool.handler(azione="scrivi", id="", testo="x")
check("senza id il messaggio lo dice", "MANCA L'ID" in manca, manca[:160])
sconosciuto = tool.handler(azione="scrivi", id="p999", testo="x")
check("un id sconosciuto elenca quelli veri",
      "NON SCRITTO" in sconosciuto and "p999" in sconosciuto,
      sconosciuto[:200])

print("\n[3c] Un REPL vero: si scrive un'espressione e si legge il risultato")
repl = tool.handler(azione="avvia", comando="python -u -i -q", attesa=1)
mrepl = re.search(r"\b(p\d+)\b", repl)
rid = mrepl.group(1) if mrepl else ""
check("il REPL e' vivo", "AVVIATO" in repl, repl[:160])
w = tool.handler(azione="scrivi", id=rid, testo="print(2+2)") if rid else ""
check("scrivi accetta un'espressione", "SCRITTO" in w, w[:160])
repl_out = ""
for _ in range(25):
    repl_out = tool.handler(azione="leggi", id=rid) if rid else ""
    if "4" in repl_out and ">>>" in repl_out:
        break
    time.sleep(0.1)
check("il REPL ha eseguito e stampato 4",
      "4" in repl_out and ">>>" in repl_out, repl_out[:200])
if rid:
    tool.handler(azione="scrivi", id=rid, testo="exit()")
    for _ in range(25):
        if not processi.leggi(rid)["vivo"]:
            break
        time.sleep(0.1)
    check("exit() chiude il REPL", not processi.leggi(rid)["vivo"],
          str(processi.leggi(rid))[:200])

print("\n[4] Fermare due volte non e' un errore, e un id sbagliato lo dice")
f2 = tool.handler(azione="ferma", id=pid_tool)
check("fermare un processo gia' finito lo dichiara",
      "niente da fermare" in f2, f2[:160])
bad = tool.handler(azione="leggi", id="p999")
check("un id inesistente elenca quelli veri", "p999" in bad and pid_tool in bad,
      bad[:200])
vuoto = tool.handler(azione="ferma", id="")
check("senza id il messaggio lo dice", "MANCA L'ID" in vuoto, vuoto[:120])
sbagliata = tool.handler(azione="salta")
check("un'azione sconosciuta elenca quelle valide",
      "AZIONE NON VALIDA" in sbagliata and "avvia" in sbagliata
      and "scrivi" in sbagliata)

print("\n[5] Il log sta nella root, cosi' read_file lo puo' aprire")
log = os.path.join(_RADICE, "tmp", "processi", f"{pid_tool}.log")
check("il log e' dentro tmp/processi della root",
      os.path.isfile(log) and os.path.abspath(log).startswith(_RADICE),
      log)
rf = default_registry().get("read_file")
letto = rf.handler(path=f"tmp/processi/{pid_tool}.log")
check("read_file legge il log del processo", "in-ascolto" in letto,
      letto[:160])

print("\n[6] I permessi non si aggirano passando dal background")
fuori = tool.handler(azione="avvia", comando="cat ../../../etc/passwd")
check("un percorso fuori dalla root viene negato",
      "NON ESEGUITO" in fuori, fuori[:200])
distruttivo = tool.handler(azione="avvia", comando="rm -rf orchestra/tools")
check("un comando distruttivo chiede, e senza permesso non parte",
      "NON ESEGUITO" in distruttivo and "distruttivo" in distruttivo,
      distruttivo[:200])
sudo = tool.handler(azione="avvia", comando="sudo rm -rf /")
check("la policy del bot vale anche qui",
      "NON ESEGUITO" in sudo, sudo[:200])

print("\n[7] Il tetto dei processi vivi")
vecchio = processi.MASSIMO_VIVI
processi.MASSIMO_VIVI = 2
try:
    comando = ("python -c \"import time; time.sleep(60)\"")
    a1 = tool.handler(azione="avvia", comando=comando, attesa=0.5)
    a2 = tool.handler(azione="avvia", comando=comando, attesa=0.5)
    a3 = tool.handler(azione="avvia", comando=comando, attesa=0.5)
    check("due avvii partono", "AVVIATO" in a1 and "AVVIATO" in a2,
          f"{a1[:60]} | {a2[:60]}")
    check("il terzo viene rifiutato dicendo cosa fermare",
          "NON AVVIATO" in a3 and "ferma" in a3, a3[:200])
    for msg in (a1, a2):
        mid = re.search(r"\b(p\d+)\b", msg)
        if mid:
            tool.handler(azione="ferma", id=mid.group(1))
finally:
    processi.MASSIMO_VIVI = vecchio

print("\n[8] Un server vero: si avvia, risponde, si ferma")
# La porta la sceglie il test: quella che il server stampa nel log arriva
# solo quando il suo buffer si svuota (molti programmi non fanno flush del
# banner), e un test che aspetta quella riga misura il buffering del
# server, non il tool. Si lega una porta libera e si aspetta che risponda.
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    porta = str(s.getsockname()[1])
prima = tool.handler(azione="avvia",
                     comando=f"python -m http.server {porta} --bind 127.0.0.1",
                     attesa=2)
mid = re.search(r"\b(p\d+)\b", prima)
sid = mid.group(1) if mid else ""
check("il server ha un id", bool(sid), prima[:160])
risposta = ""
codice = 0
for _ in range(25):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/", timeout=2) as r:
            risposta = r.read(500).decode("utf-8", "replace")
            codice = r.status
        break
    except (urllib.error.URLError, OSError):
        time.sleep(0.4)
check("la pagina risponde davvero (HTTP 200)", codice == 200, risposta[:160])
check("e serve il contenuto della cartella (e' http.server)",
      "Directory listing" in risposta or "index" in risposta.lower(),
      risposta[:160])
letto = tool.handler(azione="leggi", id=sid, righe=10) if sid else ""
check("e il log del server e' leggibile anche a server acceso",
      bool(letto) and "in esecuzione" in letto, letto[:160])
fermato = tool.handler(azione="ferma", id=sid) if sid else ""
check("ferma chiude il server", "FERMATO" in fermato, fermato[:160])
check("e il processo risulta subito morto",
      processi.leggi(sid)["vivo"] is False)
# Un server ucciso ma con il figlio vivo tiene la porta occupata: si
# prova a connettersi, non si crede al messaggio. La chiusura del socket
# pero' non e' istantanea (il kernel lo libera quando il processo e'
# davvero stato raccolto: su Linux ci vuole qualche decimo di secondo),
# quindi si aspetta entro un tetto — quello che conta e' che la porta
# TORNI libera. Un orfano la tiene per tutta la finestra dei 5 secondi.
libera = False
for _ in range(20):
    try:
        with socket.create_connection(("127.0.0.1", int(porta)), timeout=0.4):
            time.sleep(0.25)
    except OSError:
        libera = True
        break
check("la porta torna libera dopo lo stop (nessun figlio rimasto)",
      libera, "la porta risponde ancora dopo 5s: un figlio e' rimasto vivo")

print("\n[9] All'uscita di Orchestra i processi si fermano")
ultimo = tool.handler(azione="avvia",
                      comando="python -c \"import time; time.sleep(60)\"",
                      attesa=0.5)
mid = re.search(r"\b(p\d+)\b", ultimo)
uid = mid.group(1) if mid else ""
vivi_prima = len([p for p in processi.elenca()["processi"] if p["vivo"]])
fermati = processi.ferma_tutti()
check("c'e' almeno un processo vivo da fermare", vivi_prima >= 1, str(vivi_prima))
check("ferma_tutti li ferma davvero", fermati >= 1, str(fermati))
check("e dopo non ne resta nessuno vivo",
      not any(p["vivo"] for p in processi.elenca()["processi"]))
if uid:
    check("il processo era quello", processi.leggi(uid)["vivo"] is False)

print("\n[10] La cartella di lavoro non aggira il confine della root")
# `cwd` era l'unico parametro che arrivava a `Path` senza passare da
# `_safe_path`: un comando in background poteva partire in una cartella
# fuori dalla root senza che all'utente comparisse nessuna domanda.
fuori_dir = tempfile.mkdtemp(prefix="proc-fuori-")
try:
    r = tool.handler(azione="avvia",
                     comando="python -c \"print('non-doveva-partire')\"",
                     cwd=fuori_dir, attesa=0.5)
    check("un cwd fuori dalla root viene negato",
          "NON AVVIATO" in r and "cartella" in r.lower(), r[:200])
    check("e il comando non e' stato eseguito",
          "non-doveva-partire" not in r, r[:200])
finally:
    shutil.rmtree(fuori_dir, ignore_errors=True)

dentro = tool.handler(azione="avvia",
                      comando="python -c \"print('cwd-dentro')\"",
                      cwd="orchestra", attesa=1)
check("un cwd relativo dentro la root parte",
      "cwd-dentro" in dentro and "NON AVVIATO" not in dentro, dentro[:200])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
