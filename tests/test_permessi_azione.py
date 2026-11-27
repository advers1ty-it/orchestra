"""I permessi valgono per una coppia (percorso, azione), non per il solo percorso.

Due difetti P0 dell'audit:

- un consenso dato per leggere un percorso autorizzava anche a scriverlo o a
  eseguire comandi che lo toccavano;
- quando il gate approvava un percorso, i controlli su `.env` e sugli altri
  file protetti venivano saltati.

Questi test provano i due difetti dal punto in cui l'utente li vede: il tool
`write_file`, la shell, e un comando che nomina due percorsi esterni.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HOME = tempfile.mkdtemp(prefix="perm-azione-home-")
os.environ["ORCHESTRA_HOME"] = HOME

root = tempfile.mkdtemp(prefix="perm-azione-root-")
fuori = tempfile.mkdtemp(prefix="perm-azione-fuori-")
os.environ["ORCHESTRA_ROOT"] = root

from orchestra import tools as T  # noqa: E402
from orchestra.permissions import Gate, Risposta  # noqa: E402
from orchestra.tools._guard import _safe_path, verifica_comando  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def nuovo(nome, contenuto="contenuto"):
    p = os.path.join(fuori, nome)
    with open(p, "w", encoding="utf-8") as f:
        f.write(contenuto)
    return p


def leggi(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


wf = T.default_registry().get("write_file").handler

print("\n[1] Il consenso su una cartella vale solo per la stessa azione")
cartella = os.path.join(fuori, "cartella")
os.makedirs(os.path.join(cartella, "src"), exist_ok=True)
g = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
g.chiedi_all_utente(cartella, "leggere")
check("la lettura della cartella e' concessa",
      g.valuta(cartella, "leggere") == "concesso")
check("la lettura di un figlio e' concessa",
      g.valuta(os.path.join(cartella, "src"), "leggere") == "concesso")
check("la scrittura nella stessa cartella NON e' concessa",
      g.valuta(cartella, "scrivere") == "chiedi",
      g.valuta(cartella, "scrivere"))
check("la scrittura di un figlio NON e' concessa",
      g.valuta(os.path.join(cartella, "src"), "scrivere") == "chiedi",
      g.valuta(os.path.join(cartella, "src"), "scrivere"))

print("\n[2] write_file non riusa un consenso di lettura")
target = nuovo("solo-lettura.txt", "originale")
eventi = []


def chiedi(r):
    eventi.append((r.percorso, r.azione))
    # La lettura si concede per la sessione; la scrittura si nega.
    return Risposta("sessione" if r.azione == "leggere" else "mai")


g2 = Gate(root=root, chiedi=chiedi)
T.set_permission_gate(g2)
_safe_path(target, "leggere")
check("la lettura e' stata concessa",
      g2.valuta(target, "leggere") == "concesso")
try:
    wf(path=target, content="NUOVO")
    check("write_file non scrive con il solo consenso di lettura", False,
          "ha scritto")
except PermissionError:
    check("write_file non scrive con il solo consenso di lettura", True)
check("il file e' rimasto com'era", leggi(target) == "originale", leggi(target))
check("write_file ha chiesto l'azione 'scrivere'",
      eventi and eventi[-1][1] == "scrivere", str(eventi))

print("\n[3] Un consenso di esecuzione non autorizza write_file")
target2 = nuovo("solo-esecuzione.txt", "originale")
eventi2 = []


def chiedi2(r):
    eventi2.append((r.percorso, r.azione))
    return Risposta("sessione" if r.azione == "eseguire" else "mai")


g3 = Gate(root=root, chiedi=chiedi2)
T.set_permission_gate(g3)
check("l'esecuzione e' stata concessa",
      g3.chiedi_all_utente(target2, "eseguire") is True)
try:
    wf(path=target2, content="NUOVO")
    check("write_file non riusa il consenso di esecuzione", False,
          "ha scritto")
except PermissionError:
    check("write_file non riusa il consenso di esecuzione", True)
check("il file e' rimasto com'era",
      leggi(target2) == "originale", leggi(target2))
check("write_file ha chiesto 'scrivere', non 'eseguire'",
      eventi2 and eventi2[-1][1] == "scrivere", str(eventi2))

print("\n[4] Un consenso di lettura non autorizza la shell")
target3 = nuovo("shell-dopo-lettura.txt")
eventi3 = []


def chiedi3(r):
    eventi3.append((r.percorso, r.azione))
    return Risposta("sessione" if r.azione == "leggere" else "mai")


g4 = Gate(root=root, chiedi=chiedi3)
T.set_permission_gate(g4)
_safe_path(target3, "leggere")
comando = "cat " + target3
esito = verifica_comando(comando)
check("la shell non parte con il consenso di lettura",
      esito is not None and "permesso non concesso" in esito,
      str(esito))
check("la shell ha chiesto l'azione 'eseguire'",
      any(a == "eseguire" for _, a in eventi3), str(eventi3))

print("\n[5] Il gate che approva il percorso non apre .env")
class GateFinto:
    """Approvatore totale: simula un gate che dice sempre si'."""

    def __init__(self):
        self.chiamate = []

    def chiedi_all_utente(self, percorso, azione, dettaglio="", **kwargs):
        self.chiamate.append((percorso, azione))
        return True


finto = GateFinto()
T.set_permission_gate(finto)
env_fuori = os.path.join(fuori, ".env")
try:
    _safe_path(env_fuori, "leggere")
    check("_safe_path nega .env fuori dalla root", False, "e' passato")
except PermissionError as e:
    check("_safe_path nega .env fuori dalla root", "protetto" in str(e), str(e))
check("_safe_path non ha nemmeno chiesto il permesso",
      not finto.chiamate, str(finto.chiamate))

finto.chiamate.clear()
esito = verifica_comando("cat " + env_fuori)
check("la shell blocca .env anche se il gate approva il percorso",
      esito is not None and "BLOCCATO" in esito
      and "protetto" in esito, str(esito))
check("il gate era stato interpellato prima del controllo del segreto",
      bool(finto.chiamate), str(finto.chiamate))

print("\n[6] Un comando con due percorsi esterni chiede per entrambi")
p1 = nuovo("multi-uno.txt")
p2 = nuovo("multi-due.txt")
comando = f"cat {p1} {p2}"
chiamate = []


def chiedi_multi(r):
    chiamate.append(r.percorso)
    return Risposta("una_volta")


g5 = Gate(root=root, chiedi=chiedi_multi)
T.set_permission_gate(g5)
esito = verifica_comando(comando)
check("il comando con entrambi i percorsi autorizzati passa",
      esito is None, str(esito))
check("ha chiesto per entrambi i percorsi", len(chiamate) == 2,
      str(chiamate))
attesi = {str(Path(p).resolve()) for p in (p1, p2)}
check("i percorsi chiesti sono quelli giusti",
      {str(Path(p).resolve()) for p in chiamate}
      == attesi, str(chiamate))

print("\n[6b] Se il secondo percorso viene negato, il comando non parte")
chiamate2 = []


def chiedi_multi2(r):
    chiamate2.append(r.percorso)
    return Risposta("una_volta" if len(chiamate2) == 1 else "mai")


g6 = Gate(root=root, chiedi=chiedi_multi2)
T.set_permission_gate(g6)
esito = verifica_comando(comando)
check("il comando viene fermato quando il secondo percorso e' negato",
      esito is not None and "permesso non concesso" in esito, str(esito))
check("ha chiesto anche il secondo percorso", len(chiamate2) == 2,
      str(chiamate2))

print("\n[7] I vecchi permessi senza azione valgono solo per la lettura")
legacy_home = tempfile.mkdtemp(prefix="perm-azione-legacy-")
vecchio_home = os.environ["ORCHESTRA_HOME"]
os.environ["ORCHESTRA_HOME"] = legacy_home
legacy_target = nuovo("legacy.txt")
with open(os.path.join(legacy_home, "permessi.json"), "w",
          encoding="utf-8") as f:
    json.dump({"sempre": [legacy_target], "negati": []}, f)
g7 = Gate(root=root, chiedi=None)
check("il vecchio 'sempre' concede ancora la lettura",
      g7.valuta(legacy_target, "leggere") == "concesso")
check("il vecchio 'sempre' non concede la scrittura",
      g7.valuta(legacy_target, "scrivere") == "chiedi",
      g7.valuta(legacy_target, "scrivere"))
check("il vecchio 'sempre' non concede l'esecuzione",
      g7.valuta(legacy_target, "eseguire") == "chiedi",
      g7.valuta(legacy_target, "eseguire"))

print("\n[8] Un 'sempre' per la scrittura non autorizza la lettura")
os.environ["ORCHESTRA_HOME"] = legacy_home
target8 = nuovo("persistente-azione.txt")
g8 = Gate(root=root, chiedi=lambda r: Risposta("sempre"))
check("la scrittura viene concessa",
      g8.chiedi_all_utente(target8, "scrivere") is True)
g9 = Gate(root=root, chiedi=None)
check("dopo il riavvio la scrittura resta concessa",
      g9.valuta(target8, "scrivere") == "concesso",
      g9.valuta(target8, "scrivere"))
check("ma la lettura non e' stata concessa per trascinamento",
      g9.valuta(target8, "leggere") == "chiedi",
      g9.valuta(target8, "leggere"))

os.environ["ORCHESTRA_HOME"] = vecchio_home
T.set_permission_gate(None)
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(fuori, ignore_errors=True)
shutil.rmtree(legacy_home, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
