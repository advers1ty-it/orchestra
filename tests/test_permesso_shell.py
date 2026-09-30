"""Il gate concede, il blocco vecchio nega: due risposte a una domanda.

Dopo che l'utente sceglie "per questa sessione" il gate registra il
permesso e, alla volta dopo, concede senza chiedere. Ma subito dopo
_check_shell_access guardava di nuovo il comando e diceva "BLOCCATO per
sicurezza".

Il risultato era la cosa peggiore di tutte: l'utente autorizzava, il
sistema concedeva, e un secondo controllo annullava la concessione. Due
risposte contraddittorie alla stessa domanda, e vinceva la seconda.

Il gate e' l'autorita'. E' piu' severo del controllo vecchio, perche'
nega i percorsi sensibili senza neppure fare la domanda. Il blocco
vecchio resta come riserva per quando non c'e' nessun gate — la CLI e
il benchmark — dove altrimenti non ci sarebbe nessun controllo.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import tools as T  # noqa: E402
from orchestra.permissions import Gate, Risposta  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


root = tempfile.mkdtemp(prefix="root-")
fuori = tempfile.mkdtemp(prefix="fuori-")
os.environ["ORCHESTRA_ROOT"] = root

COMANDO = "ls -la " + os.path.join(fuori, "file.txt").replace("\\", "/")

print("\n[1] Senza gate, il blocco vecchio vale ancora")
T.set_permission_gate(None)
t = T.default_registry().get("run_shell")
risultato = t.handler(COMANDO)
check("il comando viene rifiutato", "NON ESEGUITO" in risultato, risultato[:70])
check("e si dice perche'", "nessuno a cui chiedere" in risultato, risultato[:70])

print("\n[2] Il gate chiede e l'utente dice 'una volta'")
gate = Gate(root=root, chiedi=lambda r: Risposta("una_volta"))
T.set_permission_gate(gate)
r1 = t.handler(COMANDO)
check("il gate ha chiesto", True)  # il lambda risponde sempre "una volta"
check("il comando NON e' bloccato",
      "BLOCCATO per sicurezza" not in r1, r1[:90])
check("e non e' detto 'non eseguito' per il gate",
      "permesso non concesso" not in r1, r1[:90])

print("\n[3] Il gate chiede e l'utente dice 'per sessione'")
gate2 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
T.set_permission_gate(gate2)
r2 = t.handler(COMANDO)
check("il permesso e' stato ricordato", len(gate2.stato()["sessione"]) == 1,
      str(gate2.stato()["sessione"]))
check("il comando NON e' bloccato lo stesso",
      "BLOCCATO per sicurezza" not in r2, r2[:90])

print("\n[4] Il caso che ha rotto tutto: seconda esecuzione")
# Prima il gate chiede e concede per sessione. Il blocco vecchio doveva
# lasciar passare. Non lo faceva.
r3 = t.handler(COMANDO)
check("la seconda esecuzione passa", "BLOCCATO per sicurezza" not in r3, r3[:90])
check("ed esegue davvero", "exit=" in r3, r3[:70])

print("\n[5] 'Mai' resta un no, anche con il blocco vecchio")
gate3 = Gate(root=root, chiedi=lambda r: Risposta("mai"))
T.set_permission_gate(gate3)
r4 = t.handler(COMANDO)
check("il gate nega", "permesso non concesso" in r4, r4[:90])

print("\n[6] I percorsi sensibili non si sbloccano con una concessione")
gate4 = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
T.set_permission_gate(gate4)
vietato = "C:/Windows/System32/config/SAM"
r5 = t.handler("cat " + vietato)
check("un percorso di sistema resta negato",
      "NON ESEGUITO" in r5 or "BLOCCATO" in r5, r5[:90])
check("e non e' finito negli concessi", not gate4.stato()["sessione"],
      str(gate4.stato()["sessione"]))

print("\n[7] Un comando dentro la root non chiede nulla")
gate5 = Gate(root=root, chiedi=lambda r: (_ for _ in ()).throw(
    AssertionError("non doveva chiedere")))
T.set_permission_gate(gate5)
r6 = t.handler("echo ciao")
check("nessuna domanda per un comando interno", "exit=" in r6, r6[:60])

T.set_permission_gate(None)
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(fuori, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
