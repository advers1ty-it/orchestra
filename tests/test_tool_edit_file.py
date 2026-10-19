"""edit_file: la sostituzione esatta, e il root che tiene.

Il tool e' nato come script nella sottocartella `orchestra/tools/`, e
per mesi nessuno l'ha visto: `orchestra/tools.py` (modulo) e
`orchestra/tools/` (cartella) hanno lo stesso nome, e senza `__init__.py`
Python ignora la cartella. `import orchestra.tools.edit_file` falliva con
`__path__ attribute not found`, quindi il tool non era importabile e non
poteva essere registrato.

Questo test verifica le due cose che contano:

- la sostituzione e' esatta e conteggiata (non "qualcosa e' cambiato")
- il root e' un confine anche qui, come per read_file e write_file: se
  `_safe_path` non fosse applicata, edit_file sarebbe un altro modo di
  uscire dal progetto, esattamente come run_shell lo era prima della sua
  guardia.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_edit")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)

from orchestra.tools import default_registry  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


h = default_registry().get("edit_file").handler
P = os.path.join(WORK, "_edit.txt")


def scrivi(testo):
    with open(P, "w", encoding="utf-8") as f:
        f.write(testo)


def leggi():
    with open(P, encoding="utf-8") as f:
        return f.read()


print("\n[1] Il tool c'e' ed e' importabile")
r = default_registry()
check("edit_file e' registrato", "edit_file" in r)
check("e' attivo", r.get("edit_file") in r.active)
check("ha uno schema con trova/sostituisci",
      set(r.get("edit_file").schema["required"]) == {"path", "trova", "sostituisci"},
      str(r.get("edit_file").schema["required"]))

print("\n[2] La sostituzione e' esatta")
scrivi("riga uno\nriga due\nriga uno\n")
out = h(path=P, trova="riga uno", sostituisci="RIGA UNO")
check("dice cosa ha fatto", "1" in out, out)
check("ha cambiato solo la prima", leggi() == "RIGA UNO\nriga due\nriga uno\n", leggi())

scrivi("aaa\naaa\naaa\n")
h(path=P, trova="aaa", sostituisci="bbb", all=True)
check("all=true cambia tutte", leggi() == "bbb\nbbb\nbbb\n", leggi())

scrivi("x\nx\nx\nx\n")
h(path=P, trova="x", sostituisci="y", count=2)
check("count=N rispetta N", leggi() == "y\ny\nx\nx\n", leggi())

# La sostituzione con lunghezza diversa e' il caso in cui gli indici si
# spostano: sostituire "aa" con "b" su "aaaa" deve dare "bb", non "baa".
scrivi("aaaa\n")
h(path=P, trova="aa", sostituisci="b", all=True)
check("lunghezze diverse non corrompono", leggi() == "bb\n", leggi())

print("\n[3] Gli errori si dicono, non si tace")
check("file inesistente", "NON ESISTE" in h(path=os.path.join(WORK, "nope.txt"),
                                            trova="a", sostituisci="b"))
check("stringa assente", "CORRISPONDENZA" in h(path=P, trova="ZZZ", sostituisci="q"))
check("trova vuoto", "ERRORE" in h(path=P, trova="", sostituisci="q"))
check("directory", "DIRECTORY" in h(path=WORK, trova="a", sostituisci="b"))

print("\n[4] dry_run non scrive")
scrivi("prima\n")
out = h(path=P, trova="prima", sostituisci="dopo", dry_run=True)
check("dice di non aver scritto", "DRY-RUN" in out, out)
check("il file e' intatto", leggi() == "prima\n", leggi())

print("\n[5] Il root e' un confine anche qui")
for bad in ["../../../Windows/win.ini", "..\\..\\secrets.txt", "/etc/passwd"]:
    try:
        h(path=bad, trova="a", sostituisci="b")
        check(f"edit_file blocca {bad[:30]}", False, "ha scritto fuori dal root!")
    except ValueError as e:
        check(f"edit_file blocca {bad[:30]}", True)
    except Exception as e:  # noqa: BLE001
        check(f"edit_file blocca {bad[:30]}", False, f"tipo inatteso: {type(e).__name__}")

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
