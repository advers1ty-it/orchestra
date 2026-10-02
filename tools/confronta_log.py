"""Raccoglie i risultati dal log del benchmark e produce il confronto.

Il benchmark stampa una riga per task e quella riga è tutto quello
che serve. Non serve rieseguire niente, e non serve che il benchmark
sappia che questo strumento esiste: legge quello che ha già scritto.

Tre cose che la prima versione ha sbagliato, e che valgono per
qualsiasi strumento che legge l'output di un altro:

1. Il log ha i codici colore della CLI. Senza toglierli, la riga non
   inizia dove si crede.

2. L'intestazione del modello è il nome a capo, in grassetto, e non fra
   `==` come avevo indovinato. Risultato: zero righe lette.

3. Uno zero letto NON è un risultato. È un file non letto. Il primo
   zero ha prodotto una tabella con "serve almeno due modelli", che
   sembra una conclusione sul confronto ed è invece una constatazione
   sul lettore — e roba da mettermi a leggere invece di misurare.

Ecco perché questo strumento esce con codice 1 quando non legge
niente: uno zero che sembra un verdetto è peggio di uno che sembra un
errore.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.confronto import confronta, tabella_confronto  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")
RIGA = re.compile(r"^\s{2}(?P<task>[a-z][a-z0-9_]*)\s{2,}(?P<esito>ok|fail)\b")
# Il nome del modello nella CLI è quello breve ("nemotron-3-ultra"),
# non l'id completo col ":free". Per il confronto va bene: conta che i
# due abbiano nomi diversi, non che siano risolvibili nel catalogo.
MODELLO = re.compile(r"^[A-Za-z0-9][\w./:-]*$")

# righe che sembrano un nome ma sono altro
NON_NOME = ("Benchmark", "risultati", "modello", "confrontabile", "ok")


class R:
    def __init__(self, model, task_id, passed):
        self.model = model
        self.task_id = task_id
        self.category = ""
        self.passed = passed
        self.unusable = False


def leggi(path: str) -> tuple[list, list]:
    risultati: list = []
    modelli: list[str] = []
    modello = None
    with open(path, encoding="utf-8") as f:
        for grezza in f:
            riga = ANSI.sub("", grezza).rstrip()
            if not riga:
                continue
            m = RIGA.match(riga)
            if m:
                if modello:
                    risultati.append(R(modello, m.group("task"),
                                       m.group("esito") == "ok"))
                continue
            if riga.startswith(" ") or riga.startswith("-"):
                continue
            if MODELLO.match(riga) and not any(riga.startswith(p) for p in NON_NOME):
                if riga not in modelli:
                    modello = riga
                    modelli.append(riga)
    return risultati, modelli


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: confronta_log.py <log del benchmark>")
        return 2
    rs, modelli = leggi(sys.argv[1])
    print(f"righe lette: {len(rs)}")
    print(f"modelli trovati: {modelli}")
    if len(rs) == 0:
        print("\n! NESSUNA RIGA LETTA: questo non è il log che lo strumento "
              "sa leggere,\n  o il benchmark non è finito. Non è un "
              "risultato dello zero.")
        return 1
    esito = confronta(rs)
    print()
    print(tabella_confronto(esito))
    return 0


if __name__ == "__main__":
    sys.exit(main())