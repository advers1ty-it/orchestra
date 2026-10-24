"""Un messaggio role="tool" senza tool_call_id rompe molti gateway.

Il Nous (e altri proxy) rifiutano con 400 "Missing required parameter:
'tool_call_id'" se un messaggio di tool non ha l'id. L'agente
costruisce due messaggi di sistema (gira_a_vuoto e nudge) senza id:
quando finiscono nel payload, la richiesta va in 400 e il modello
non si riprende.

Questo test non parla con un provider: controlla il payload che
l'agente invierebbe, e richiede che OGNI messaggio role="tool"
abbia un tool_call_id non vuoto.
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


if __name__ == "__main__":
    test_nudge_ha_id()
    print("OK   il nudge ha id")
    test_tool_normale_ha_id()
    print("OK   il tool normale ha id")
    test_steer_ha_id()
    print("OK   lo steer ha id")
    test_verifica_ha_id()
    print("OK   la verifica ha id")
    print("\nTUTTO OK")