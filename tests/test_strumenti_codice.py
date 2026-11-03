"""I due tool che mancavano: leggere la struttura e girare i test.

`analisi_python` risponde a "dov'e' definito" senza leggere il corpo del
file; `run_tests` trova il comando che il progetto usa invece di
indovinarlo. Qui si verifica il comportamento reale, non la presenza dei
nomi: un file di prova con simboli, import e chiamate, e una cartella di
prova con una suite che passa e una che fallisce.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra.tools.analisi_python import tool_analisi_python  # noqa: E402
from orchestra.tools.esegui_test import _rileva, tool_run_tests  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


WORK = tempfile.mkdtemp(prefix="orch-strumenti-")
os.environ["ORCHESTRA_ROOT"] = WORK

ESEMPIO = os.path.join(WORK, "esempio.py")
with open(ESEMPIO, "w", encoding="utf-8") as f:
    f.write('''"""Un modulo di prova."""
import os
from pathlib import Path as P


class Contenitore:
    def metodo(self, x):
        return len(x)

    class Interna:
        def profonda(self):
            pass


def saluta(nome: str) -> str:
    def aiuto():
        return "!"
    return "ciao " + nome + aiuto()


def main():
    c = Contenitore()
    c.metodo(["a", "b"])
    print(saluta("mondo"))
''')

analisi = tool_analisi_python().handler

print("== analisi_python: la struttura, senza il corpo ==")

simboli = analisi(path="esempio.py")
check("trova le classi con la riga", "classe class Contenitore" in simboli,
      simboli)
check("trova le funzioni con la firma",
      "def saluta(nome: str) -> str" in simboli, simboli)
check("mostra le funzioni annidate", "[in saluta]" in simboli, simboli)
check("mostra le classi annidate", "Interna" in simboli
      and "[in Contenitore]" in simboli, simboli)

imports = analisi(path="esempio.py", cosa="import")
check("elenca gli import", "import os" in imports, imports)
check("elenca i from-import con l'alias",
      "from pathlib import Path as P" in imports, imports)

chiamate = analisi(path="esempio.py", cosa="chiamate")
check("elenca le chiamate", "print(...)" in chiamate, chiamate)
check("dice in che funzione sta la chiamata",
      "in main" in chiamate, chiamate)

filtrate = analisi(path="esempio.py", cosa="chiamate", nome="metodo")
check("il filtro per nome funziona", "metodo(...)" in filtrate
      and "print(" not in filtrate, filtrate)

usi = analisi(path="esempio.py", cosa="usi", nome="Contenitore")
check("trova gli usi del nome", "usi di Contenitore" in usi, usi)

check("un file valido passa il controllo di sintassi",
      "sintassi valida" in analisi(path="esempio.py", cosa="sintassi"))

ROTTO = os.path.join(WORK, "rotto.py")
with open(ROTTO, "w", encoding="utf-8") as f:
    f.write("def x(:\n    pass\n")
esito = analisi(path="rotto.py")
check("un file rotto riporta riga e motivo",
      "ERRORE DI SINTASSI" in esito and "rotto.py:1" in esito, esito)

ALTRO = os.path.join(WORK, "stile.js")
with open(ALTRO, "w", encoding="utf-8") as f:
    f.write("function x() {}\n")
esito = analisi(path="stile.js")
check("un file non Python lo dice invece di restituire vuoto",
      "FORMATO NON SUPPORTATO" in esito, esito)

check("un path inesistente lo dice", "NON ESISTE" in analisi(path="nope.py"))
check("senza path chiede il path", "Quale file" in analisi())

print("\n== run_tests: il comando lo detta il progetto ==")

radice = tempfile.mkdtemp(prefix="orch-runner-")
# 1) pytest
open(os.path.join(radice, "pyproject.toml"), "w").close()
os.makedirs(os.path.join(radice, "tests"))
comando, perche = _rileva(__import__("pathlib").Path(radice), "")
check("riconosce pytest", comando == "python -m pytest -q", comando)
check("sa dire perche'", "pytest" in perche, perche)

# 2) Node con script test
open(os.path.join(radice, "pyproject.toml"), "w").close()
os.makedirs(os.path.join(radice, "node_modules"), exist_ok=True)
import json  # noqa: E402
with open(os.path.join(radice, "package.json"), "w", encoding="utf-8") as f:
    json.dump({"scripts": {"test": "vitest run"}}, f)
open(os.path.join(radice, "pnpm-lock.yaml"), "w").close()
import shutil  # noqa: E402
shutil.rmtree(os.path.join(radice, "tests"))
os.remove(os.path.join(radice, "pyproject.toml"))
comando, _ = _rileva(__import__("pathlib").Path(radice), "")
check("riconosce pnpm test dal lockfile", comando == "pnpm test", comando)

# 3) Rust
radice2 = tempfile.mkdtemp(prefix="orch-rust-")
open(os.path.join(radice2, "Cargo.toml"), "w").close()
check("riconosce cargo", _rileva(__import__("pathlib").Path(radice2), "")[0]
      == "cargo test")

# 4) Niente: non si inventa
radice3 = tempfile.mkdtemp(prefix="orch-vuoto-")
comando, perche = _rileva(__import__("pathlib").Path(radice3), "")
check("senza suite non inventa un comando", comando == "", comando)

print("\n== run_tests: esegue davvero e riporta l'esito ==")

# Una suite vera nella root finta: scrive un file solo se arriva in fondo,
# cosi' si vede che e' stata eseguita e non solo costruita la stringa.
PROGETTO = tempfile.mkdtemp(prefix="orch-suite-")
os.makedirs(os.path.join(PROGETTO, "tests"))
with open(os.path.join(PROGETTO, "tests", "run_all.py"), "w",
          encoding="utf-8") as f:
    f.write(
        "import pathlib, sys\n"
        "print('PASS 2  FAIL 0')\n"
        "pathlib.Path('eseguito.txt').write_text('si')\n"
        "sys.exit(0)\n"
    )

os.environ["ORCHESTRA_ROOT"] = PROGETTO
runner = tool_run_tests().handler
esito = runner()
check("il comando usato e' quello del progetto",
      "comando: python tests/run_all.py" in esito, esito)
check("l'output della suite arriva", "PASS 2  FAIL 0" in esito, esito)
check("la suite e' stata eseguita davvero",
      os.path.exists(os.path.join(PROGETTO, "eseguito.txt")), esito)

# Una suite che fallisce deve restituire il codice di uscita, non "ok".
SUITE_ROTTA = tempfile.mkdtemp(prefix="orch-suite-rotta-")
os.makedirs(os.path.join(SUITE_ROTTA, "tests"))
with open(os.path.join(SUITE_ROTTA, "tests", "run_all.py"), "w",
          encoding="utf-8") as f:
    f.write("import sys\nprint('FAIL 1')\nsys.exit(1)\n")
os.environ["ORCHESTRA_ROOT"] = SUITE_ROTTA
esito = runner()
check("un fallimento resta un fallimento", "exit=1" in esito, esito)
check("il messaggio del test arriva", "FAIL 1" in esito, esito)

# Comando esplicito: vince sul rilevamento.
os.environ["ORCHESTRA_ROOT"] = PROGETTO
esito = runner(comando="python tests/run_all.py")
check("un comando esplicito viene usato", "comando indicato da te" in esito,
      esito)

# Nessuna suite: si dice, non si inventa.
os.environ["ORCHESTRA_ROOT"] = radice3
esito = runner()
check("senza suite lo dice", "NESSUNA SUITE RICONOSCIUTA" in esito, esito)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
