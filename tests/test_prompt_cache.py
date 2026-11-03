"""Prompt caching: i marcatori giusti, nel payload giusto.

Anthropic non riusa niente se non lo si marca; OpenAI-compatibile lo fa
da solo e non vuole campi suoi. Questi controlli guardano il payload che
parte davvero, senza rete.
"""

from __future__ import annotations

import os
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra.providers import AnthropicAdapter, OpenAICompatAdapter  # noqa: E402
from orchestra.types import Message  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class Cattura(AnthropicAdapter):
    """Anthropic senza rete: prende il payload e finge una risposta."""

    def __init__(self) -> None:
        super().__init__(base_url="http://127.0.0.1:9", api_key="finta",
                         model="claude-3-5-sonnet-latest")
        self.visto = None

    def _post(self, payload):
        self.visto = payload
        return {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "model": self.model,
            "stop_reason": "end_turn",
        }


TOOL_A = {"type": "function", "function": {
    "name": "read_file", "description": "legge", "parameters": {"type": "object"}}}
TOOL_B = {"type": "function", "function": {
    "name": "write_file", "description": "scrive", "parameters": {"type": "object"}}}

print("\n[1] System, tool e coda sono marcati")
a = Cattura()
a.chat([Message(role="system", content="regole"),
        Message(role="user", content="ciao")],
       tools=[TOOL_A, TOOL_B])
p = a.visto or {}
system = p.get("system")
check("il system e' un blocco, non una stringa", isinstance(system, list), str(type(system)))
check("il testo e' intatto", system and system[0].get("text") == "regole")
check("il system e' marcato",
      system and system[0].get("cache_control") == {"type": "ephemeral"})
tools = p.get("tools") or []
check("i tool ci sono", len(tools) == 2, str(len(tools)))
check("il primo tool non e' marcato", "cache_control" not in tools[0])
check("l'ultimo tool e' marcato",
      tools and tools[-1].get("cache_control") == {"type": "ephemeral"})
coda = p.get("messages", [{}])[-1].get("content", [{}])[-1]
check("l'ultimo blocco del messaggio e' marcato",
      coda.get("cache_control") == {"type": "ephemeral"}, str(coda))


print("\n[2] Senza system o tool non si inventano campi")
a = Cattura()
a.chat([Message(role="user", content="solo una domanda")])
p = a.visto or {}
check("nessun campo system", "system" not in p, str(p.keys()))
check("nessun campo tools", "tools" not in p, str(p.keys()))
check("la coda e' comunque marcata",
      p["messages"][-1]["content"][-1].get("cache_control") == {"type": "ephemeral"})


print("\n[3] Un system vuoto non diventa un blocco vuoto")
a = Cattura()
a.chat([Message(role="system", content=""),
        Message(role="user", content="ciao")])
check("system assente", "system" not in (a.visto or {}))


print("\n[4] L'adapter OpenAI-compatibile non riceve campi Anthropic")
visto = {}


class CatturaOpenAI(OpenAICompatAdapter):
    def _post(self, path, payload, _retry=True):
        visto.clear()
        visto.update(payload)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}


o = CatturaOpenAI(base_url="http://127.0.0.1:9", api_key="finta",
                  model="gpt-4o-mini")
o.chat([Message(role="system", content="regole"),
        Message(role="user", content="ciao")], tools=[TOOL_A, TOOL_B])
check("il system resta un messaggio di testo",
      "system" not in visto
      and visto.get("messages", [{}])[0].get("role") == "system"
      and isinstance(visto["messages"][0].get("content"), str), str(visto.keys()))
check("i tool non hanno cache_control",
      all("cache_control" not in t for t in visto.get("tools") or []))


print("\n[5] Le immagini non impediscono la marcatura")
a = Cattura()
a.chat([Message(role="user", content="guarda",
                images=["data:image/png;base64,AAAA"])])
blocchi = (a.visto or {}).get("messages", [{}])[-1].get("content", [])
check("l'immagine c'e'", any(b.get("type") == "image" for b in blocchi))
check("l'ultimo blocco e' marcato",
      blocchi[-1].get("cache_control") == {"type": "ephemeral"}, str(blocchi[-1]))


print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
