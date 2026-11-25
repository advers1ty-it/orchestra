"""Il tool git: tre letture, un tetto, nessuna scrittura.

`status`, `diff_stat` e `log` devono dire la verita' sul repository senza
cambiarlo, e l'output tagliato deve dichiararsi. Commit e push non sono
azioni di questo tool: restano nella shell, dove il gate li chiede anche
quando il comando gira dentro la root. Il test usa un repository vero e
temporaneo, e una shell vera solo per l'ultimo controllo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

WORK = tempfile.mkdtemp(prefix="orch-git-")
HOME = tempfile.mkdtemp(prefix="orch-git-home-")
os.environ["ORCHESTRA_ROOT"] = WORK
os.environ["ORCHESTRA_HOME"] = HOME

from orchestra import piano as piano_mod  # noqa: E402
from orchestra import policy  # noqa: E402
from orchestra.permissions import Gate, Risposta  # noqa: E402
from orchestra.tools import (  # noqa: E402
    _PROFILI,
    default_registry,
    set_permission_gate,
)
from orchestra.tools import git as git_mod  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


if shutil.which("git") is None:
    print("SKIP: git non è installato")
    sys.exit(0)


def git(*argomenti: str) -> str:
    r = subprocess.run(
        ["git", *argomenti], cwd=WORK, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(argomenti)}: {r.stderr}")
    return r.stdout


git("init", "-q")
git("config", "user.email", "test@example.invalid")
git("config", "user.name", "Test")
with open(os.path.join(WORK, "base.txt"), "w", encoding="utf-8") as f:
    f.write("uno\n")
git("add", "-A")
git("commit", "-q", "-m", "primo commit")
with open(os.path.join(WORK, "base.txt"), "w", encoding="utf-8") as f:
    f.write("due\n")

r = default_registry()
t = r.get("git")
h = t.handler
set_permission_gate(None)

print("\n[1] Il tool e' registrato, e non e' un tool che scrive")
check("git e' registrato", "git" in r)
check("e' attivo", t in r.active)
check("e' in tutti i profili",
      all("git" in p for p in _PROFILI.values()),
      str({k: "git" in v for k, v in _PROFILI.items()}))
check("non e' nella lista dei tool che cambiano",
      "git" not in piano_mod.TOOL_CHE_CAMBIANO)
azioni = set(t.schema["properties"]["azione"]["enum"])
check("lo schema ha status, diff_stat e log",
      azioni == {"status", "diff_stat", "log"}, str(azioni))
check("limite e' nel contratto", "limite" in t.schema["properties"])

print("\n[2] status, diff --stat e log leggono il repository")
out = h(azione="status")
check("status mostra il branch", "## " in out, out[:200])
check("status mostra il file modificato", "base.txt" in out, out[:200])

out = h(azione="diff_stat")
check("diff_stat mostra il file", "base.txt" in out, out[:200])
check("diff_stat non e' vuoto", "nessuna differenza" not in out.lower(), out[:200])

out = h(azione="log")
check("log mostra il commit", "primo commit" in out, out[:200])
out = h(azione="log", limite=1)
check("log rispetta il limite", out.count("\n") <= 3, out)

print("\n[3] L'output viene tagliato, e il taglio si dichiara")
for i in range(30):
    with open(os.path.join(WORK, f"non_tracciato_{i:02d}.txt"), "w",
              encoding="utf-8") as f:
        f.write("x\n")
vecchio_tetto = git_mod.TETTO_USCITA
git_mod.TETTO_USCITA = 80
try:
    out = h(azione="status")
finally:
    git_mod.TETTO_USCITA = vecchio_tetto
check("il taglio e' dichiarato",
      "output troncato" in out and "caratteri in totale" in out, out[-220:])
check("l'output tagliato resta breve", len(out) < 500, str(len(out)))

print("\n[4] Commit e push non sono azioni del tool")
prima = git("rev-parse", "HEAD").strip()
out = h(azione="commit")
check("commit viene rifiutato", "sola lettura" in out and "conferma" in out, out)
out = h(azione="push")
check("push viene rifiutato", "sola lettura" in out and "conferma" in out, out)
check("HEAD non e' cambiato", git("rev-parse", "HEAD").strip() == prima)

print("\n[5] La shell chiede conferma per commit e push")
for cmd in ("git commit -m 'x'", "git -C repo commit", "git push",
            "git.exe push origin"):
    check(f"rischio: {cmd}", policy.rischio_operativo(cmd) is not None,
          str(policy.rischio_operativo(cmd)))
check("git status non chiede", policy.rischio_operativo("git status") is None)

chiamate = []


def chiedi(r):
    chiamate.append(r)
    return Risposta("una_volta")


gate = Gate(root=WORK, chiedi=chiedi)
check("dentro la root, senza forza, non si chiede",
      gate.chiedi_all_utente(WORK, "distruggere") is True)
chiamate.clear()
ok = gate.chiedi_all_utente(WORK, "distruggere", forza=True)
check("con forza si chiede anche dentro la root",
      ok is True and len(chiamate) == 1, f"ok={ok} chiamate={len(chiamate)}")
check("il motivo e' una conferma esplicita",
      bool(chiamate) and chiamate[0].motivo == "conferma esplicita",
      str(chiamate[0].motivo if chiamate else None))

print("\n[6] Dopo il si' della conferma, il commit parte davvero")
git("add", "-A")
gate2 = Gate(root=WORK, chiedi=lambda r: Risposta("una_volta"))
set_permission_gate(gate2)
try:
    shell = default_registry().get("run_shell")
    esito = shell.handler(command="git commit -m secondo")
finally:
    set_permission_gate(None)
check("la shell ha eseguito il commit", "exit=0" in esito, esito[:200])
check("il commit e' nella storia", "secondo" in git("log", "--oneline"))

set_permission_gate(None)
shutil.rmtree(WORK, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
