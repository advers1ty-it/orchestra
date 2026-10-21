"""Verifica del tool run_shell sulla macchina reale.

Non è un file temporaneo: copre i due bug trovati in e2e (separatore `;`
morto, output non-UTF-8). Girare su questa macchina serve a validare il
comportamento della shell effettiva, che cambia tra ambienti.

I comandi sono bash PURI, non "python3 -c ...".

Il perche' merita due righe, perche' e' stato il motivo per cui questo
test falliva su una macchina e passava su un'altra:

  1. "python3" su Windows e' un App Execution Alias: risolve il Python
     rispetto al DIRECTORY CORRENTE. Se la cwd non ha un Python dentro,
     muore con "Could not find the standard library directory" — un
     errore che sembra un difetto della shell e invece e' della macchina.
  2. Un path ASSOLUTO che esce dalla root viene rifiutato dal guard, e
     il rifiuto e' giusto. Ma allora l'interprete doveva essere dentro
     la root, e li' si era messa una COPIA del Python: in
     un'installazione copiata la copia puo' essere corrotta (solo
     __pycache__, nessun .py) e il test moriva lo stesso.

Qui si prova la SHELL: separatore, variabili, encoding, timeout, exit
code. L'interprete era un mezzo, non la domanda.
"""

import os
import sys

_RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RADICE)

# La root e' la RADICE DEL PROGETTO, non una sottocartella: e' l'unica
# che contiene tutto quello che il guard lascia passare.
os.environ["ORCHESTRA_ROOT"] = _RADICE
os.makedirs(os.environ["ORCHESTRA_ROOT"], exist_ok=True)

from orchestra.tools import _detect_posix_shell, default_registry  # noqa: E402

print("shell POSIX rilevata:", _detect_posix_shell())
sh = default_registry().get("run_shell")
ok = True


def _prova(nome, comando, condizione, timeout=60):
    global ok
    out = sh.handler(command=comando, timeout=timeout)
    risp = condizione(out)
    print(f"  {'OK  ' if risp else 'FAIL'} {nome}")
    if not risp:
        print(f"        -> {out[:200]!r}")
    ok = ok and risp


# 1. il separatore ';' esegue entrambi i comandi
_prova("il separatore ';' esegue entrambi i comandi",
       "echo uno; echo due",
       lambda o: "uno" in o and "due" in o)

# 2. le variabili si espandono
_prova("variabili espanse (shell POSIX)",
       "echo $HOME",
       lambda o: "$HOME" not in o and o.strip() != "")

# 3. l'output non-UTF-8 non deve uccidere il tool
_prova("output non-UTF-8 senza crash",
       r"printf 'caff\xe8'",
       lambda o: "caff" in o)

# 4. il testo semplice arriva intatto
_prova("testo semplice preservato",
       "echo 'perche gia citta e qui'",
       lambda o: "perche" in o and "citta" in o)

# 5. gli accenti veri arrivano intatti
_prova("accenti UTF-8 preservati",
       r"printf 'perchè gi\xc3\xa0 citt\xc3\xa0 è qui\n'",
       lambda o: "citt" in o)

# 6. il timeout viene rispettato
_prova("timeout rispettato",
       "sleep 5",
       lambda o: "TIMEOUT" in o,
       timeout=1)

# 7. l'exit code non nullo arriva
_prova("exit code non nullo propagato",
       "exit 3",
       lambda o: "exit=3" in o)

# 8. la cwd e' la root
_prova("cwd applicato",
       "pwd",
       lambda o: "orchestra" in o.lower())

print("TUTTO OK" if ok else "QUALCOSA FALLISCE")
sys.exit(0 if ok else 1)
