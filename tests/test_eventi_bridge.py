"""Cosa succede davvero agli eventi durante un turno.

Il sintomo visto dal fuori: lo stream mostra seq 0, 2, 4. Gli eventi 1
(turn_start) e 3 (assistant) arrivano al bridge ma non sulla rete. qui
si guarda il bridge di persona, senza browser e senza curl, per capire
se a perdersi sono gli eventi o il modo in cui vengono scritti.
"""

import os
import sys
from typing import Any
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ORCHESTRA_ROOT"] = r"D:\orchestra"

from orchestra.agent import Agent, LoopConfig  # noqa: E402
from orchestra.session import EventBridge  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import LLMResponse  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


VEDI = []


class Provider:
    """Risponde con testo e basta: il caso piu' semplice possibile."""

    model = "fake/modello"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="ok", model="fake/modello",
                           prompt_tokens=4, completion_tokens=3)


print("[1] Un turno emesso dal bridge, senza rete")
# Si ascolta con stream(), che e' l'unica porta: il bridge consegna, e
# non ha una coda pubblica da cui andare a pescare. Prima leggevamo
# _q direttamente, e quello e' stato proprio il buco: la coda interna
# e' un dettaglio, e un test che la usa finisce per verificare una
# cosa diversa da quella che l'utente vede.
bridge = EventBridge()
raccolti: list[dict] = []


def ascolta():
    for ev in bridge.stream(timeout=2.0):
        if ev["kind"] != "keepalive":
            raccolti.append(ev)
            if len(raccolti) >= 2:
                return


t = threading.Thread(target=ascolta, daemon=True)
t.start()
time.sleep(0.3)
agent = Agent(Provider(), default_registry(), "SYS", LoopConfig(max_iterations=2),
              on_event=bridge.emit)
agent.run("dimmi solo: ok")
t.join(timeout=4)

eventi = raccolti
seqs = [e["seq"] for e in eventi]
kinds = [e["kind"] for e in eventi]
print("   seq:", seqs)
print("   kind:", kinds)
check("gli eventi sono in ordine di seq", seqs == sorted(seqs), str(seqs))
check("i seq sono consecutivi", seqs == list(range(1, len(seqs) + 1)), str(seqs))
check("c'e' un solo evento assistant", kinds.count("assistant") == 1, str(kinds))
check("l'assistant ha contenuto",
      any(e["kind"] == "assistant" and (e["data"].get("content") or "").strip()
          for e in eventi))

print("\n[2] Lo stesso, ma con un testo che contiene righe vuote")
# Se il contenuto avesse dei \\n\\n reali, il framing SSE si romperebbe
# e i blocchi successivi sembrerebbero persi. json.dumps li scappa, ma
# il caso va verificato perche' e' il modo piu' subdolo di perdere
# eventi senza che nessuno se ne accorga.
class ProviderConRighe(Provider):
    model = "fake/righe"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="prima\n\nseconda\n\nterza",
                           model="fake/righe", prompt_tokens=4, completion_tokens=3)


bridge2 = EventBridge()
raccolti2: list[dict] = []


def ascolta2():
    for ev in bridge2.stream(timeout=2.0):
        if ev["kind"] != "keepalive":
            raccolti2.append(ev)
            if len(raccolti2) >= 2:
                return


t2 = threading.Thread(target=ascolta2, daemon=True)
t2.start()
time.sleep(0.3)
agent2 = Agent(ProviderConRighe(), default_registry(), "SYS", LoopConfig(max_iterations=2),
               on_event=bridge2.emit)
agent2.run("dimmi qualcosa")
t2.join(timeout=4)

import json  # noqa: E402

scritti = []
for ev in raccolti2:
    # esattamente quello che fa _sse_send
    payload = json.dumps(ev, default=str)
    scritti.append(f"data: {payload}\n\n")

stream = "".join(scritti)
blocchi = [b for b in stream.split("\n\n") if b.strip()]
check("ogni evento forma esattamente un blocco",
      len(blocchi) == len(scritti), f"{len(blocchi)} blocchi per {len(scritti)} eventi")
check("il testo con righe vuote non spezza nulla",
      all(b.startswith("data: ") and b.count("\n") == 0 for b in blocchi),
      "un blocco contiene un a capo")

print("\n[3] Il testo non vuoto e' la differenza fra evento e nessuno")
# Prima la snapshot scartava i messaggi assistant vuoti. Se lo stesso
# filtro finisce anche nel percorso degli eventi, un turno in cui il
# modello risponde ma il testo non arriva sparisce: e' successo, e
# sembrava un blocco della pagina.
class ProviderMuto(Provider):
    model = "fake/muto"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="   ", model="fake/muto",
                           prompt_tokens=4, completion_tokens=0)


bridge3 = EventBridge()
eventi3: list[Any] = []
bridge3._esegui(Agent(ProviderMuto(), default_registry(), "SYS",
                      LoopConfig(max_iterations=1), on_event=bridge3.emit),
                "x", eventi3)
k3 = [e["kind"] for e in eventi3]
check("il bridge emette comunque l'evento", "assistant" in k3, str(k3))
# ed e' il posto giusto per decidere: il bridge consegna, non giudica.
# Se il filtro vivesse qui, un client che si ricollega non troverebbe
# mai nella snapshot quello che ha perso in diretta.
vuoto = EventBridge()
eventi3b: list[Any] = []
vuoto._esegui(
    Agent(ProviderMuto(), default_registry(), "SYS", LoopConfig(max_iterations=1),
          on_event=lambda k, d: vuoto.emit(k, d)
          if not (k == "assistant" and not (d.get("content") or "").strip()) else None),
    "x", eventi3b)
k3b = [e["kind"] for e in eventi3b]
check("un assistant vuoto si puo' scartare a valle", "assistant" not in k3b, str(k3b))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
