"""Il riavvio del server: la riga giusta, e chi la esegue.

Il difetto da evitare e' silenzioso. `[sys.executable] + sys.argv` sembra
la risposta ovvia, ma con l'avvio vero (`python -m orchestra.cli web ...`)
`sys.argv[0]` e' il file del modulo: rilanciarlo come script fa morire il
processo sugli import relativi, e il server non torna su. Qui si guarda la
riga costruita nei tre casi (modulo, eseguibile, file singolo) e che
`riavvia()` la passi davvero a `os.execv`.

Nessun processo viene sostituito: `os.execv` e' una funzione finta.
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import orchestra.riavvio as r  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


print("\n[1] l'avvio vero (python -m ...) si rilancia come modulo")
# `sys.argv[0]` e' orchestra/cli.py, ma la riga che ha avviato il processo
# e' `-m orchestra.cli`: l'unica che sa ricostruire il pacchetto.
cmd = r.comando_riavvio(
    ["orchestra/cli.py", "web", "--port", "8737", "--no-browser"],
    "C:/Python/python.exe", frozen=False,
    orig_argv=["C:/Python/python.exe", "-m", "orchestra.cli", "web",
               "--port", "8737", "--no-browser"])
check("l'interprete e' quello di adesso", cmd[0] == "C:/Python/python.exe",
      str(cmd))
check("il modulo resta un modulo", cmd[1:3] == ["-m", "orchestra.cli"],
      str(cmd))
check("e gli argomenti del server restano", cmd[3:] == ["web", "--port",
                                                       "8737", "--no-browser"],
      str(cmd))
check("non si esegue il file del modulo come script",
      "orchestra/cli.py" not in cmd, str(cmd))

print("\n[2] un eseguibile impacchettato rilancia se stesso")
cmd = r.comando_riavvio(["C:/Program Files/Orchestra/Orchestra.exe", "web"],
                        "C:/Program Files/Orchestra/Orchestra.exe",
                        frozen=True, orig_argv=["ignorato"])
check("e' l'eseguibile, non python", cmd == [
    "C:/Program Files/Orchestra/Orchestra.exe", "web"], str(cmd))

print("\n[3] senza orig_argv si ricostruisce il modulo da __main__")
# Python 3.9 non ha `sys.orig_argv`: il nome del modulo in esecuzione e'
# comunque nel `__spec__` di `__main__`, ed e' quello che serve.
vero = sys.modules.get("__main__")
finto = types.ModuleType("finto_main")
finto.__spec__ = types.SimpleNamespace(name="orchestra.cli")
sys.modules["__main__"] = finto
try:
    cmd = r.comando_riavvio(["x.py", "web"], "python", frozen=False,
                            orig_argv=[])
finally:
    if vero is None:
        sys.modules.pop("__main__", None)
    else:
        sys.modules["__main__"] = vero
check("il modulo ricostruito e' orchestra.cli",
      cmd == ["python", "-m", "orchestra.cli", "web"], str(cmd))

print("\n[4] un programma avviato come file resta un file")
cmd = r.comando_riavvio(["script.py", "web"], "python", frozen=False,
                        orig_argv=[])
check("senza un modulo si tiene argv", cmd == ["python", "script.py", "web"],
      str(cmd))

print("\n[5] riavvia() passa la riga a os.execv, e non torna")
chiamate = []
vero_comando = r.comando_riavvio
vero_execv = r.os.execv
r.comando_riavvio = lambda argv=None: ["python-finto", "-m", "orchestra.cli"]
r.os.execv = lambda exe, argv: chiamate.append((exe, list(argv)))
try:
    r.riavvia()
finally:
    r.comando_riavvio = vero_comando
    r.os.execv = vero_execv
check("execv chiamato una volta", len(chiamate) == 1, str(chiamate))
check("con l'eseguibile e la stessa riga",
      chiamate == [("python-finto", ["python-finto", "-m",
                                     "orchestra.cli"])], str(chiamate))
check("e senza un secondo processo da aspettare", len(chiamate) == 1,
      str(chiamate))

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
