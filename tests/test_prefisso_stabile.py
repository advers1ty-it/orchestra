"""Prefisso stabile: la cache vive o muore qui.

Il difetto che questi controlli prevengono: skill e istruzioni del
progetto riscritte dentro il primo messaggio di sistema a ogni turno.
Con un prefisso che cambia, marcare system e tool per la cache non serve
a niente: ogni richiesta e' un cache miss.
"""

from __future__ import annotations

import os
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra.session import Session, LoopConfig  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import LLMResponse, Message  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="ok", model=self.model)


def nuovo() -> Session:
    return Session(provider=ProviderFinto(), registry=default_registry(),
                   system_prompt="BASE-STABILE", config=LoopConfig(max_iterations=2))


def blocchi(sess: Session):
    return [(m.role, m.name, m.content) for m in sess.agent.state.messages]


print("\n[1] Cambiando la domanda, il primo blocco non cambia")
s = nuovo()
s.agent.state.messages = [
    Message(role="system", content="BASE-STABILE"),
    Message(role="user", content="scrivi un test python"),
]
s.agent._aggiorna_prompt()
prima = s.agent.state.messages[0].content
volatile_prima = next((m.content for m in s.agent.state.messages
                       if m.role == "system" and m.name == "__contesto__"), "")
check("il blocco volatile esiste", bool(volatile_prima), str(blocchi(s)[:3]))
s.agent.state.messages[-1] = Message(role="user", content="cerca sul web notizie di borsa")
s.agent._aggiorna_prompt()
dopo = s.agent.state.messages[0].content
volatile_dopo = next((m.content for m in s.agent.state.messages
                      if m.role == "system" and m.name == "__contesto__"), "")
check("il primo blocco e' identico", prima == dopo == "BASE-STABILE", dopo)
check("il blocco volatile si aggiorna", volatile_dopo != volatile_prima,
      f"{len(volatile_prima)} -> {len(volatile_dopo)}")
check("il volatile sta dopo il primo",
      [b[0] for b in blocchi(s)[:2]] == ["system", "system"]
      and blocchi(s)[1][1] == "__contesto__")
check("c'e' un solo blocco volatile",
      sum(1 for m in s.agent.state.messages
          if m.role == "system" and m.name == "__contesto__") == 1)


print("\n[2] Chiamate ripetute non accumulano blocchi")
prima_lunghezza = len(s.agent.state.messages)
for _ in range(5):
    s.agent._aggiorna_prompt()
check("la lista non cresce", len(s.agent.state.messages) == prima_lunghezza,
      f"{prima_lunghezza} -> {len(s.agent.state.messages)}")


print("\n[3] Il progetto attivo non finisce nel prefisso")
s.agent.progetto = "progetto-di-prova"
s.agent._aggiorna_prompt()
base = s.agent.state.messages[0].content
volatile = next((m.content for m in s.agent.state.messages
                 if m.role == "system" and m.name == "__contesto__"), "")
check("il progetto e' nel blocco volatile", "progetto-di-prova" in volatile,
      volatile[-200:])
check("il progetto NON e' nel prefisso", "progetto-di-prova" not in base,
      base[:200])
check("il prefisso e' ancora quello", base == "BASE-STABILE", base)


print("\n[4] Senza skill e senza progetto il blocco volatile sparisce")
for nome in ("skill_cerca", "skill_leggi", "skill_genera", "skill_importa"):
    s.agent.registry.deactivate(nome)
s.agent.progetto = ""
s.agent._aggiorna_prompt()
check("nessun blocco volatile rimasto",
      not any(m.role == "system" and m.name == "__contesto__"
              for m in s.agent.state.messages), str(blocchi(s)[:3]))
check("il prefisso resta intatto", s.agent.state.messages[0].content == "BASE-STABILE")


print("\n[5] Cambiare identita' aggiorna il prefisso, non lo duplica")
s.agent.system_prompt = "NUOVA-IDENTITA'"
s.agent._aggiorna_prompt()
check("il prefisso e' quello nuovo", s.agent.state.messages[0].content == "NUOVA-IDENTITA'")
check("non ci sono due prefissi",
      sum(1 for m in s.agent.state.messages
          if m.role == "system" and m.name != "__contesto__") == 1)


print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
