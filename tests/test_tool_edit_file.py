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
import orchestra.checkpoint as checkpoint_mod  # noqa: E402
import orchestra.scrittura as scrittura_mod  # noqa: E402

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
check("lo schema accetta una sola sostituzione o un batch",
      set(r.get("edit_file").schema["required"]) == {"path"}
      and "modifiche" in r.get("edit_file").schema["properties"],
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
    except (ValueError, PermissionError) as e:
        check(f"edit_file blocca {bad[:30]}", True)
    except Exception as e:  # noqa: BLE001
        check(f"edit_file blocca {bad[:30]}", False, f"tipo inatteso: {type(e).__name__}")

print("\n[6] Batch: piu' sostituzioni, un solo checkpoint e una scrittura")
scrivi("alfa\nbeta\ngamma\n")
conta = {"checkpoint": 0, "scritture": 0}
cp_orig = checkpoint_mod.registra
sc_orig = scrittura_mod.scrivi_bytes


def cp_conta(*a, **k):
    conta["checkpoint"] += 1
    return cp_orig(*a, **k)


def sc_conta(*a, **k):
    conta["scritture"] += 1
    return sc_orig(*a, **k)


checkpoint_mod.registra = cp_conta
scrittura_mod.scrivi_bytes = sc_conta
try:
    out = h(path=P, modifiche=[
        {"trova": "alfa", "sostituisci": "ALFA"},
        {"trova": "beta", "sostituisci": "BETA"},
    ])
finally:
    checkpoint_mod.registra = cp_orig
    scrittura_mod.scrivi_bytes = sc_orig
check("il batch dice quante modifiche", "2 modifiche" in out, out)
check("il batch applica tutte le voci", leggi() == "ALFA\nBETA\ngamma\n", leggi())
check("un solo checkpoint", conta["checkpoint"] == 1, str(conta))
check("una sola scrittura", conta["scritture"] == 1, str(conta))

print("\n[7] Il batch e' atomico: se una voce non c'e', non scrive")
scrivi("uno\ndue\n")
conta = {"checkpoint": 0, "scritture": 0}
checkpoint_mod.registra = cp_conta
scrittura_mod.scrivi_bytes = sc_conta
try:
    out = h(path=P, modifiche=[
        {"trova": "uno", "sostituisci": "1"},
        {"trova": "TRE", "sostituisci": "3"},
    ])
finally:
    checkpoint_mod.registra = cp_orig
    scrittura_mod.scrivi_bytes = sc_orig
check("dice quale voce manca", "modifica 2" in out and "NESSUNA CORRISPONDENZA" in out, out)
check("il file e' intatto", leggi() == "uno\ndue\n", leggi())
check("niente checkpoint", conta["checkpoint"] == 0, str(conta))
check("niente scrittura", conta["scritture"] == 0, str(conta))

print("\n[8] Batch: all/count per voce, dry_run e CRLF")
scrivi("x x x\n")
h(path=P, modifiche=[
    {"trova": "x", "sostituisci": "y", "count": 2},
    {"trova": "x", "sostituisci": "z"},
])
check("count e poi prima occorrenza", leggi() == "y y z\n", leggi())

scrivi("a\na\n")
out = h(path=P, modifiche=[{"trova": "a", "sostituisci": "b", "all": True}],
        dry_run=True)
check("dry_run batch non scrive", "DRY-RUN" in out and "nessuna scrittura" in out, out)
check("dry_run batch lascia il file", leggi() == "a\na\n", leggi())

with open(P, "wb") as f:
    f.write(b"uno\r\ndue\r\n")
h(path=P, modifiche=[{"trova": "uno\ndue", "sostituisci": "UNO\nDUE"}])
with open(P, "rb") as f:
    crlf = f.read()
check("batch con CRLF e stringa LF", crlf == b"UNO\r\nDUE\r\n", repr(crlf))

print("\n[9] Batch: i due modi non si mescolano")
scrivi("a\n")
out = h(path=P, trova="a", sostituisci="b",
        modifiche=[{"trova": "a", "sostituisci": "c"}])
check("mescolare e' errore", "ERRORE" in out and "non entrambi" in out, out)
out = h(path=P, modifiche=[{"trova": "", "sostituisci": "x"}])
check("trova vuoto nel batch e' errore", "ERRORE" in out and "modifica 1" in out, out)
out = h(path=P, modifiche=[{"trova": "a", "sostituisci": "b"}], all=True)
check("all fuori dal batch e' errore", "ERRORE" in out, out)
out = h(path=P, modifiche=[])
check("lista vuota e' errore", "ERRORE" in out, out)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
