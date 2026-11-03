"""L'undo delle scritture: checkpoint prima, ripristino dopo.

Il difetto che questi controlli prevengono: un agente che sovrascrive un
file e non lascia modo di tornare indietro. Per un utente che non usa
git, "il modello ha sbagliato file" non deve significare "perso".
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

TMP = tempfile.mkdtemp(prefix="orchestra_annulla_")
PROGETTO = os.path.join(TMP, "progetto")
os.makedirs(PROGETTO)
os.environ["ORCHESTRA_HOME"] = os.path.join(TMP, "dati")
os.environ["ORCHESTRA_ROOT"] = PROGETTO

from orchestra import checkpoint, webapp  # noqa: E402
from orchestra.tools.edit_file import tool_edit_file  # noqa: E402
from orchestra.tools.write_file import tool_write_file  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def leggi(rel: str) -> str:
    with open(os.path.join(PROGETTO, rel), encoding="utf-8") as f:
        return f.read()


def scrivi(rel: str, testo: str) -> None:
    tool_write_file().handler(path=rel, content=testo)


def testo_edit(rel: str, trova: str, sostituisci: str) -> str:
    return tool_edit_file().handler(path=rel, trova=trova,
                                    sostituisci=sostituisci)


print("\n[1] Un file creato si annulla sparendo")
checkpoint.svuota()
scrivi("nuovo.txt", "prima versione")
check("il file c'e'", os.path.isfile(os.path.join(PROGETTO, "nuovo.txt")))
voce = webapp.OrchestraApp.annulla_modifica(object())
check("l'undo risponde", voce.get("azione_fatta") == "rimosso", str(voce))
check("il file non c'e' piu'",
      not os.path.exists(os.path.join(PROGETTO, "nuovo.txt")))


print("\n[2] Una sovrascrittura torna alla versione precedente")
checkpoint.svuota()
scrivi("storia.txt", "uno")
scrivi("storia.txt", "due")
check("il file ora dice due", leggi("storia.txt") == "due")
voce = webapp.OrchestraApp.annulla_modifica(object())
check("l'undo ripristina", voce.get("azione_fatta") == "ripristinato", str(voce))
check("il contenuto e' quello di prima", leggi("storia.txt") == "uno",
      leggi("storia.txt"))
webapp.OrchestraApp.annulla_modifica(object())
check("il secondo undo toglie la creazione",
      not os.path.exists(os.path.join(PROGETTO, "storia.txt")))


print("\n[3] Anche edit_file lascia un checkpoint")
checkpoint.svuota()
scrivi("edit.txt", "alpha beta")
esito = testo_edit("edit.txt", "beta", "gamma")
check("la modifica e' avvenuta", "gamma" in leggi("edit.txt"), esito)
webapp.OrchestraApp.annulla_modifica(object())
check("edit_file torna indietro", leggi("edit.txt") == "alpha beta",
      leggi("edit.txt"))


print("\n[4] Senza niente da annullare lo si dice")
checkpoint.svuota()
check("il registro e' vuoto", checkpoint.annulla_ultima() is None)
try:
    webapp.OrchestraApp.annulla_modifica(object())
    errore = ""
except ValueError as e:
    errore = str(e)
check("l'API distingue il vuoto dall'errore", "nessuna modifica" in errore, errore)


print("\n[5] Un file troppo grande non si annulla, e non salta indietro")
checkpoint.svuota()
grande = os.path.join(PROGETTO, "grande.bin")
with open(grande, "wb") as f:
    f.write(b"x" * (checkpoint.MAX_BYTE + 10))
scrivi("grande.bin", "piccolo")
check("la scrittura e' avvenuta", leggi("grande.bin") == "piccolo")
try:
    checkpoint.annulla_ultima()
    errore2 = ""
except RuntimeError as e:
    errore2 = str(e)
check("l'undo si ferma e spiega", "non e' annullabile" in errore2, errore2)
check("il file resta quello nuovo", leggi("grande.bin") == "piccolo")
check("non ha annullato una modifica piu' vecchia",
      checkpoint.annulla_ultima() is None)


print("\n[6] Il registro non cresce senza limite")
checkpoint.svuota()
for i in range(checkpoint.MAX_VOCI + 5):
    scrivi("molti.txt", f"v{i}")
check("tiene solo le ultime", len(checkpoint.storico(100)) <= checkpoint.MAX_VOCI,
      str(len(checkpoint.storico(100))))


shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
