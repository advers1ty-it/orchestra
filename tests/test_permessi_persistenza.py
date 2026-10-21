"""I permessi "sempre" devono sopravvivere al riavvio del server.

Il bug: "sempre" era tenuto in un set in memoria, dentro il Gate. Il
Gate vive sul processo del server. Al riavvio il set e' vuoto, e un
permesso che l'utente aveva concesso per sempre tornava a chiedere —
ogni volta, per sempre, anche se l'utente aveva gia' premuto "sempre".

E' il difetto peggiore di questo tipo: non e' che il permesso e' troppo
permessivo, e' che non c'e'. L'utente crede di aver concesso qualcosa
che e' sparito, e il sistema non lo dice.

Qui sotto il permesso viene salvato su disco e ricaricato in un Gate
nuovo, che e' esattamente quello che capita quando il server riparte.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.permissions import Gate, Risposta  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


# Ogni test gira con una ORCHESTRA_HOME sua: il file dei permessi e'
# condiviso, e due test che lo scrivessero insieme si romperebbero a
# vicenda. E' la stessa regola del server di test.
HOME = tempfile.mkdtemp(prefix="perm-home-")
os.environ["ORCHESTRA_HOME"] = HOME

root = tempfile.mkdtemp(prefix="root-")
fuori = tempfile.mkdtemp(prefix="fuori-")

# Ogni sezione usa un percorso DIVERSO. I permessi sono persistenti:
# riusare lo stesso percorso fra la sezione "sempre" e quella "mai"
# significherebbe che la seconda parte da un percorso gia' concesso, e
# il test misurerebbe il test, non il codice.
def _nuovo(nome):
    p = os.path.join(fuori, nome)
    with open(p, "w", encoding="utf-8") as f:
        f.write("roba")
    return p


target = _nuovo("lavoro.txt")
target_1 = _nuovo("solo-una-volta.txt")
target_2 = _nuovo("solo-sessione.txt")
target_3 = _nuovo("mai.txt")
target_4 = _nuovo("revocato.txt")


def gate_sempre():
    return Gate(root=root, chiedi=lambda r: Risposta("sempre"))


def gate_mai():
    return Gate(root=root, chiedi=lambda r: Risposta("mai"))


print("\n[1] 'sempre' resta concesso dopo il riavvio")
g = gate_sempre()
check("prima chiede", g.valuta(target, "leggere") == "chiedi")
g.chiedi_all_utente(target, "leggere")
check("dopo 'sempre' e' concesso", g.valuta(target, "leggere") == "concesso")

# il riavvio: un Gate nuovo, che non ha niente in memoria
g2 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("dopo il riavvio e' ancora concesso", g2.valuta(target, "leggere") == "concesso",
      g2.valuta(target, "leggere"))
check("e non chiede un'altra volta", g2.chiedi_all_utente(target, "leggere") is True)

print("\n[2] 'sempre' vale anche per quello che c'e' dentro")
g = gate_sempre()
cartella = os.path.join(fuori, "sotto")
os.makedirs(cartella, exist_ok=True)
g.chiedi_all_utente(cartella, "leggere")
g2 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("il file dentro la cartella concessa passa",
      g2.valuta(os.path.join(cartella, "x.txt"), "leggere") == "concesso",
      g2.valuta(os.path.join(cartella, "x.txt"), "leggere"))

print("\n[3] 'mai' resta negato dopo il riavvio")
g = gate_mai()
check("prima chiede", g.valuta(target_3, "leggere") == "chiedi")
g.chiedi_all_utente(target_3, "leggere")
check("dopo 'mai' e' negato", g.valuta(target_3, "leggere") == "negato")
g2 = Gate(root=root, chiedi=lambda r: Risposta("sempre"))
check("dopo il riavvio e' ancora negato", g2.valuta(target_3, "leggere") == "negato",
      g2.valuta(target_3, "leggere"))
check("e non si lascia convincere", g2.chiedi_all_utente(target_3, "leggere") is False)

print("\n[4] 'una volta' NON deve diventare 'sempre'")
g = Gate(root=root, chiedi=lambda r: Risposta("una_volta"))
g.chiedi_all_utente(target_1, "leggere")
g2 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("una volta non viene salvata", g2.valuta(target_1, "leggere") == "chiedi",
      g2.valuta(target_1, "leggere"))

print("\n[5] 'sessione' NON deve diventare 'sempre'")
g = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
g.chiedi_all_utente(target_2, "leggere")
g2 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("la sessione non viene salvata", g2.valuta(target_2, "leggere") == "chiedi",
      g2.valuta(target_2, "leggere"))

print("\n[6] La revoca survive al riavvio")
g = gate_sempre()
g.chiedi_all_utente(target_4, "leggere")
check("prima e' concesso", g.valuta(target_4, "leggere") == "concesso")
g.revoca(target_4)
g2 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("dopo la revoca torna a chiedere", g2.valuta(target_4, "leggere") == "chiedi",
      g2.valuta(target_4, "leggere"))

print("\n[7] Il file dei permessi esiste ed e' leggibile")
files = [f for f in os.listdir(HOME) if "perm" in f.lower()]
check("c'e' un file dei permessi", bool(files), str(os.listdir(HOME)))
if files:
    try:
        dati = json.load(open(os.path.join(HOME, files[0]), encoding="utf-8"))
        check("e' JSON valido", isinstance(dati, dict), type(dati).__name__)
        check("e ha le sezioni attese",
              all(k in dati for k in ("sempre", "negati")), str(list(dati.keys())))
    except Exception as e:  # noqa: BLE001
        check("e' JSON valido", False, f"{type(e).__name__}: {e}")

print("\n[8] Un file corrotto non blocca il server")
# il file viene scritto a meta' (scatta la corrente, muore il processo)
for f in os.listdir(HOME):
    if "perm" in f.lower():
        with open(os.path.join(HOME, f), "w", encoding="utf-8") as fh:
            fh.write("{questo non e' json")
g3 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("il gate si costruisce lo stesso", g3 is not None)
check("e chiede come se non ci fosse nulla", g3.valuta(target, "leggere") == "chiedi",
      g3.valuta(target, "leggere"))

print("\n[9] I permessi restano separati fra installazioni")
# un'altra ORCHESTRA_HOME = un'altra installazione = un altro file
altro = tempfile.mkdtemp(prefix="perm-altro-")
vecchio = os.environ["ORCHESTRA_HOME"]
os.environ["ORCHESTRA_HOME"] = altro
g4 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
check("l'altra installazione non eredita nulla", g4.valuta(target, "leggere") == "chiedi",
      g4.valuta(target, "leggere"))
os.environ["ORCHESTRA_HOME"] = vecchio

print("\n" + "=" * 60)
print(f"  {len(PASS)} passati, {len(FAIL)} falliti")
if FAIL:
    print("  FALLITI: " + ", ".join(FAIL))
shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(fuori, ignore_errors=True)
sys.exit(1 if FAIL else 0)
