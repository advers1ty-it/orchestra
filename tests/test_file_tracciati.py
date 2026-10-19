"""Ogni modulo importato deve essere nel repo. Anche quelli con l'underscore.

Un ImportError su una macchina pulita non si vede mai in sviluppo: il
file c'e', l'import funziona, i test passano. Si vede solo sulla
macchina del tester, dopo l'update, dove il file non e' mai arrivato.

E' successo con orchestra/tools/_guard.py: cinque moduli lo
importavano, funzionava tutto in D:, ma il .gitignore aveva la regola
`_*.py` e il file non e' mai entrato in nessuna release. Tutte le
installazioni si sono rotte con `No module named 'orchestra.tools._guard'`.

Questo file controlla che ogni import relativo risolva su un file
tracciato da git. Costa un secondo e chiude la classe di difetti piu'
costosa: quella che passa tutti i test e rompe solo gli altri.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PKG = ROOT / "orchestra"

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Ogni import relativo risolve su un file tracciato da git")
tracciati = set(subprocess.run(
    ["git", "ls-files", "*.py"], capture_output=True, text=True,
    cwd=str(ROOT)).stdout.split())
moduli = sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)
check("moduli trovati", bool(moduli), "nessun .py sotto orchestra/")


def risolvi(modulo: Path, livello: int, nome: str | None):
    """Ritorna il/i Path candidati per un import relativo."""
    base = modulo.parent
    for _ in range(livello - 1):
        base = base.parent
    if not nome:
        return [base / "__init__.py"]
    # from .x.y import ...  ->  x/y.py oppure x/y/__init__.py
    rel = Path(*nome.split("."))
    return [base / (str(rel) + ".py"), base / rel / "__init__.py"]


mancanti = []
for mod in moduli:
    try:
        albero = ast.parse(mod.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        continue
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.ImportFrom) or not nodo.level:
            continue
        for cand in risolvi(mod, nodo.level, nodo.module):
            if cand.is_file():
                rel = cand.relative_to(ROOT).as_posix()
                if rel not in tracciati:
                    mancanti.append(f"{mod.relative_to(ROOT).as_posix()} -> {rel}")
                break
        else:
            if nodo.module:
                mancanti.append(
                    f"{mod.relative_to(ROOT).as_posix()} -> .{nodo.module} (file assente)")

check("import tutti tracciati", not mancanti, "; ".join(mancanti[:5]))

print("[2] Il gate importato da .tools e' quello vero (._guard)")
try:
    from orchestra.tools import set_permission_gate as spg_tools
    from orchestra.tools._guard import set_permission_gate as spg_guard
    check("stesso gate", spg_tools is spg_guard,
          ".tools ne ha uno diverso: i tool negano senza chiedere")
except Exception as e:  # noqa: BLE001
    check("stesso gate", False, str(e)[:80])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
