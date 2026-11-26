"""Un fatto aggiunto in fondo non deve incollarsi all'ultimo.

`Memoria.appendi` scriveva la riga senza guardare come finiva il file.
Su un `memory.md` la cui ultima riga non aveva l'a capo finale — capita
a chi lo edita a mano, e a un file troncato — il fatto nuovo finiva
sulla stessa riga del precedente: `fatti()` ne vedeva uno solo con due
fatti dentro, e il secondo non si trovava piu' ne' con `elimina` ne'
con la ricerca.

Niente rete e niente memoria vera: ogni caso ha il suo file temporaneo.
"""

from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Prima di importare orchestra: `memoria()` e' un singleton.
os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch-test-appendi-")

from orchestra import memoria as memoria_mod            # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def memoria_con(contenuto: str) -> memoria_mod.Memoria:
    """Una memoria che nasce da un file scritto a mano."""
    cartella = tempfile.mkdtemp(prefix="orch-app-")
    percorso = os.path.join(cartella, "memory.md")
    with open(percorso, "w", encoding="utf-8", newline="") as f:
        f.write(contenuto)
    return memoria_mod.Memoria(percorso=percorso)


def contenuto(m: memoria_mod.Memoria) -> str:
    """Il file, con gli a capo normalizzati a "\n".

    La lettura di default traduce `\r\n` in `\n`: i controlli sul testo
    devono valere uguale su Windows e su Linux, o il test passerebbe
    solo sulla macchina di chi l'ha scritto.
    """
    with open(m.percorso, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
print("\n[1] appendi su un file senza a capo finale")

m = memoria_con("# Memoria di Orchestra\n\n## Fatti\n\n- Primo fatto")
m.appendi("- Secondo fatto\n")
testo = contenuto(m)

check("il fatto nuovo si apre una riga sua",
      "- Primo fatto\n- Secondo fatto" in testo, repr(testo))
check("i due fatti non sono incollati",
      "Primo fatto- Secondo fatto" not in testo, repr(testo))
check("i fatti letti sono due",
      m.fatti() == ["Primo fatto", "Secondo fatto"], str(m.fatti()))
check("la cache resta allineata al file",
      m.leggi() == testo, repr(m.leggi()))

# L'ultimo fatto si deve poter cancellare da solo: prima esisteva solo
# come pezzo della riga del precedente.
check("il fatto aggiunto si elimina da solo",
      m.elimina("Secondo fatto") is True
      and m.fatti() == ["Primo fatto"], str(m.fatti()))

# ---------------------------------------------------------------------------
print("\n[2] Il percorso vero: `aggiungi` su un file senza a capo finale")

m2 = memoria_con("# Memoria di Orchestra\n\n## Fatti\n\n- Primo fatto")
check("aggiungi riesce", m2.aggiungi("Secondo fatto") is True)
check("i due fatti restano distinti",
      m2.fatti() == ["Primo fatto", "Secondo fatto"], str(m2.fatti()))
check("nel file stanno su due righe",
      "- Primo fatto\n- Secondo fatto" in contenuto(m2),
      repr(contenuto(m2)))
check("il nuovo si elimina da solo",
      m2.elimina("Secondo fatto") is True
      and m2.fatti() == ["Primo fatto"], str(m2.fatti()))

# La sezione Importanti segue lo stesso percorso di append.
m3 = memoria_con(
    "## Fatti\n\n- Primo fatto\n\n## Importanti\n\n- Regola scritta a mano")
m3.aggiungi("Regola nuova importante", importante=True)
check("anche fra gli Importanti il fatto non si incolla",
      m3.importanti() == ["Regola scritta a mano",
                          "Regola nuova importante"],
      str(m3.importanti()))

# ---------------------------------------------------------------------------
print("\n[3] I casi che non devono cambiare")

m4 = memoria_con("# Memoria di Orchestra\n\n## Fatti\n\n- Primo fatto\n")
m4.appendi("- Secondo fatto\n")
check("con l'a capo finale non si aggiunge una riga vuota",
      "- Primo fatto\n- Secondo fatto\n" in contenuto(m4),
      repr(contenuto(m4)))
check("e non ci sono righe vuote fra i fatti",
      "- Primo fatto\n\n- Secondo fatto" not in contenuto(m4),
      repr(contenuto(m4)))

m5 = memoria_con("")
m5.appendi("- Primo fatto\n")
check("su un file vuoto non si apre con una riga vuota",
      contenuto(m5) == "- Primo fatto\n", repr(contenuto(m5)))

m6 = memoria_con("## Fatti\r\n\r\n- Primo fatto\r\n")
m6.appendi("- Secondo fatto\n")
check("un file con a capo Windows non prende una riga vuota",
      "- Primo fatto\n\n- Secondo fatto" not in contenuto(m6),
      repr(contenuto(m6)))
check("e i fatti sono due",
      m6.fatti() == ["Primo fatto", "Secondo fatto"], str(m6.fatti()))

# Il testo che arriva con un a capo davanti non ne prende un altro:
# `aggiungi` lo usa quando deve aprire una sezione nuova.
m7 = memoria_con("## Fatti\n\n- Primo fatto")
m7.appendi("\n## Importanti\n\n- Regola\n")
check("un blocco che inizia con l'a capo non ne prende un secondo",
      "Primo fatto\n## Importanti" in contenuto(m7)
      and "Primo fatto\n\n## Importanti" not in contenuto(m7),
      repr(contenuto(m7)))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
