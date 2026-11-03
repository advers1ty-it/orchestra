"""Modalita' piano: prima il piano, poi le modifiche.

Il rischio di questa funzione non e' che il piano non si veda: e' che il
blocco si aggiri. Qui si verifica il comportamento vero con un turno
completo — il modello prova a scrivere, viene fermato, propone il piano,
l'utente approva, la scrittura passa — e si controlla che l'approvazione
NON sopravviva al turno successivo.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = tempfile.mkdtemp(prefix="orch-piano-")
os.environ["ORCHESTRA_ROOT"] = WORK
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import LLMResponse, LoopConfig  # noqa: E402
from orchestra import domande  # noqa: E402
from orchestra import piano as piano_mod  # noqa: E402
from orchestra.agent import Agent  # noqa: E402
from orchestra.tools import _PROFILI, default_registry  # noqa: E402
from orchestra.tools.piano import tool_proponi_piano  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("== il tool c'e' in ogni profilo, e i tool che cambiano sono elencati ==")

check("proponi_piano e' in tutti i profili",
      all("proponi_piano" in p for p in _PROFILI.values()),
      str({k: "proponi_piano" in v for k, v in _PROFILI.items()}))
for nome in ("write_file", "edit_file", "run_shell", "run_tests"):
    check(f"{nome} e' bloccato in modalita' piano",
          nome in piano_mod.TOOL_CHE_CAMBIANO)
check("ask_user non e' bloccato", "ask_user" not in piano_mod.TOOL_CHE_CAMBIANO)
check("proponi_piano non e' bloccato",
      "proponi_piano" not in piano_mod.TOOL_CHE_CAMBIANO)

# ---------------------------------------------------------------------------
# Un turno completo, con un canale che approva.

risposte = []


def canale_che(testo: str):
    """Un canale che risponde sempre `testo`, come farebbe l'utente."""
    def canale(d):
        risposte.append(d)

        def rispondi():
            time.sleep(0.05)
            domande.rispondi(d["id"], testo)

        threading.Thread(target=rispondi, daemon=True).start()
    return canale


class Script:
    """Un modello che prova a scrivere PRIMA di avere il piano approvato."""

    name = "script"
    model = "m"

    def __init__(self, file="prima.txt", dopo="dopo.txt", con_piano=True):
        self.n = 0
        self.file = file
        self.dopo = dopo
        self.con_piano = con_piano

    def chat(self, messages, tools=None, **kw):
        import json
        self.n += 1
        passi = {
            1: ("write_file", {"path": self.file, "content": "x"}),
        }
        if self.con_piano:
            passi[2] = ("proponi_piano", {
                "piano": "Leggo il progetto e scrivo due file.",
                "passi": ["leggo", f"scrivo {self.file}", f"scrivo {self.dopo}"],
            })
            passi[3] = ("write_file", {"path": self.dopo, "content": "si"})
        if self.n in passi:
            nome, args = passi[self.n]
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id=f"t{self.n}", name=nome,
                                     arguments=json.dumps(args))],
                model="m",
            )
        return LLMResponse(content="fatto", model="m")


domande.imposta_canale(canale_che("Approva il piano"))
agent = Agent(provider=Script(), registry=default_registry(),
              system_prompt="SYS", config=LoopConfig(max_iterations=10))
agent.modalita_piano = True

print("\n== turno 1: scrivere prima del piano non si puo' ==")

stato = agent.run("fai il lavoro")
prima = os.path.join(WORK, "prima.txt")
dopo = os.path.join(WORK, "dopo.txt")

check("la scrittura prima del piano non e' avvenuta", not os.path.exists(prima))
check("il modello ha ricevuto il motivo del blocco",
      any(m.role == "tool" and "modalita' piano" in (m.content or "")
          for m in stato.messages),
      str([m.content[:80] for m in stato.messages if m.role == "tool"]))
check("il piano e' stato proposto", len(risposte) == 1,
      f"domande={len(risposte)}")
check("il piano conserva le righe",
      len(risposte) == 1 and "\n" in risposte[0].get("testo", ""),
      str(risposte[0].get("testo") if risposte else "")[:120])
check("la modale e' marcata come piano",
      len(risposte) == 1 and risposte[0].get("tipo") == "piano")
check("la scrittura dopo l'approvazione e' avvenuta", os.path.exists(dopo))
check("il contenuto e' quello chiesto",
      os.path.exists(dopo) and open(dopo, encoding="utf-8").read() == "si")

print("\n== turno 2: l'approvazione non e' un permesso permanente ==")

# Uno script NUOVO: il turno riparte dall'inizio, e la scrittura che al
# turno 1 era permessa (dopo l'approvazione) ora non deve passare.
agent.provider = Script(file="secondo.txt", dopo="mai.txt", con_piano=False)
stato2 = agent.run("altro lavoro")
check("al turno dopo si ricomincia bloccati",
      not os.path.exists(os.path.join(WORK, "secondo.txt")))
check("l'approvazione e' stata azzerata", piano_mod.approvato() is False)

print("\n== un rifiuto non sblocca, e la nota arriva al modello ==")

risposte.clear()
domande.imposta_canale(canale_che("No, cambia il passo 2"))
esito = tool_proponi_piano().handler(piano="Piano due\npassi")
check("il rifiuto non approva", piano_mod.approvato() is False)
check("il rifiuto e' detto al modello", "NON APPROVATO" in esito, esito)
check("la risposta dell'utente torna al modello", "passo 2" in esito, esito)

print("\n== senza canale non si approva niente ==")

domande.imposta_canale(None)
piano_mod.nuovo_turno()
esito = tool_proponi_piano().handler(piano="Piano")
check("senza canale il piano non e' approvato", piano_mod.approvato() is False)
check("senza canale lo dice", "PIANO NON APPROVATO" in esito, esito)

print("\n== il contesto dice che la modalita' e' attiva ==")

agent.modalita_piano = True
agent._aggiorna_prompt()
volatile = [m.content for m in agent.state.messages
            if m.role == "system" and m.name == "__contesto__"]
check("il blocco volatile annuncia la modalita' piano",
      any("Modalita' piano ATTIVA" in v for v in volatile),
      str(volatile)[:160])

agent.modalita_piano = False
agent._aggiorna_prompt()
volatile = [m.content for m in agent.state.messages
            if m.role == "system" and m.name == "__contesto__"]
check("spenta la modalita', il blocco sparisce",
      not any("Modalita' piano ATTIVA" in v for v in volatile))

domande.imposta_canale(None)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
