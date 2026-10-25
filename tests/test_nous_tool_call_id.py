"""Un messaggio role="tool" rompe molti gateway: serve id E pairing.

Due difetti della stessa famiglia, visti sul Nous:

  1. 400 "Missing required parameter: 'tool_call_id'" — un messaggio di
     tool senza id. L'agente costruisce messaggi di sistema (gira_a_vuoto,
     nudge, steer, verifica) con un id inventato: ora ce l'hanno.
  2. 400 "messages[N] is a tool result, but it does not follow an
     assistant message with 'tool_calls' or its results" — avere un id
     NON basta: il tool result deve seguire un assistant che lo abbia
     chiamato con quell'id. Beam 1.0 e altri gateway stretti rifiutano
     la richiesta intera e il turno si interrompe senza riprendersi.

Questo test non parla con un provider: controlla il payload che
l'agente invierebbe, e richiede che OGNI messaggio role="tool" abbia un
tool_call_id non vuoto E che sia preceduto da un assistant con una
tool_call di quell'id.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["ORCHESTRA_ROOT"] = ROOT

from orchestra.agent import Agent, LoopConfig
from orchestra.tools import default_registry
from orchestra.types import LLMResponse, Message, ToolCall


class Provider:
    """Risponde con testo e basta: il caso piu' semplice possibile."""

    name = "fake"
    model = "fake/modello"

    def __init__(self, content="ok", tool_calls=()):
        self.content = content
        self.tool_calls = tool_calls
        self.chiamate = 0

    def chat(self, messages, tools=None, **kw):
        self.chiamate += 1
        if self.chiamate == 1 and self.tool_calls:
            return LLMResponse(content=self.content,
                               tool_calls=self.tool_calls,
                               model=self.model,
                               prompt_tokens=4, completion_tokens=3)
        return LLMResponse(content="fatto", model=self.model,
                           prompt_tokens=4, completion_tokens=3)


def _payload(agent):
    """Costruisce il payload che l'agente invierebbe al provider."""
    return [m.to_api() for m in agent.state.messages]


def _orfani(payload):
    """Gli indici dei tool result che non seguono un tool_call.

    Riproduce la validazione dei gateway stretti (Beam 1.0): un
    messaggio role="tool" deve essere preceduto da un assistant con una
    tool_call che porta lo stesso id. Un tool result orfano fa
    rifiutare la richiesta intera con 400.
    """
    out = []
    attesi = set()
    for i, m in enumerate(payload):
        if m.get("role") == "assistant":
            attesi |= {tc["id"] for tc in m.get("tool_calls") or []}
        elif m.get("role") == "tool":
            if m.get("tool_call_id") not in attesi:
                out.append(i)
            else:
                attesi.discard(m["tool_call_id"])
    return out


def _assert_nessun_orfano(agent, tag):
    orf = _orfani(_payload(agent))
    assert not orf, (
        f"{tag}: tool result orfano agli indici {orf} — "
        f"il gateway stretto rifiuterebbe la richiesta"
    )


def test_nudge_ha_id():
    """Dopo un nudge (modello che annuncia senza fare), il messaggio ha id."""
    reg = default_registry()
    prov = Provider(content="Analizzo il progetto e troverò la risposta.")
    ag = Agent(prov, reg, "test", LoopConfig(max_iterations=3))
    ag._annuncia_senza_fare = lambda c: True  # forza il nudge

    ag.run("test")

    payload = _payload(ag)
    tool_msgs = [m for m in payload if m.get("role") == "tool"]
    assert tool_msgs, "il nudge deve essere un messaggio tool"
    for m in tool_msgs:
        assert m.get("tool_call_id"), (
            f"nudge senza tool_call_id: {m!r}"
        )


def test_tool_normale_ha_id():
    """Dopo un tool call normale, il messaggio tool ha l'id della tool call."""
    reg = default_registry()
    tc = ToolCall(id="call_test123", name="echo",
                  arguments='{"testo":"ciao"}')
    prov = Provider(tool_calls=[tc])
    ag = Agent(prov, reg, "test", LoopConfig(max_iterations=3))

    ag.run("test")

    payload = _payload(ag)
    tool_msgs = [m for m in payload if m.get("role") == "tool"]
    assert tool_msgs, "ci devono essere messaggi tool"
    for m in tool_msgs:
        assert m.get("tool_call_id"), (
            f"messaggio tool senza tool_call_id: {m!r}"
        )


def test_steer_ha_id():
    """Uno steer inietta un messaggio tool: deve avere un tool_call_id.

    E' il bug che ha rotto lo steer: il messaggio era role="tool" senza
    id, e il Nous rispondeva 400 "Missing required parameter:
    'messages[N].tool_call_id'". Lo steer e' un messaggio del sistema,
    non un risultato di tool call: l'id si inventa, come per il nudge.
    """
    reg = default_registry()
    prov = Provider(content="fatto")
    ag = Agent(prov, reg, "test", LoopConfig(max_iterations=3))
    ag.steer("Rifai la parte X")

    ag.run("test")

    payload = _payload(ag)
    tool_msgs = [m for m in payload if m.get("role") == "tool"]
    assert tool_msgs, "lo steer deve essere un messaggio tool"
    for m in tool_msgs:
        assert m.get("tool_call_id"), (
            f"steer senza tool_call_id: {m!r}"
        )


def test_verifica_ha_id():
    """La nota di verifica fallita e' un messaggio tool: deve avere id."""
    def fallito(work):
        return False, "file mancante"

    reg = default_registry()
    prov = Provider(content="fatto")
    ag = Agent(prov, reg, "test", LoopConfig(max_iterations=4))
    ag.config.verifica_compito = {
        "verificatori": [fallito], "work": "", "max_tentativi": 2}

    ag.run("test")

    payload = _payload(ag)
    tool_msgs = [m for m in payload if m.get("role") == "tool"]
    assert tool_msgs, "la verifica fallita deve essere un messaggio tool"
    for m in tool_msgs:
        assert m.get("tool_call_id"), (
            f"verifica senza tool_call_id: {m!r}"
        )


def test_nessun_tool_orfano():
    """Ogni tool result del payload segue un assistant con quell'id.

    E' il difetto che Beam 1.0 ha fatto vedere: i messaggi di sistema
    (nudge, steer, verifica) sono role="tool" con un id inventato, ma
    nessun assistant li aveva chiamati — 400 "is a tool result, but it
    does not follow an assistant message with 'tool_calls'". Il fix e'
    il pairing: la nota e' preceduta da un assistant con una tool_call
    dello stesso id.
    """
    # nudge (modello che annuncia senza fare)
    reg = default_registry()
    ag = Agent(Provider(content="Analizzo il progetto."), reg, "test",
               LoopConfig(max_iterations=3))
    ag._annuncia_senza_fare = lambda c: True
    ag.run("test")
    _assert_nessun_orfano(ag, "nudge")

    # steer
    reg = default_registry()
    ag = Agent(Provider(content="fatto"), reg, "test",
               LoopConfig(max_iterations=3))
    ag.steer("Rifai la parte X")
    ag.run("test")
    _assert_nessun_orfano(ag, "steer")

    # verifica fallita
    def fallito(work):
        return False, "file mancante"
    reg = default_registry()
    ag = Agent(Provider(content="fatto"), reg, "test",
               LoopConfig(max_iterations=4))
    ag.config.verifica_compito = {
        "verificatori": [fallito], "work": "", "max_tentativi": 2}
    ag.run("test")
    _assert_nessun_orfano(ag, "verifica")


def test_compaction_non_lascia_tool_orfani():
    """La compaction non deve spezzare una coppia assistant/tool.

    Se l'ultimo messaggio prima del taglio e' un assistant con tool_calls
    e il primo messaggio TENUTO e' il suo tool result, il tool result
    resta orfano: il gateway stretto rifiuta tutta la richiesta.
    """
    from orchestra.context import compact_history

    msgs = [Message(role="system", content="prompt")]
    msgs.append(Message(role="user", content="obiettivo"))
    for i in range(20):
        msgs.append(Message(role="assistant", content=f"passo {i}"))
        msgs.append(Message(role="user", content=f"e {i}"))
    # coppia assistant(tool_calls)/tool al confine del taglio
    msgs.append(Message(role="assistant", content="",
                        tool_calls=[ToolCall(id="call_confine",
                                             name="echo",
                                             arguments='{"a":1}')]))
    msgs.append(Message(role="tool", tool_call_id="call_confine",
                        name="echo", content="risultato"))
    for i in range(7):
        msgs.append(Message(role="assistant", content=f"recente {i}"))

    n = compact_history(msgs, keep_recent=8)
    assert n > 0, "la compaction deve aver fuso qualcosa"
    payload = [m.to_api() for m in msgs]
    orf = _orfani(payload)
    assert not orf, f"tool result orfano dopo la compaction: {orf}"


if __name__ == "__main__":
    test_nudge_ha_id()
    print("OK   il nudge ha id")
    test_tool_normale_ha_id()
    print("OK   il tool normale ha id")
    test_steer_ha_id()
    print("OK   lo steer ha id")
    test_verifica_ha_id()
    print("OK   la verifica ha id")
    test_nessun_tool_orfano()
    print("OK   nessun tool result orfano nel payload")
    test_compaction_non_lascia_tool_orfani()
    print("OK   la compaction non lascia tool orfani")
    print("\nTUTTO OK")