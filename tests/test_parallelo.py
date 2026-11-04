"""Il parallelismo dei tool di sola lettura, e i suoi confini.

Il difetto che questi controlli prevengono e' doppio:

- se il parallelismo fosse "cieco", due scritture sullo stesso file
  partirebbero insieme e l'ordine smetterebbe di contare;
- se l'elenco dei tool di sola lettura contenesse un tool che scrive, un
  turno con due chiamate lo eseguirebbe fuori sequenza senza che nessuno
  se ne accorga.

Per questo si controlla il tempo (due letture insieme durano meno della
somma) E l'ordine dei risultati E l'elenco.
"""

from __future__ import annotations

import json
import os
import sys
import time

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

import tempfile  # noqa: E402

os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orchestra_par_")

from orchestra.agent import Agent, LoopConfig  # noqa: E402
from orchestra import parallelo, piano  # noqa: E402
from orchestra.tools import Tool, ToolRegistry  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class Orologio:
    """Registra quando ogni esecuzione parte e quando finisce."""

    def __init__(self, durata: float) -> None:
        self.durata = durata

    def __call__(self, **kw):
        self.inizio = time.monotonic()
        time.sleep(self.durata)
        self.fine = time.monotonic()
        return f"fatto {kw.get('path', '')}"


def registro(durata: float = 0.3):
    reg = ToolRegistry()
    lettura = Orologio(durata)
    scrittura = Orologio(durata)
    reg.registra(Tool("read_file", "legge", {}, lettura))
    reg.registra(Tool("write_file", "scrive", {}, scrittura))
    return reg, lettura, scrittura


def chiamate(*coppie) -> list[ToolCall]:
    return [ToolCall(id=f"t{i}", name=nome,
                     arguments=json.dumps({"path": nome}))
            for i, nome in enumerate(coppie)]


def agente(reg) -> Agent:
    return Agent(provider=object(), registry=reg, system_prompt="s",
                 config=LoopConfig())


print("\n== due letture nello stesso giro partono insieme ==")

reg, lettura, _ = registro()
a = agente(reg)
inizio = time.monotonic()
esiti, avviate = a._prepara_parallelo(
    chiamate("read_file", "read_file", "read_file"))
durata = time.monotonic() - inizio
check("tutte le chiamate hanno un esito", len(esiti) == 3, str(esiti))
check("tutte risultano avviate", len(avviate) == 3)
check("durano meno della somma (0.3 x 3)", durata < 0.75, f"{durata:.2f}s")
check("i risultati sono quelli dei tool",
      all("fatto" in e[0] for e in esiti.values()))

print("\n== una scrittura manda tutto in fila ==")

reg, _, _ = registro()
a = agente(reg)
esiti, avviate = a._prepara_parallelo(chiamate("read_file", "write_file"))
check("nessun esito preparato", esiti == {} and avviate == set())

print("\n== l'ordine delle chiamate resta quello del modello ==")

reg, _, _ = registro(0.05)
a = agente(reg)
c = chiamate("read_file", "read_file")
esiti, _ = a._prepara_parallelo(c)
check("l'ordine degli id e' quello richiesto",
      list(esiti) == [tc.id for tc in c], str(list(esiti)))
check("gli argomenti non si sono scambiati",
      "read_file" in esiti[c[0].id][0])

print("\n== l'elenco e i blocchi non si contraddicono ==")

check("write_file non e' di sola lettura",
      not parallelo.sola_lettura("write_file"))
check("nessun tool che modifica e' anche di sola lettura",
      not (parallelo.SOLA_LETTURA & piano.TOOL_CHE_CAMBIANO),
      str(sorted(parallelo.SOLA_LETTURA & piano.TOOL_CHE_CAMBIANO)))
check("un tool sconosciuto non e' di sola lettura",
      not parallelo.sola_lettura("mcp__server__scrivi"))

print("\n== con il cancel richiesto non parte niente ==")

reg, _, _ = registro()
a = agente(reg)
a._cancel_flag = True
esiti, avviate = a._prepara_parallelo(chiamate("read_file", "read_file"))
check("nessuna esecuzione dopo il cancel", esiti == {} and avviate == set())

print("\n== l'interruttore spegne il parallelismo ==")

reg, _, _ = registro()
a = agente(reg)
a.config.parallelo = False
esiti, avviate = a._prepara_parallelo(chiamate("read_file", "read_file"))
check("con parallelo=False si va in fila", esiti == {} and avviate == set())

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
