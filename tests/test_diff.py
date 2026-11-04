"""Il diff multi-file: le modifiche del turno, con le righe cambiate.

L'undo sa tornare indietro, ma non sa dire cosa e' cambiato: per vederlo
bisognava aprire i file. Qui si controlla che il confine del turno sia
quello giusto (le scritture di prima non entrano), che il diff contenga
le righe vere, e che un file nuovo sia distinto da uno modificato.
"""

from __future__ import annotations

import os
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

TMP = tempfile.mkdtemp(prefix="orchestra_diff_")
PROGETTO = os.path.join(TMP, "progetto")
os.makedirs(PROGETTO)
os.environ["ORCHESTRA_HOME"] = os.path.join(TMP, "dati")
os.environ["ORCHESTRA_ROOT"] = PROGETTO

from orchestra import checkpoint  # noqa: E402
from orchestra.tools.write_file import tool_write_file  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def scrivi(rel: str, testo: str) -> None:
    tool_write_file().handler(path=rel, content=testo)


def per_percorso(mods):
    return {m["percorso"]: m for m in mods}


print("\n== prima del turno il diff e' vuoto ==")

checkpoint.svuota()
scrivi("vecchio.txt", "una riga\n")
check("senza turno segnato non c'e' niente da mostrare",
      checkpoint.modifiche_turno() == [])

print("\n== il diff parte dal turno segnato ==")

checkpoint.nuovo_turno()
scrivi("nuovo.txt", "riga uno\nriga due\n")
mods = checkpoint.modifiche_turno()
check("una sola modifica nel turno", len(mods) == 1, str(mods))
m = mods[0]
check("il percorso e' relativo", m["percorso"] == "nuovo.txt", m["percorso"])
check("il file nuovo e' marcato come tale", m["stato"] == "nuovo", m["stato"])
check("il diff contiene la riga aggiunta", "+riga uno" in m["diff"], m["diff"])
check("conta le righe aggiunte", m["aggiunte"] == 2, str(m["aggiunte"]))
check("non conta righe tolte", m["tolte"] == 0, str(m["tolte"]))

print("\n== una modifica mostra prima e dopo ==")

scrivi("nuovo.txt", "riga uno\nriga DUE\n")
tutte = checkpoint.modifiche_turno()
check("ora ci sono due voci (due scritture)", len(tutte) == 2, str(tutte))
mods = per_percorso(tutte)
m = mods.get("nuovo.txt")
check("la seconda modifica e' 'modificato'", m and m["stato"] == "modificato",
      str(m))
check("il diff ha la riga tolta", "-riga due" in (m or {}).get("diff", ""))
check("il diff ha la riga aggiunta",
      "+riga DUE" in (m or {}).get("diff", ""))
check("aggiunte e tolte tornano",
      (m or {}).get("aggiunte") == 1 and (m or {}).get("tolte") == 1,
      str(m))

print("\n== un nuovo turno azzera il confine, non la storia ==")

checkpoint.nuovo_turno()
check("il turno appena aperto e' vuoto", checkpoint.modifiche_turno() == [])
scrivi("dopo.txt", "x\n")
mods = checkpoint.modifiche_turno()
check("solo la scrittura del nuovo turno", len(mods) == 1, str(mods))
check("ed e' dopo.txt", mods[0]["percorso"] == "dopo.txt", str(mods))
check("l'undo conosce ancora le scritture di prima",
      len(checkpoint.storico()) >= 2, str(len(checkpoint.storico())))

print("\n== una riscrittura identica non inventa modifiche ==")

scrivi("dopo.txt", "x\n")
m = [x for x in checkpoint.modifiche_turno()
     if x["percorso"] == "dopo.txt"][-1]
check("nessuna riga cambiata", m["aggiunte"] == 0 and m["tolte"] == 0,
      str(m))

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
