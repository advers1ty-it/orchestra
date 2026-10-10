"""La delega: un figlio che risponde, e uno che non può.

Un sub-agente che torna con una risposta sembra funzionare anche
quando sta facendo solo tre cose: non delega in_loop, non confonde
"errore" con "risposta", e non costa una cifra che nessuno guarda.

Il terzo è il più subdolo. Una delega che costa più di fare il
lavoro in prima persona funziona — produce la risposta giusta — e
non si nota mai, perché nessuno guarda il conto. Per questo il
Delegatore tiene il conto da solo e lo restituisce.

E il test del figlio che delega a sua volta: non verifico che il
modello "non dovrebbe" farlo, verifico che il TOOL non sia nel suo
registro. Un tetto messo nelle istruzioni è un tetto che un modello
dimentica al quarto passo.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.delega import (  # noqa: E402
    Delegatore, Figlio,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


from orchestra.agent import AgentState          # noqa: E402
from orchestra.types import Message              # noqa: E402


def stato_reale(finale="", iterazioni=2, fermo="risposta_finale"):
    """Un AgentState VERO, costruito coi campi che ha davvero.

    Prima qui c'era una classe `Stato` con `.finale`, `.iterazioni` e
    `.uso` — tre campi che AgentState NON ha. I test passavano, e
    passavano la mia immaginazione dell'interfaccia invece di quella.

    Il risultato e' stato un modulo che leggeva `finale`, non lo
    trovava, e tornava con il vuoto: sembrava un modello muto, e il
    vuoto e' indistinguibile da un modello che non risponde. Un test
    che usa la struttura vera smette di poter essere sbagliato su un
    nome.
    """
    return AgentState(
        messages=[Message(role="user", content="domanda"),
                  Message(role="assistant", content=finale)],
        iterations=iterazioni,
        stopped_because=fermo,
    )


class FiglioFalso:
    """Un agente finto che registra cosa gli e' stato chiesto."""

    def __init__(self, risposta="fatto", passi=2, alza=None,
                 fermo="risposta_finale"):
        self.risposta = risposta
        self.passi = passi
        self.alza = alza
        self.fermo = fermo
        self.ricevuto = []

    def run(self, testo):
        self.ricevuto.append(testo)
        if self.alza:
            raise self.alza
        return stato_reale(self.risposta, self.passi, self.fermo)


print("[1] Il padre riceve solo la risposta, non il trascorso")
f = FiglioFalso("Il file contiene 42 righe.")
d = Delegatore(lambda t: f)
r = d.delega("quante righe ha risposta.txt?")
check("ha risposto", r.ok, r.esito)
check("il testo e' quello del figlio", "42 righe" in r.testo)
check("e non ha importato passi", "passo" not in r.testo.lower(),
      r.testo[:60])
check("il padre ha visto il passaggio una volta sola", len(f.ricevuto) == 1)

print("\n[2] Il contesto viaggia, ma non la conversazione")
f2 = FiglioFalso("ok")
d2 = Delegatore(lambda t: f2)
d2.delega(" conta le righe ", " il file e' risposta.txt, in D:/orchestra ")
ricevuto = f2.ricevuto[0]
check("il contesto c'e'", "risposta.txt" in ricevuto, ricevuto[:60])
check("l'obiettivo c'e'", "conta le righe" in ricevuto, ricevuto[:60])
check("e non c'e' traccia di unprompt di sistema",
      "system" not in ricevuto.lower(), ricevuto[:60])

print("\n[3] Un figlio che va in errore NON e' una risposta")
def esplode(testo):
    raise RuntimeError("provider chiuso")

d3 = Delegatore(esplode)
r3 = d3.delega("qualcosa")
check("non ha sollevato", True)
check("l'esito e' errore, non risposto", r3.esito == "errore", r3.esito)
check("il padre lo vede scritto", "non e' un risultato" in r3.per_il_padre())
check("e sa cosa e' successo", "provider chiuso" in r3.motivo, r3.motivo)

print("\n[4] Esaurito e' diverso da risposto, e lo dice")
r4 = Figlio("esaurito", "", passi=12, motivo="finito")
check("non e' ok", not r4.ok)
check("il padre vede che non ha risposto",
      "non e' un risultato" in r4.per_il_padre())
r5 = Figlio("risposto", "", passi=1)
check("e una risposta vuota non viene trattata come esaurita",
      r5.esito == "risposto")

print("\n[5] Un figlio che non produce niente e' un errore, non un vuoto")
f6 = FiglioFalso("")
d6 = Delegatore(lambda t: f6)
r6 = d6.delega("qualcosa")
check("l'esito e' errore", r6.esito == "errore", r6.esito)
check("e il motivo lo dice", "risposta finale" in r6.motivo, r6.motivo)

print("\n[6] Il tetto di profondita: un figlio NON delega")
d7 = Delegatore(lambda t: FiglioFalso(), profondita=1)
puo, perche_no = d7.puo_delegare()
check("non puo' delegare", not puo)
check("e il perche' e' scritto", "profondità massima" in perche_no, perche_no)
r7 = d7.delega("prova")
check("torna Figlio errore invece di alzare", r7.esito == "errore")

print("\n[7] Il conto dei figli e dei costi")
d8 = Delegatore(lambda t: FiglioFalso("ok", 3), max_figli=2)
r8a = d8.delega("primo")
r8b = d8.delega("secondo")
r8c = d8.delega("terzo")
check("il terzo viene rifiutato", r8c.esito == "errore")
check("il perche' lo dice", "troppi figli" in r8c.motivo)
check("conto corretto", d8.n_figli == 2)

print("\n[8] Profilo di uso: quante deleghe sono state utili")
check("due su tre utili", d8.resoconto().startswith("3 deleghe, 2 utili"))

if FAIL:
    print("\nFAIL:", FAIL)
    sys.exit(1)
else:
    print("\nTUTTI OK")
