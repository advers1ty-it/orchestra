"""I permessi devono chiudere davvero, non sembrare chiusi.

Il pericolo di questo pezzo e' che funzioni in tutti i test e non
protegga niente: un agente che puo' scrivere in C:/Windows non e' un
agente, e nessuno se ne accorge finche' non e' troppo tardi.

Ogni test qui sotto prova una riga di codice di un utente ostile.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.permissions import Gate, Risposta  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


root = tempfile.mkdtemp(prefix="root-")
fuori = tempfile.mkdtemp(prefix="fuori-")
file_fuori = os.path.join(fuori, "segreto.txt")
with open(file_fuori, "w", encoding="utf-8") as f:
    f.write("contenuto")

print("\n[1] Dentro la root: nessuna domanda")
g = Gate(root=root)
check("un file nella root passa", g.valuta("nota.txt", "scrivere") == "concesso")
check("una sottocartella passa", g.valuta("a/b/c.txt", "scrivere") == "concesso")
check("il percorso assoluto nella root passa",
      g.valuta(os.path.join(root, "x.txt"), "scrivere") == "concesso")

print("\n[2] Il traversal non aggira la root")
# il caso classico: "../" per uscire. _safe_path lo blocca gia', ma il
# gate non deve dipendere da quello.
g2 = Gate(root=root)
check("../ non ottiene il consenso",
      g2.valuta("../" + os.path.basename(fuori), "leggere") in ("chiedi", "negato"),
      g2.valuta("../" + os.path.basename(fuori), "leggere"))
check("un percorso fuori chiede",
      g2.valuta(file_fuori, "leggere") == "chiedi")

print("\n[3] I percorsi sensibili non sono autorizzabili")
g3 = Gate(root=root)
for p in ("C:/Windows/System32/drivers/etc/hosts",
          "C:/Program Files/una cosa/x.dll",
          "/etc/passwd", "/bin/ls", "/System/Library/x"):
    esito = g3.valuta(p, "leggere")
    if os.name == "nt" and p.startswith("/"):
        continue  # su Windows quei path non sono sensibili perche' non esistono
    check(f"negato: {p}", esito == "negato", esito)

print("\n[4] Chiavi e credenziali vietate ovunque")
g4 = Gate(root=root)
vietati = [os.path.join(fuori, ".env"),
           os.path.join(fuori, "sub", ".ssh", "id_rsa"),
           os.path.join(fuori, ".aws", "credentials")]
for p in vietati:
    check(f"negato: {os.path.basename(p)}", g4.valuta(p, "leggere") == "negato",
          g4.valuta(p, "leggere"))

print("\n[5] 'Una volta' non lascia traccia")
chiamate = []


def chiedi_una(r):
    chiamate.append(r)
    return Risposta("una_volta")


g5 = Gate(root=root, chiedi=chiedi_una)
ok1 = g5.chiedi_all_utente(file_fuori, "leggere")
ok2 = g5.chiedi_all_utente(file_fuori, "leggere")
check("la prima volta e' concessa", ok1 is True)
check("la seconda volta e' concessa", ok2 is True)
check("ha chiesto due volte", len(chiamate) == 2, str(len(chiamate)))
check("non resta memoria del consenso",
      g5.valuta(file_fuori, "leggere") == "chiedi")

print("\n[6] 'Per sessione' concede una volta sola")
g6 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
check("prima: concesso", g6.chiedi_all_utente(file_fuori, "leggere") is True)
check("seconda: concesso senza chiedere",
      g6.chiedi_all_utente(file_fuori, "leggere") is True)
check("valuta() dice concesso", g6.valuta(file_fuori, "leggere") == "concesso")
check("ha chiesto una volta sola", g6.stato()["sessione"], str(g6.stato()))

print("\n[7] 'Mai' nega e ricorda")
g7 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("prima: negato", g7.chiedi_all_utente(file_fuori, "leggere") is False)
check("seconda: negato senza chiedere",
      g7.chiedi_all_utente(file_fuori, "leggere") is False)
check("il consenso e' sparito dalla lista", not g7.stato()["sessione"])
check("il rifiuto e' ricordato", g7.stato()["negati"], str(g7.stato()["negati"]))

print("\n[8] Una risposta inesistente non concede niente")
g8 = Gate(root=root, chiedi=lambda r: Risposta("per_sempre_eroico"))
check("risposta sconosciuta = negato",
      g8.chiedi_all_utente(file_fuori, "leggere") is False)
g8b = Gate(root=root, chiedi=lambda r: Risposta(""))
check("risposta vuota = negato",
      g8b.chiedi_all_utente(file_fuori, "leggere") is False)

print("\n[9] Se nessuno puo' rispondere, si nega")
g9 = Gate(root=root, chiedi=None)
check("senza canale di conferma si nega",
      g9.chiedi_all_utente(file_fuori, "leggere") is False)


def chiedi_che_esplode(r):
    raise RuntimeError("il canale e' morto")


g9b = Gate(root=root, chiedi=chiedi_che_esplode)
check("se la domanda fallisce si nega",
      g9b.chiedi_all_utente(file_fuori, "leggere") is False)

print("\n[9b] Un canale rotto si dichiara, non si nasconde")
# Il caso peggiore non e' negare per errore: e' negare per errore
# SENZA DIRE NIENTE. L'utente vede un rifiuto e pensa che l'agente
# abbia deciso cosi'. Succede se un AttributeError nel canale viene
# trattato come una risposta.
import io  # noqa: E402
import contextlib  # noqa: E402


def chiedi_rompe_sul_metodo(r):
    # esattamente il bug reale: si chiama un metodo che non esiste
    return r.session.emit("permission_request", {})


g9c = Gate(root=root, chiedi=lambda r: (_ for _ in ()).throw(
    AttributeError("'Session' object has no attribute 'emit'")))
buf = io.StringIO()
with contextlib.redirect_stderr(buf):
    esito = g9c.chiedi_all_utente(file_fuori, "leggere")
check("l'errore del canale porta a negare", esito is False)
check("ma viene dichiarato", "[permessi]" in buf.getvalue()
      and "AttributeError" in buf.getvalue(),
      repr(buf.getvalue()[:80]))

print("\n[10] Il permesso di sessione scade")
import orchestra.permissions as P  # noqa: E402

vecchio = P.SESSIONE_SECONDI
P.SESSIONE_SECONDI = 0.2
try:
    g10 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
    g10.chiedi_all_utente(file_fuori, "leggere")
    check("subito dopo, ancora concesso",
          g10.valuta(file_fuori, "leggere") == "concesso")
    time.sleep(0.35)
    check("dopo la scadenza chiede di nuovo",
          g10.valuta(file_fuori, "leggere") == "chiedi",
          g10.valuta(file_fuori, "leggere"))
finally:
    P.SESSIONE_SECONDI = vecchio

print("\n[11] La domanda aspetta davvero la risposta")
risposta_arrivata = threading.Event()


def chiedi_lenta(r):
    # simula la UI: arriva la risposta dopo un momento
    def arriva():
        time.sleep(0.15)
        g11.rispondi(r.id, "una_volta")
        risposta_arrivata.set()
    threading.Thread(target=arriva, daemon=True).start()
    return g11._risposte[r.id]


g11 = Gate(root=root, chiedi=None)
# il percorso vero: chiedi() deve poter rispondere da un altro thread
canale = {}


def chiedi_reale(r):
    def attende():
        t0 = time.time()
        while r.id not in canale and time.time() - t0 < 3:
            time.sleep(0.01)
        canale[r.id] = Risposta("una_volta")
    threading.Thread(target=attende, daemon=True).start()
    while r.id not in canale:
        time.sleep(0.01)
    return canale[r.id]


g12 = Gate(root=root, chiedi=chiedi_reale)
check("il consenso arriva da un altro thread",
      g12.chiedi_all_utente(file_fuori, "leggere") is True)

print("\n[12] Revocare un permesso")
g13 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
g13.chiedi_all_utente(file_fuori, "leggere")
check("prima di revocare e' concesso", g13.valuta(file_fuori, "leggere") == "concesso")
g13.revoca(file_fuori)
check("dopo la revoca chiede di nuovo",
      g13.valuta(file_fuori, "leggere") == "chiedi",
      g13.valuta(file_fuori, "leggere"))

print("\n[13] Il permesso su una cartella vale per quello che c'e' dentro")
# Concedere "Documenti" senza questo non serve: il primo `ls
# Documenti/2024` chiede di nuovo, e l'utente preme "questa volta" a
# ogni livello di profondita'. Il permesso che hai dato e' su una
# cartella, non su un indirizzo esatto.
cart = os.path.join(fuori, "progetto")
os.makedirs(os.path.join(cart, "src", "deep"), exist_ok=True)
g13 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
check("la cartella non e' concessa all'inizio",
      g13.valuta(cart, "leggere") == "chiedi")
g13.chiedi_all_utente(cart, "leggere")
check("dopo il permesso e' concessa", g13.valuta(cart, "leggere") == "concesso")
check("una sottocartella e' concessa",
      g13.valuta(os.path.join(cart, "src"), "leggere") == "concesso",
      g13.valuta(os.path.join(cart, "src"), "leggere"))
check("due livelli sotto e' ancora concesso",
      g13.valuta(os.path.join(cart, "src", "deep"), "leggere") == "concesso",
      g13.valuta(os.path.join(cart, "src", "deep"), "leggere"))
check("ma un fratello no",
      g13.valuta(os.path.join(fuori, "altro"), "leggere") == "chiedi")
# e la revoca della cartella revoca anche i figli
g13.revoca(cart)
check("revocando la cartella, i figli tornano da chiedere",
      g13.valuta(os.path.join(cart, "src", "deep"), "leggere") == "chiedi")

print("\n[14] Un percorso SENSIBILE dentro una cartella concessa resta negato")
# Se concedessi /home e l'agente chiedesse /home/.ssh/id_rsa, la
# concessione non deve aprire il cassetto: i sensibili si negano
# SEMPRE, prima di guardare qualsiasi concessione.
g14 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
home = os.path.join(fuori, "home")
os.makedirs(home, exist_ok=True)
g14.chiedi_all_utente(home, "leggere")
check("la cartella e' concessa", g14.valuta(home, "leggere") == "concesso")
nascosto = os.path.join(home, ".ssh", "id_rsa")
check("ma dentro .ssh resta negato",
      g14.valuta(nascosto, "leggere") == "negato",
      g14.valuta(nascosto, "leggere"))

shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(fuori, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
