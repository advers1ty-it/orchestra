"""Due limiti che si scoprono troppo tardi.

Il tetto di tempo: le iterazioni limitavano le chiamate, non l'orologio.
Venti giri con dentro test da due minuti fanno un turno da mezz'ora, e
l'unica uscita era premere stop.

Il budget: `record_usage` registra e POI controlla, quindi la chiamata
che sfora viene pagata e solo dopo il turno si ferma — e la chiamata che
sfora e' quella piu' cara. Qui si verifica che si fermi PRIMA di
spendere.

Nessuno dei due test aspetta davvero: il tempo si simula spostando
l'orologio del processo, il budget si configura minuscolo. Il provider
finto conta le chiamate, cosi' "fermato prima di spendere" e' un fatto
misurato e non una speranza.
"""

import contextlib
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_root = tempfile.mkdtemp(prefix="limiti-")
os.environ["ORCHESTRA_ROOT"] = _root
os.environ["ORCHESTRA_HOME"] = _root

from orchestra.agent import Agent, LoopConfig  # noqa: E402
from orchestra.budget import BudgetLimits  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import LLMResponse, ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    """Chiede sempre lo stesso tool, e conta quante volte e' stato chiamato."""

    name = "finto"
    model = "finto-modello"

    def __init__(self, nome_tool="list_dir"):
        self.nome_tool = nome_tool
        self.chiamate = 0

    def chat(self, messages, tools=None, **kwargs):
        self.chiamate += 1
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"call_{self.chiamate}", name=self.nome_tool,
                                 arguments="{}")],
            model=self.model,
            prompt_tokens=1000,
            completion_tokens=100,
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        # L'agent preferisce lo streaming quando esiste: qui e' lo stesso
        # di `chat`, perche' il test misura chiamate e fermate, non i
        # chunk.
        return self.chat(messages, tools, **kwargs)


@contextlib.contextmanager
def orologio_avanti(secondi, *, dopo=1):
    """Sposta in avanti `time.monotonic` dentro `orchestra.agent`.

    Le prime `dopo` letture sono vere: sono quella che registra l'inizio
    del turno. Dalla successiva in poi il turno risulta vecchio di
    `secondi`, cosi' il controllo scatta al punto che ci interessa senza
    far aspettare il test.
    """
    import orchestra.agent as mod

    vero = mod.time
    base = vero.monotonic()
    contatore = {"n": 0}

    class Finto:
        def monotonic(self):
            contatore["n"] += 1
            if contatore["n"] <= dopo:
                return base
            return base + secondi

        def __getattr__(self, nome):
            return getattr(vero, nome)

    mod.time = Finto()
    try:
        yield
    finally:
        mod.time = vero


print("\n[1] Il tempo massimo ferma il turno, e prima di spendere")
provider = ProviderFinto()
agente = Agent(provider, default_registry(), "sistema",
               LoopConfig(max_iterations=20, max_secondi_turno=30.0))
with orologio_avanti(31.0):
    stato = agente.run("fai qualcosa")
check("fermato per tempo", stato.stopped_because == "tempo_scaduto",
      stato.stopped_because)
check("il provider non e' stato chiamato", provider.chiamate == 0,
      str(provider.chiamate))
check("nel contesto resta il motivo",
      any("TEMPO MASSIMO" in (m.content or "") for m in stato.messages),
      str([m.role for m in stato.messages]))

print("\n[2] Con il tetto a zero non si ferma niente")
provider = ProviderFinto()
agente = Agent(provider, default_registry(), "sistema",
               LoopConfig(max_iterations=2, max_secondi_turno=0))
stato = agente.run("fai qualcosa")
check("il provider e' stato chiamato", provider.chiamate > 0,
      str(provider.chiamate))
check("non e' fermato per tempo", stato.stopped_because != "tempo_scaduto",
      stato.stopped_because)

print("\n[3] Taglio dentro il batch dei tool: nessun tool_call a vuoto")
provider = ProviderFinto()
agente = Agent(provider, default_registry(), "sistema",
               LoopConfig(max_iterations=20, max_secondi_turno=30.0))
# due letture "vere": l'inizio del turno e il controllo in cima al ciclo.
# La terza e' dentro il batch, dopo che il modello ha chiesto il tool.
with orologio_avanti(60.0, dopo=2):
    stato = agente.run("fai qualcosa")
check("fermato per tempo", stato.stopped_because == "tempo_scaduto",
      stato.stopped_because)
chiamate_modello = [m for m in stato.messages
                    if m.role == "assistant" and m.tool_calls]
risultati = [m for m in stato.messages if m.role == "tool"]
check("il modello aveva chiesto dei tool", len(chiamate_modello) >= 1,
      str(len(chiamate_modello)))
if chiamate_modello:
    attesi = {tc.id for tc in chiamate_modello[0].tool_calls}
    ottenuti = {m.tool_call_id for m in risultati}
    check("ogni tool_call ha il suo risultato", attesi <= ottenuti,
          f"attesi {attesi}, ottenuti {ottenuti}")
    check("il risultato dice perche' e' vuoto",
          any("Tempo massimo" in (m.content or "") for m in risultati),
          str([(m.content or "")[:40] for m in risultati]))

print("\n[4] Budget controllato PRIMA di spendere")
provider = ProviderFinto()
limiti = BudgetLimits(
    max_tokens_per_session=0,
    max_cost_usd_per_session=0,
    max_requests_per_session=0,
    max_tokens_per_task=0,
    # Un milionesimo di dollaro: la stima della prima chiamata (1000
    # token di prompt + il tetto di output) lo supera di sicuro.
    max_cost_usd_per_task=0.000001,
    max_iterations_per_task=0,
    max_cost_usd_per_day=0,
    max_cost_usd_per_month=0,
)
agente = Agent(provider, default_registry(), "sistema",
               LoopConfig(max_iterations=3, budget_limits=limiti))
stato = agente.run("fai qualcosa")
check("fermato per budget", stato.stopped_because == "budget_exceeded",
      stato.stopped_because)
check("il provider NON e' stato chiamato", provider.chiamate == 0,
      f"chiamate={provider.chiamate}")
check("il contesto spiega il motivo",
      any("BUDGET" in (m.content or "") for m in stato.messages),
      str([(m.content or "")[:40] for m in stato.messages]))

print("\n[5] Budget con margine: il turno parte")
provider = ProviderFinto()
limiti = BudgetLimits(
    max_tokens_per_session=0,
    max_cost_usd_per_session=0,
    max_requests_per_session=0,
    max_tokens_per_task=0,
    max_cost_usd_per_task=5.0,
    max_iterations_per_task=0,
    max_cost_usd_per_day=0,
    max_cost_usd_per_month=0,
)
agente = Agent(provider, default_registry(), "sistema",
               LoopConfig(max_iterations=2, budget_limits=limiti))
agente.run("fai qualcosa")
check("il provider e' stato chiamato", provider.chiamate > 0,
      str(provider.chiamate))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
