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
    PASSI_MAX, PROFONDITA_MAX, Delegatore, Figlio,
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
r4 = Figlio("esaurito", "", passi=PASSI_MAX, motivo="finito")
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
d7 = Delegatore(lambda t: FiglioFalso(), profondita=PROFONDITA_MAX)
puo, perche_no = d7.puo_delegare()
check("non puo' delegare", not puo)
check("e il perche' e' scritto", "profondità massima" in perche_no, perche_no)
r7 = d7.delega("prova")
check("la delega rifiutata non solleva", r7.esito == "errore", r7.esito)
check("e dice perche'", "profondità" in r7.motivo, r7.motivo)

print("\n[7] Il tetto di profondita e' nel REGISTRO, non nelle istruzioni")
# Il punto intero della regola: che il figlio non abbia lo strumento.
# Non basta scrivere "non delegare" nel prompt.
d8 = Delegatore(lambda t: FiglioFalso())
check("il padre e' a profondita 0", d8.profondita == 0)
check("e puo' delegare", d8.puo_delegare()[0])
check("il tetto e' dichiarato come numero", PROFONDITA_MAX == 1,
      str(PROFONDITA_MAX))
# un figlio costruito dal delegatore ha profondita 1, non 0
figlio_delegante = Delegatore(lambda t: FiglioFalso(), profondita=1)
check("il figlio costruito da un padre e' gia' al tetto",
      not figlio_delegante.puo_delegare()[0])

print("\n[8] Il tetto di figli")
d9 = Delegatore(lambda t: FiglioFalso(), max_figli=2)
for i in range(2):
    d9.delega(f"lavoro {i}")
puo9, perche9 = d9.puo_delegare()
check("al terzo non puo'", not puo9)
check("e spiega che e' un tetto", "tetto" in perche9, perche9)

print("\n[9] Il costo: noto con la tariffa, DICHIARATO senza")
# Prima questo test pretendeva 0.06 USD da un AgentState che non ha
# un campo costo. Il modulo rispondeva 0.0, il test passava, e il
# resoconto stampava "0.0000 USD", che vuol dire "questa delega e' stata
# gratis". Non lo sapevamo: non lo sapeva nessuno.
d10 = Delegatore(lambda t: FiglioFalso())
d10.delega("uno")
d10.delega("due")
check("senza tariffa il costo e' sconosciuto",
      d10.costo_totale is None, str(d10.costo_totale))
check("e il resoconto LO DICE, non stampa uno zero",
      "costo non noto" in d10.resoconto(), d10.resoconto())
check("e non stampa 0.0000", "0.0000" not in d10.resoconto(),
      d10.resoconto())

d10b = Delegatore(lambda t: FiglioFalso(), tariffa=lambda tk: tk * 0.001)
d10b.delega("uno")
d10b.delega("due")
check("con la tariffa lo calcola", d10b.costo_totale is not None,
      str(d10b.costo_totale))
check("e il resoconto porta i soldi",
      "USD" in d10b.resoconto() and "non noto" not in d10b.resoconto(),
      d10b.resoconto())
check("e ha contato i figli", len(d10b.storia) == 2, str(len(d10b.storia)))

print("\n[10] Una delega che non serve viene dichiarata, non nascosta")
d11 = Delegatore(esplode)
d11.delega("a")
d11.delega("b")
r11 = d11.resoconto()
check("dice 0 utili su 2", "0 utili" in r11, r11)
check("e li ha contati lo stesso", "2 deleghe" in r11, r11)

print("\n[11] Il modello del figlio e' scelto sulla SUA domanda")
scelte = []
def scegli(obiettivo):
    scelte.append(obiettivo)
    return "piccolo/gratis"

d12 = Delegatore(lambda t: FiglioFalso(), scegli_modello=scegli)
r12 = d12.delega(" Conta i file .py nella cartella ")
check("ha scelto un modello", r12.modello == "piccolo/gratis", r12.modello)
check("scegliendo sulla domanda del FIGLIO, non su quella del padre",
      scelte and "file .py" in scelte[0], str(scelte))

print("\n[12] Se la scelta del modello fallisce, si delega lo stesso")
def scegli_morto(obiettivo):
    raise RuntimeError("catalogo non caricato")

d13 = Delegatore(lambda t: FiglioFalso("fatto"), scegli_modello=scegli_morto)
r13 = d13.delega("qualcosa")
check("ha delegato lo stesso", r13.ok, r13.esito)
check("e il modello resta vuoto, dichiarato", r13.modello == "", r13.modello)
check("non si e' fermato per un problema non suo", r13.testo == "fatto")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)