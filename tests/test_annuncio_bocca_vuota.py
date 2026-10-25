"""Il nudge anti-bocca-vuota deve riconoscere gli annunci che i modelli fanno davvero.

Il difetto, osservato su Beam 1.0: il modello chiudeva il turno con
"Faccio le modifiche vere ora. Prima indago il modal tracce." — nessun
tool, una iterazione, esito "risposta_finale". Il nudge esiste apposta
per questo caso, ma non e' partito: "faccio" e "indago" non erano nel
vocabolario. Per l'utente il sintomo era "risponde a caso", e il modello
stava solo promettendo.

Le tracce di quei turni sono la prova: sette di fila a una iterazione,
zero tool, e in nessuna traccia recente un evento `nudge` o
`solo_parole`. La rete c'era e non si e' mai aperta.

Qui si verifica in due modi:
  1. il vocabolario, sui testi veri presi dalle tracce;
  2. il giro completo, con un provider finto che annuncia sempre: il
     nudge deve partire, e il secondo annuncio di fila deve chiudere
     con "solo_parole" invece di mentire con "risposta_finale".
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["ORCHESTRA_ROOT"] = ROOT

from orchestra.agent import Agent, LoopConfig
from orchestra.tools import default_registry
from orchestra.types import LLMResponse, ToolCall

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


# ------------------------------------------------------ [1] il vocabolario
print("[1] Gli annunci che i modelli fanno davvero")

# I primi tre sono testi veri, presi dalle tracce del turno incriminato.
ANNUNCI = [
    "Faccio le modifiche vere ora. Prima indago il modal tracce.",
    "Hai ragione: ho allucinato commit/file senza toccare nulla. Mi scuso. "
    "Faccio il lavoro vero adesso.",
    "Faccio il lavoro vero adesso, step by step.",
    "Ora faccio la modifica.",
    "Indago il problema e poi ti dico.",
    "Vado a leggere il file.",
    "Mi metto al lavoro.",
    "Comincio dal webapp.",
    "Passo a modificare index.html.",
    "Adesso sistemo il file.",
    "Procedo con la modifica.",
    "Analizzo il progetto e ti dico.",
    "Ora applico la patch.",
    "Modificherò il file e poi ti aggiorno.",
    "Sto per correggere il bug.",
    "Controllo il file e ti dico cosa manca.",
]

for testo in ANNUNCI:
    check(f"annuncio riconosciuto: {testo[:46]}",
          Agent._annuncia_senza_fare(testo) is True,
          "non riconosciuto: il nudge non partirebbe")

# Le risposte vere NON devono passare di qui: un falso positivo costa una
# risposta buona, quindi si verifica anche il contrario.
RISPOSTE = [
    "Ecco la valutazione, punto 1: il codice e' corretto e non serve altro.",
    "Il file index.html ha 148 div aperti e 148 chiusi: il bilancio torna.",
    "Non faccio nulla ora: il file e' gia' corretto.",
    "Faccio notare che il file non esiste.",
    "La funzione restituisce True quando il testo e' un annuncio.",
    "Il difetto era nel CSS, non nel JavaScript: display:none sul genitore.",
    "x" * 300,
    "riga uno\nriga due\nriga tre\nriga quattro",
]

for testo in RISPOSTE:
    check(f"risposta non scambiata per annuncio: {testo[:40]}",
          Agent._annuncia_senza_fare(testo) is False,
          "falso positivo: Orchestra interromperebbe una risposta vera")


# ------------------------------------------------------ [2] il giro completo
print("\n[2] Il nudge parte, e il secondo annuncio chiude onesto")


class Provider:
    """Annuncia sempre lo stesso lavoro, senza mai chiamare un tool."""

    name = "fake"
    model = "fake/modello"

    def __init__(self, testo):
        self.testo = testo
        self.chiamate = 0

    def chat(self, messages, tools=None, **kw):
        self.chiamate += 1
        return LLMResponse(content=self.testo, model=self.model,
                           prompt_tokens=4, completion_tokens=3)


eventi = []
prov = Provider("Faccio le modifiche vere ora. Prima indago il modal tracce.")
ag = Agent(prov, default_registry(), "test", LoopConfig(max_iterations=6),
           on_event=lambda k, d: eventi.append(k))
ag.run("sistema il modal delle tracce")

check("il nudge e' partito", "nudge" in eventi,
      f"eventi visti: {sorted(set(eventi))}")
check("il secondo annuncio chiude con solo_parole",
      ag.state.stopped_because == "solo_parole",
      f"esito: {ag.state.stopped_because!r}")
check("non mente con risposta_finale",
      ag.state.stopped_because != "risposta_finale")
check("nessun tool e' stato eseguito", ag.state.tool_calls_made == 0,
      f"tool eseguiti: {ag.state.tool_calls_made}")

# Il nudge deve essere un messaggio tool con id: senza, il gateway
# risponde 400 (vedi test_nous_tool_call_id.py). Si filtra per ruolo
# "tool": la coppia sintetica ha anche un assistant fittizio col nome
# "__nudge__" (serve al pairing, vedi _nota_sistema).
nudge = [m for m in ag.state.messages
         if m.name == "__nudge__" and m.role == "tool"]
check("il nudge e' nel contesto una volta sola", len(nudge) == 1,
      f"nudge trovati: {len(nudge)}")
if nudge:
    check("il nudge ha un tool_call_id", bool(nudge[0].tool_call_id))

# Una risposta vera non deve far partire niente.
eventi2 = []
prov2 = Provider("Il file ha 148 div aperti e 148 chiusi: il bilancio torna.")
ag2 = Agent(prov2, default_registry(), "test", LoopConfig(max_iterations=6),
            on_event=lambda k, d: eventi2.append(k))
ag2.run("quanti div ci sono?")
check("una risposta vera chiude come risposta_finale",
      ag2.state.stopped_because == "risposta_finale",
      f"esito: {ag2.state.stopped_because!r}")
check("una risposta vera non prende il nudge", "nudge" not in eventi2,
      f"eventi: {sorted(set(eventi2))}")

# ------------------------------------------------------ [3] dopo aver lavorato
print("\n[3] Anche dopo aver usato i tool: il turno non si chiude su un annuncio")

# Il buco: il controllo dell'annuncio stava dentro `tool_calls_made == 0`.
# Un turno che aveva gia' fatto venti tool e poi chiudeva con "ora faccio
# il resto" non veniva ripreso da nessuno: il lavoro restava a meta' e
# l'esito diceva "risposta_finale", cioe' "completato".


class ProviderConLavoro:
    """Prima usa un tool, poi annuncia, poi annuncia di nuovo."""

    name = "fake"
    model = "fake/modello"

    def __init__(self):
        self.chiamate = 0

    def chat(self, messages, tools=None, **kw):
        self.chiamate += 1
        if self.chiamate == 1:
            return LLMResponse(
                content="", model=self.model, prompt_tokens=4,
                completion_tokens=3,
                tool_calls=[ToolCall(id="call_1", name="calculate",
                                     arguments='{"expression":"2+2"}')])
        return LLMResponse(content="Ora faccio il resto della modifica.",
                           model=self.model, prompt_tokens=4,
                           completion_tokens=3)


eventi3 = []
prov3 = ProviderConLavoro()
ag3 = Agent(prov3, default_registry(), "test", LoopConfig(max_iterations=8),
            on_event=lambda k, d: eventi3.append(k))
ag3.run("sistema il modal")

check("il tool e' stato eseguito davvero", ag3.state.tool_calls_made == 1,
      f"tool eseguiti: {ag3.state.tool_calls_made}")
check("il nudge parte anche dopo aver lavorato", "nudge" in eventi3,
      f"eventi: {sorted(set(eventi3))}")
check("l'esito non mente con risposta_finale",
      ag3.state.stopped_because != "risposta_finale",
      f"esito: {ag3.state.stopped_because!r}")
check("l'esito e' annuncio_finale, non solo_parole",
      ag3.state.stopped_because == "annuncio_finale",
      f"esito: {ag3.state.stopped_because!r}")

nudge3 = [m for m in ag3.state.messages
          if m.name == "__nudge__" and m.role == "tool"]
check("il nudge e' nel contesto", len(nudge3) == 1)
if nudge3:
    testo3 = nudge3[0].content
    check("il nudge non dice il falso 'non hai usato nessuno strumento'",
          "non hai ancora usato nessuno strumento" not in testo3,
          "il testo e' quello del caso senza tool")
    check("il nudge chiede di finire o dirlo esplicitamente",
          "hai annunciato altro lavoro" in testo3, testo3[:80])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
