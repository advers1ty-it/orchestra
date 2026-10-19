"""Il permesso deve bloccare davvero, non sembrare che blocchi.

I test di permissions.py provano il gate da solo. Qui si prova il
percorso completo: un tool chiede, l'evento parte, la risposta torna, il
tool prosegue. Il buco pericoloso e' fra questi tre pezzi — un tool che
non chiede, un evento che non parte, una risposta che non torna: in
tutti e tre i casi l'agente scrive fuori e l'utente non se ne accorge.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


root = tempfile.mkdtemp(prefix="root-")
fuori = tempfile.mkdtemp(prefix="fuori-")
segreto = os.path.join(fuori, "nota.txt")
with open(segreto, "w", encoding="utf-8") as f:
    f.write("segreto")

os.environ["ORCHESTRA_ROOT"] = root
os.environ.pop("ORCHESTRA_HOME", None)

from orchestra import tools as T  # noqa: E402
from orchestra.permissions import Gate, Risposta  # noqa: E402
from orchestra.types import Tool  # noqa: E402

print("\n[1] Senza gate, fuori dalla root e' negato")
T.set_permission_gate(None)
try:
    T._safe_path(segreto)
    check("il percorso fuori viene negato", False, "e' passato")
except ValueError:
    check("il percorso fuori viene negato", True)
except PermissionError:
    check("il percorso fuori viene negato", True)

print("\n[2] Dentro la root passa sempre, anche senza gate")
dentro = os.path.join(root, "ok.txt")
check("il percorso dentro passa", str(T._safe_path("ok.txt")) == str(Path(dentro).resolve()))

print("\n[3] Il tool si ferma e aspetta la risposta")
eventi = []
gate = Gate(root=root, chiedi=None)


def chiedi(r):
    eventi.append(("domandato", r.percorso, r.azione))
    # risponde come farebbe la UI, da un altro thread
    def risponde():
        time.sleep(0.2)
        gate.rispondi(r.id, "una_volta")
    threading.Thread(target=risponde, daemon=True).start()
    while r.id not in gate._risposte:
        time.sleep(0.01)
    return gate._risposte[r.id]


gate.chiedi = chiedi
T.set_permission_gate(gate)

risultato = {}
threading.Thread(target=lambda: risultato.update(
    p=str(T._safe_path(segreto))), daemon=True).start()
# si controlla PRIMA che la risposta arrivi (il thread risponde dopo
# 0.2s): controllare dopo significherebbe misurare la risposta, non
# l'attesa
time.sleep(0.08)
check("il tool e' fermo finche' non rispondi",
      "p" not in risultato, str(risultato))
check("la domanda e' partita con il percorso giusto",
      eventi and eventi[0][1] == segreto, str(eventi))
time.sleep(0.4)
check("dopo la risposta il tool prosegue", "p" in risultato, str(risultato))
check("il percorso restituito e' quello giusto",
      risultato.get("p") == segreto, str(risultato.get("p")))

print("\n[4] Un percorso vietato non arriva mai a chiedere")
eventi.clear()
vietato = "C:\\Windows\\System32\\drivers\\etc\\hosts"
try:
    T._safe_path(vietato)
    check("il percorso vietato viene negato", False, "e' passato")
except PermissionError:
    check("il percorso vietato viene negato", True)
except ValueError:
    check("il percorso vietato viene negato", True)
check("nessuna domanda per un percorso vietato",
      not eventi, str(eventi))

print("\n[5] 'Mai' blocca anche quando il gate chiede")
gate2 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
T.set_permission_gate(gate2)
try:
    T._safe_path(segreto)
    check("con 'mai' il tool si ferma", False, "e' passato")
except PermissionError:
    check("con 'mai' il tool si ferma", True)
check("il rifiuto resta ricordato", gate2.stato()["negati"])

print("\n[6] Il benchmark non ha nessuno a cui chiedere: nega")
gate3 = Gate(root=root, chiedi=None)
T.set_permission_gate(gate3)
try:
    T._safe_path(segreto)
    check("senza canale si nega", False, "e' passato")
except PermissionError:
    check("senza canale si nega", True)

print("\n[7] run_shell eredita lo stesso vincolo")
# il percorso e' il vincolo reale: se l'agente usa la shell per
# arrivare dove non potrebbe, deve comunque chiedere. Verifichiamo che
# il controllo esista sul tool, non solo sulle funzioni di file.
# `tools` e' un pacchetto, non un file: i controlli stanno in file diversi
# (le guardie in _guard.py, run_shell nel suo modulo). Leggere tutti i
# file del pacchetto e verificare la proprieta' sul totale: il test
# controlla che la guardia ESISTA, non dove sta scritta.
_pkg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "orchestra", "tools")
sorgente = chr(10).join(
    open(os.path.join(_pkg, f), encoding="utf-8").read()
    for f in sorted(os.listdir(_pkg)) if f.endswith(".py")
)
check("_safe_path e' usata dai tool su file",
      sorgente.count("_safe_path(") >= 4, str(sorgente.count("_safe_path(")))
check("run_shell chiede anche lui",
      "_percorso_fuori" in sorgente and "chiedi_all_utente" in sorgente,
      "run_shell non chiede: il permesso si aggirerebbe con la shell")
check("il controllo della shell dichiara i suoi limiti",
      "non e' un sandbox" in sorgente,
      "un controllo che sembra totale e non lo e' e' peggio di nessuno")

T.set_permission_gate(None)
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(fuori, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
