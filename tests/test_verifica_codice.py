import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.verificatori_codice import esegui, v_esegui  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


# Il caso facile: il codice giusto passa tutto
GIUSTO = '''
def media(xs):
    numeri = [x for x in xs if x is not None]
    if not numeri:
        return None
    return sum(numeri) / len(numeri)
'''

# Il caso che un modello scrive senza pensarci: la divisione per zero
# quando la lista e' vuota o tutta None
SBAGLIATO = '''
def media(xs):
    numeri = [x for x in xs if x is not None]
    return sum(numeri) / len(numeri)
'''

# Quello che passa finche' non trova l'input difficile
MEZZO = '''
def media(xs):
    numeri = [x for x in xs if x is not None]
    if not numeri:
        return 0
    return sum(numeri) / len(numeri)
'''

# ogni coppia e' (lista degli argomenti, atteso). Per media(xs) un
# argomento solo: la lista che si passa e' dentro un'altra lista.
PROVE = [
    ([[1, 2, 3]], 2.0),
    ([[None, 5]], 5.0),
    ([[]], None),
    ([[None, None]], None),
]


def scenario(codice, prove=PROVE):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "sol.py"), "w", encoding="utf-8") as f:
        f.write(codice)
    return v_esegui("sol.py", "media", prove)(d)


print("[1] Il codice giusto passa")
ok, det = scenario(GIUSTO)
check("tutte le prove passano", ok, det)

print("\n[2] Il codice sbagliato viene bocciato")
# E' la prova che il verificatore misura qualcosa. Se passasse, la
# curva di difficolta' misurerebbe se il modello sa scrivere un file.
ko, det = scenario(SBAGLIATO)
check("il divisore per zero e' preso", not ko, "il codice buggy e' passato")
check("e il messaggio dice quale prova", "prove sbagliate" in det, det)
mezzo, det2 = scenario(MEZZO)
check("il 0 al posto di None e' preso", not mezzo,
      "restituisce 0 invece di None: la prova esiste per questo")

print("\n[3] Quello che non regge")
# Nessuna prova -> non si puo' dire niente, e dire "passa" sarebbe
# falso
vuoto, det = scenario(GIUSTO, prove=[])
check("senza prove non dichiara che passa", not vuoto or "0/0" in det, det)

print("\n[4] Un file che non c'e'")
d = tempfile.mkdtemp()
ris, det = v_esegui("assente.py", "media", PROVE)(d)
check("distingue il file mancante", not ris and "non esiste" in det, det)

print("\n[5] Un codice che non termina")
# Il tetto: senza, un loop infinito blocca il benchmark per sempre e
# sembra un crash.
ciclo = "def media(xs):\n    while True:\n        pass\n"
ris, det = scenario(ciclo)
check("un loop infinito non blocca tutto", not ris, "il verificatore si e' bloccato")
check("e dice che non termina", "non termina" in det, det)

print("\n[6] Un codice che non compila")
rotto = "def media(xs)\n    return 1\n"
ris, det = scenario(rotto)
check("un errore di sintassi e' un fallimento pulito", not ris, det)
check("e lo nomina", "import" in det or "Sintassi" in det or "Error" in det, det)

print("\n[7] Il confronto dei numeri")
# 0.1+0.2 e' 0.30000000000000004 in Python. Un modello che risponde
# cosi' ha ragione e non deve essere bocciato per la virgola.
import orchestra.verificatori_codice as VC  # noqa: E402
check("0.30000000000000004 vale 0.3", VC._uguale(0.30000000000000004, 0.3))
check("3 e 3.0 sono lo stesso numero", VC._uguale(3, 3.0))
check("ma 3 e '3' no", not VC._uguale("3", 3))
check("e le liste si confrontano elemento a elemento",
      VC._uguale([1, 2.0], [1.0, 2]))
check("e i dizionari per chiave", VC._uguale({"a": 1}, {"a": 1.0}))
check("una lista diversa non passa", not VC._uguale([1, 2], [1, 2, 3]))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)