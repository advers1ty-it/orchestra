"""Il modello non sapeva di poter chiedere: le istruzioni glielo impedivano.

Cinque bug in fila, tutti sulla stessa catena, e questo era il
sottoscritto. Il gate funzionava, la domanda partiva, l'utente la
vedeva e rispondeva — e il modello, dal canto suo, rispondeva "non posso
accedere, i miei strumenti sono limitati alla cartella di lavoro".

Perche'? Perche' il SYSTEM_PROMPT non diceva una parola sui permessi e
la descrizione dei tool annunciava "Path relativo alla root di lavoro".
Il modello leggeva esattamente quello che gli davamo: gli strumenti
sono relativi e la root e' un muro. Non stava eseguendo, stava
riportando.

Le due cose da correggere non sono il gate — quello funzionava — ma
quello che il modello crede di poter fare.

- il prompt di sistema ora dice che i percorsi ASSOLUTI si usano, che
  la domanda la fa lo strumento e lui non deve fare nulla, e che cosa
  fare quando l'utente nega (rispettare, non riprovare con un altro
  strumento)
- le descrizioni di read_file, write_file e run_shell non dicono piu'
  "relativo alla root"

Una riga che vale piu' di tutto il resto: "non dire mai 'non posso
accedere a <cartella>' senza averci provato". Il rifiuto anticipato
e' la cosa piu' costosa che un agente puo' fare, perche' si presenta
come una constatazione e non come una prova.

Verificato sul server vero, con il messaggio dell'utente: parte la
domanda per C:\\Users\\adver\\TraceAppNew, risposta "per questa
sessione", e l'agente legge package.json (LuoghiDiStoria 2.0.0) e
README.md (React Native 0.86, New Architecture, React 19).

Anche list_dir su una cartella autorizzata fuori dalla root non
morreva piu' con ValueError: faceva x.relative_to(ROOT) su un percorso
che non e' sotto la root. Il permesso concesso non bastava a nulla
perche' il listing crashava subito dopo.
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


print("[1] Il prompt di sistema deve parlare dei permessi")
p = T.SYSTEM_PROMPT
check("dice che i percorsi assoluti si usano", "ASSOLUT" in p.upper())
check("dice che la domanda la fa lo strumento", "domanda" in p.lower())
check("elenca le scelte", all(s in p for s in ("una volta", "sessione", "sempre")))
check("vieta il rifiuto anticipato", "senza averci provato" in p)

print("\n[2] Le descrizioni dei tool non possono far pensare che esista solo la root")
# Non basta che la frase "relativo alla root" non ci sia PIOLA: se il
# modello legge "Percorso relativo alla root" e nient'altro, crede che
# la root sia l'unico posto. Deve comparire la parola ASSOLUTO, che e'
# quello che gli serve sapere.
reg = T.default_registry()
for nome in ("read_file", "write_file", "run_shell", "list_dir"):
    spec = reg.get(nome).schema
    testo = " ".join(str(v) for v in spec.get("properties", {}).values())
    check(f"{nome}: dice che esistono anche i percorsi assoluti",
          "ASSOLUT" in testo.upper(), testo[:80])

print("\n[3] list_dir su una cartella FUORI dalla root autorizzata")
root = tempfile.mkdtemp(prefix="root-")
fuori = tempfile.mkdtemp(prefix="fuori-")
esterno = os.path.join(fuori, "progetto")
os.makedirs(os.path.join(esterno, "src"))
os.makedirs(os.path.join(esterno, ".bundle"))
with open(os.path.join(esterno, "package.json"), "w", encoding="utf-8") as f:
    f.write("{}")
os.environ["ORCHESTRA_ROOT"] = root

gate = Gate(root=root, chiedi=lambda r: Risposta("sessione"))
T.set_permission_gate(gate)
gate.chiedi_all_utente(esterno, "leggere")

r = reg.get("list_dir").handler(esterno)
check("il listing non muore con ValueError", "ValueError" not in r, r[:90])
check("mostra i file", "package.json" in r, r[:160])
check("e le directory, estese", os.path.join(esterno, ".bundle") in r, r[:200])

r2 = reg.get("list_dir").handler(os.path.join(esterno, ".bundle"))
check("e si puo' riaprire una sottocartoria", "ValueError" not in r2, r2[:90])

print("\n[4] Dentro la root resta tutto come prima")
T.set_permission_gate(None)
dentro = os.path.join(root, "sotto")
os.makedirs(dentro)
with open(os.path.join(dentro, "a.txt"), "w", encoding="utf-8") as f:
    f.write("x")
r3 = reg.get("list_dir").handler(".")
check("i percorsi relativi funzionano ancora", "sotto" in r3, r3[:90])
check("e restano relativi alla root", os.path.join(root, "sotto") not in r3, r3[:120])

T.set_permission_gate(None)
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(fuori, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
