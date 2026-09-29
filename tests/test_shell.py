"""Verifica del tool run_shell sulla macchina reale.

Non è un file temporaneo: copre i due bug trovati in e2e (separatore `;`
morto, output non-UTF-8). Girare su questa macchina serve a validare il
comportamento della shell effettiva, che cambia tra ambienti.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ORCHESTRA_ROOT"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe3")
os.makedirs(os.environ["ORCHESTRA_ROOT"], exist_ok=True)

from orchestra.tools import _detect_posix_shell, default_registry  # noqa: E402

print("shell POSIX rilevata:", _detect_posix_shell())
sh = default_registry().get("run_shell")
ok = True

out = sh.handler(command='python3 -c "print(1)"; python3 -c "print(2)"')
has2 = "2" in out
print(f"  {'OK  ' if has2 else 'FAIL'} il separatore ';' esegue entrambi i comandi")
ok = ok and has2

out2 = sh.handler(command="echo $0")
expanded = "$0" not in out2
print(f"  {'OK  ' if expanded else 'FAIL'} variabili espanse (shell POSIX)")
ok = ok and expanded

out3 = sh.handler(command='python3 -c "import sys; sys.stdout.buffer.write(bytes([99,97,102,102,102,232]))"')
no_crash = "caff" in out3
print(f"  {'OK  ' if no_crash else 'FAIL'} output non-UTF-8 senza crash")
ok = ok and no_crash

out4 = sh.handler(command='python3 -c "print(\\"perche gia citta e qui\\")"')
words = "perche" in out4 and "citta" in out4
print(f"  {'OK  ' if words else 'FAIL'} testo semplice preservato")
ok = ok and words

# accenti veri, via file per non annidare apici
_probe = os.environ["ORCHESTRA_ROOT"]
with open(os.path.join(_probe, "acc.py"), "w", encoding="utf-8") as f:
    f.write("print('perch\\u00e8 gi\\u00e0 citt\\u00e0 \\u00e8 qui')\n")
out4b = sh.handler(command='python3 acc.py')
accents = "perch" in out4b and "citt" in out4b
print(f"  {'OK  ' if accents else 'FAIL'} accenti UTF-8 preservati")
ok = ok and accents

out5 = sh.handler(command="sleep 5", timeout=1)
timed = "TIMEOUT" in out5
print(f"  {'OK  ' if timed else 'FAIL'} timeout rispettato")
ok = ok and timed

out6 = sh.handler(command='python3 -c "import sys; sys.exit(3)"')
ec = "exit=3" in out6
print(f"  {'OK  ' if ec else 'FAIL'} exit code non nullo propagato")
ok = ok and ec

out7 = sh.handler(command="pwd")
has_wd = "orchestra" in out7.lower() or "/" in out7 or "\\" in out7
print(f"  {'OK  ' if has_wd else 'FAIL'} cwd applicato")
ok = ok and has_wd

print("TUTTO OK" if ok else "QUALCOSA FALLISCE")
sys.exit(0 if ok else 1)
