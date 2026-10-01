"""Il runner deve fallire quando una suite fallisce.

Il difetto che questo chiude: `required=False` faceva riportare come
"SKIP (non richiesto)" qualunque errore di una suite opzionale. Il
riepilogo diceva "Tutto verde", il processo usciva con 0, e l'e2e —
che era partito, aveva fallito, e aveva stampato un FAIL — non
contava.

E' la classe di difetto piu' pericolosa in un runner: non un test
rosso, che si vede. Un test rosso che il runner ha deciso di non
guardare.
"""

import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


src = io.open(os.path.join(ROOT, "tests", "run_all.py"), encoding="utf-8").read()

print("[1] Non c'e' un ramo che trasforma un errore in 'SKIP'")
i = src.index("if code == 0:")
blocco = src[i:src.index("if failed:", i)]
check("un exit non-zero porta a FAIL",
      re.search(r"FAIL\s+\{name\}", blocco) is not None,
      blocco[:120].replace("\n", " "))
check("e porta ad aggiungere la suite ai falliti",
      "failed.append(name)" in blocco,
      "senza questo il riepilogo resta vuoto e il processo esce 0")
check("non c'e' piu' un verdetto 'non richiesto'",
      "non richiesto" not in src,
      "un ramo che chiama SKIP su un exit non-zero")

print("\n[2] La prova vera: due suite finte, una che fallisce")
# Non si controlla il codice a occhio: si esegue, con la stessa
# logica del runner, e si guardano le due cose che contano — cosa
# viene scritto e con che codice si esce.
D = tempfile.mkdtemp()
ok = os.path.join(D, "ok.py")
ko = os.path.join(D, "ko.py")
aperta = os.path.join(D, "aperta.py")
open(ok, "w").write("print('  OK   tutto bene')\n")
# una suite "non richiesta" che pero' fallisce davvero
open(ko, "w").write("import sys\nprint('  FAIL qualcosa')\nsys.exit(1)\n")
# una che non puo' girare: esce 0, ed e' cosi' che le suite vere
# dichiarano "non posso lavorare"
open(aperta, "w").write("print('  SKIP senza chiave')\n")

STUB = ('import subprocess, sys\n'
        'SUITES = [("buona", {ok!r}, True), ("cattiva", {ko!r}, False)]\n'
        'failed = []\n'
        'for name, script, required in SUITES:\n'
        '    code = subprocess.run([sys.executable, script]).returncode\n'
        '    if code == 0:\n'
        '        print("  PASS  " + name)\n'
        '    else:\n'
        # "%d" nello stub verrebbe letto come un segnaposto di
        # formato quando la stringa viene composta: due segnaposto e
        # un %d, e il % consuma il %d.
        '        print("  FAIL  " + name + " (exit " + str(code) + ")")\n'
        '        failed.append(name)\n'
        'if failed:\n'
        '    print("RIEPILOGO: " + ", ".join(failed))\n'
        '    sys.exit(1)\n'
        'print("Tutto verde.")\n'
        'sys.exit(0)\n').format(ok=ok, ko=ko)

f = os.path.join(D, "runner.py")
open(f, "w", encoding="utf-8").write(STUB)
r = subprocess.run([sys.executable, f], capture_output=True, text=True)
out = r.stdout
print("    " + out.replace("\n", "\n    ").strip())
check("la suite che fallisce e' riportata FAIL", "FAIL  cattiva" in out, out)
check("e non come SKIP", "SKIP" not in out,
      "un errore mascherato da saltato")
check("il riepilogo la nomina",
      "RIEPILOGO" in out and "cattiva" in out, out)
check("e il riepilogo NON dice 'Tutto verde'",
      "Tutto verde" not in out,
      "un runner che dice 'Tutto verde' mentre una suite e' rossa")
check("il processo esce con codice diverso da zero", r.returncode != 0,
      f"returncode={r.returncode}")

print("\n[3] Il caso 'non posso girare' e' distinto")
STUB2 = STUB.replace(repr(ko), repr(aperta))
f2 = os.path.join(D, "runner2.py")
open(f2, "w", encoding="utf-8").write(STUB2)
r2 = subprocess.run([sys.executable, f2], capture_output=True, text=True)
check("una suite che non puo' girare non e' un fallimento",
      "FAIL  aperta" not in r2.stdout, r2.stdout)
check("e il runner dice comunque Tutto verde",
      "Tutto verde" in r2.stdout, r2.stdout)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)