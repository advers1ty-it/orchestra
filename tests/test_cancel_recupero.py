"""Dopo lo stop, il lavoro deve poter riprendere.

Il bug: `agent.request_cancel()` metteva `_cancel_flag = True` e nessuno
lo rimetteva a False. Da quel momento in poi, ogni turno successivo
aveva il flag gia' acceso: ogni tool_call veniva annullato PRIMA di
partire, con il messaggio "Cancellato dall'utente prima dell'esecuzione".

Il sintomo per l'utente e' sgradevole e poco intuitivo: dopo aver fermato
una conversazione, l'agente non poteva piu' fare niente tranne chattare.
I tool che chiedono un permesso (leggere fuori dalla cartella, la shell)
non partivano affatto, e il rifiuto sembrava arrivare dal permesso.

Il flag va resettato all'INIZIO di ogni turno: il cancel riguarda il turno
in corso, non tutti i turni futuri.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_cancel")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import LLMResponse, LoopConfig  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import Tool, ToolCall, ToolRegistry  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


# --------------------------------------------------------------------------
# Un tool che registra ogni esecuzione: se il flag e' sporco, non parte MAI.


chiamate: list[str] = []


def _pippo() -> str:
    # l'handler viene chiamato con **kwargs: niente argomenti, e va bene
    chiamate.append("pippo")
    return "fatto"


def _registro() -> ToolRegistry:
    r = ToolRegistry()
    r.register(Tool(name="pippo", description="un tool di prova per contare le esecuzioni",
                     schema={"type": "object", "properties": {}},
                     handler=_pippo))
    return r


class SoloTool:
    """Il provider chiede SEMPRE un tool, mai una risposta finale.

    Serve a vedere il flag di cancel: se resta acceso, il tool viene
    annullato prima dell'esecuzione e `chiamate` resta vuota.

    Il ritardo serve a una cosa precisa: il cancel deve arrivare DURANTE
    il turno, non dopo. Un provider istantaneo finisce prima che il test
    possa premere ■, e il bug resterebbe nascosto.
    """

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.n = 0
        self.name = "solo_tool"
        self.model = "m"

    def chat(self, messages, tools=None, **kw):
        time.sleep(self.delay)
        self.n += 1
        if self.n % 3 == 0:
            return LLMResponse(content=f"finale {self.n}", model="m")
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"t{self.n}", name="pippo", arguments="{}")],
            model="m",
        )


print("== il cancel riguarda il turno in corso, non quelli futuri ==")

s = Session(provider=SoloTool(), registry=_registro(), system_prompt="SYS",
            config=LoopConfig(max_iterations=8))

s.send("primo")
# il cancel deve arrivare a META' turno: aspetto che il turno sia partito
time.sleep(0.12)
s.cancel()
s.wait(timeout=10)
prima = len(chiamate)
check("il primo turno esegue i tool", prima > 0, f"chiamate={prima}")

# e si riparte: questo e' il momento in cui il bug fa male
s.send("secondo")
s.wait(timeout=10)
dopo = len(chiamate) - prima
check("dopo lo stop i tool tornano a girare", dopo > 0,
      f"nessun tool eseguito nel turno dopo lo stop")

check("il flag di cancel e' tornato a False",
      s.agent._cancel_flag is False,
      f"_cancel_flag={s.agent._cancel_flag}")

# --------------------------------------------------------------------------
# Il caso che l'utente ha descritto: dopo lo stop, il tool che chiede un
# permesso fuori dalla root viene negato all'istante invece di chiedere.

print("\n== dopo lo stop, un permesso fuori dalla root si chiede ancora ==")

from orchestra.permissions import Gate, Richiesta, Risposta  # noqa: E402

domande: list[Richiesta] = []


def _chiedi(r: Richiesta) -> Risposta:
    domande.append(r)
    return Risposta("una_volta")


gate = Gate(root=WORK, chiedi=_chiedi)
from orchestra.tools import set_permission_gate  # noqa: E402
from orchestra.tools.list_dir import tool_list_dir  # noqa: E402
set_permission_gate(gate)

# il tool REALE che chiede il permesso: list_dir su un path fuori dalla root
reg2 = ToolRegistry()
reg2.register(tool_list_dir())


class ChiedeFuori:
    """Il provider chiede list_dir su un path FUORI dalla root.

    E' il caso che l'utente ha descritto: dopo lo stop, l'agente non
    riusciva piu' a entrare nelle cartelle, e sembrava un rifiuto.
    """

    def __init__(self):
        self.n = 0
        self.name = "chiede_fuori"
        self.model = "m"

    def chat(self, messages, tools=None, **kw):
        time.sleep(0.05)
        self.n += 1
        if self.n % 3 == 0:
            return LLMResponse(content=f"finale {self.n}", model="m")
        # gli argomenti si costruiscono con json.dumps: scriverli a mano
        # porta a JSON invalido (i backslash di Windows non sono un
        # escape valido), e il tool non parte — un falso negativo che
        # sembrerebbe "il permesso non e' mai chiesto".
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"t{self.n}", name="list_dir",
                                 arguments=json.dumps({"path": "C:/Users/adver/Documents"}))],
            model="m",
        )


s2 = Session(provider=ChiedeFuori(), registry=reg2, system_prompt="SYS",
             config=LoopConfig(max_iterations=8))
s2.send("primo")
time.sleep(0.12)
s2.cancel()
s2.wait(timeout=10)

domande.clear()
s2.send("secondo")
s2.wait(timeout=10)

# il punto: il gate DEVE aver ricevuto la domanda, non aver negato in silenzio
check("il gate ha chiesto, non negato in silenzio", len(domande) > 0,
      "nessuna domanda e' arrivata al gate")

set_permission_gate(None)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
