"""Il confronto deve dire quando non vale.

Il numero che rende il tutto onesto e' QUANTI task discriminano. Due
modelli che differiscono su due task su quaranta non sono stati
confrontati: sono stati misurati in parte, e la classifica che ne
esce sembra precisa quanto un oroscopo.

Qui si costruiscono i casi in cui il confronto NON regge — pochi task
discriminanti, una ripetizione sola, insiemi diversi — e si verifica
che il modulo se ne accorga e lo dichiari PRIMA della classifica.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.confronto import (  # noqa: E402
    DISCRIMINANTI_MINIMI, RIPETIZIONI_MINIME, confronta, tabella_confronto,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


class R:
    def __init__(self, model, task_id, category="code", passed=False, unusable=False):
        self.model = model
        self.task_id = task_id
        self.category = category
        self.passed = passed
        self.unusable = unusable


def coppia(n_differiscono: int, n_uguali: int = 20, ripetizioni: int = 4):
    """Due modelli che passano tutto uguale e differiscono su n task."""
    out = []
    for i in range(n_uguali):
        for m in ("bravo", "scarso"):
            for _ in range(ripetizioni):
                out.append(R(m, f"uguale_{i}", passed=True))
    for i in range(n_differiscono):
        for _ in range(ripetizioni):
            out.append(R("bravo", f"diff_{i}", passed=True))
            out.append(R("scarso", f"diff_{i}", passed=False))
    return out


print("[1] Il caso buono: molti task che separano, con ripetizioni")
esito = confronta(coppia(8, 20, 4))
check("il confronto e' convalidato", esito["confrontabile"], esito["motivo"])
check("e conta i task che discriminano", esito["n_discriminanti"] == 8,
      str(esito["n_discriminanti"]))
check("il bravo e' davanti", esito["classifica"][0]["modello"] == "bravo",
      str([c["modello"] for c in esito["classifica"]]))
check("con il punteggio pieno", esito["classifica"][0]["tasso"] == 100.0,
      str(esito["classifica"][0]["tasso"]))
check("e lo scarso a zero", esito["classifica"][1]["tasso"] == 0.0,
      str(esito["classifica"][1]["tasso"]))

print("\n[2] Pochi task discriminanti: il confronto non vale")
esito2 = confronta(coppia(2, 40, 4))
check("pochi discriminanti non vengono dichiarati validi",
      not esito2["confrontabile"], esito2["motivo"])
check("e il motivo lo dice", "differiscono" in esito2["motivo"], esito2["motivo"])
check("la soglia e' dichiarata", DISCRIMINANTI_MINIMI == 6, str(DISCRIMINANTI_MINIMI))
check("i due task ci sono comunque", esito2["n_discriminanti"] == 2,
      str(esito2["n_discriminanti"]))

print("\n[3] Una ripetizione sola: la differenza puo' essere caso")
esito3 = confronta(coppia(10, 20, 1))
check("una ripetizione sola non convalida", not esito3["confrontabile"],
      esito3["motivo"])
check("e il motivo parla di fortuna", "sorte" in esito3["motivo"], esito3["motivo"])
check("la soglia e' dichiarata", RIPETIZIONI_MINIME == 3, str(RIPETIZIONI_MINIME))

print("\n[4] Con ripetizioni la differenza si ferma")
# Il caso in cui il confronto e' pieno di volte ma la differenza non
# e' stabile: il modello scarso sbaglia solo alla prima ripetizione.
rumore = []
for i in range(10):
    for k in range(5):
        rumore.append(R("bravo", f"t{i}", passed=True))
        rumore.append(R("scarso", f"t{i}", passed=(k > 0)))
e4 = confronta(rumore)
check("il modello instabile non e' trattato come incapace",
      e4["classifica"][1]["tasso"] == 80.0, str(e4["classifica"][1]["tasso"]))
check("e la ripetizione lo dichiara", e4["confrontabile"], e4["motivo"])
check("il tasso e' quello medio, non 0 o 100",
      0 < e4["classifica"][1]["tasso"] < 100, str(e4["classifica"][1]["tasso"]))

print("\n[5] Insiemi di task diversi non sono confrontabili")
mescolati = [R("bravo", f"a{i}", passed=True) for i in range(10)]
mescolati += [R("scarso", f"b{i}", passed=False) for i in range(10)]
e5 = confronta(mescolati)
check("diversi insiemi non convalidano", not e5["confrontabile"], e5["motivo"])
check("e il motivo lo dice chiaramente",
      "stessi task" in e5["motivo"], e5["motivo"])

print("\n[6] Un modello riservato non entra nel confronto")
riservato = [R("normale", f"t{i}", passed=True) for i in range(10)]
riservato += [R("riservato", f"t{i}", passed=False, unusable=True) for i in range(10)]
e6 = confronta(riservato)
check("il riservato non e' fra i modelli", "riservato" not in e6["modelli"],
      str(e6["modelli"]))

print("\n[7] Un solo modello non e' un confronto")
e7 = confronta([R("solo", f"t{i}", passed=True) for i in range(10)])
check("un modello solo non convalida", not e7["confrontabile"], e7["motivo"])
check("e lo dice", "due modelli" in e7["motivo"], e7["motivo"])

print("\n[8] La tabella mette l'avvertenza PRIMA della classifica")
tab = tabella_confronto(e5)
righe = tab.split("\n")
i_avv = next((i for i, r in enumerate(righe) if "NON CONVALIDO" in r), None)
i_cla = next((i for i, r in enumerate(righe) if "bravo" in r or "normale" in r), None)
check("l'avvertenza c'e'", i_avv is not None, tab[:90])
check("e sta sopra la classifica", i_avv is not None and i_cla is not None
      and i_avv < i_cla, tab[:120])
check("la classifica c'e' comunque",
      "modello" in tab.lower() and any("bravo" in r for r in righe), tab[:150])

print("\n[9] Il vuoto non esplode")
e9 = confronta([])
check("nessun risultato non rompe", e9["modelli"] == [], str(e9["modelli"]))
check("e non inventa un confronto", not e9["confrontabile"], e9["motivo"])
check("la tabella di un vuoto si stampa", isinstance(tabella_confronto(e9), str))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)