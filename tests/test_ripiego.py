"""Il ripiego: due errori di fila e si cambia modello.

Tre cose da verificare, e la terza e' quella che il resto del progetto
insegna.

La prima: scatta al SECONDO errore, non al primo. Un modello che
sbaglia una chiamata e si corregge sta funzionando. Cambiargli modello
li' significa punire un comportamento che funziona, e il risultato e'
una sessione che cambia modello ogni tre messaggi.

La seconda: dopo aver cambiato, non cambia di nuovo al turno
successivo. Il segno `_ripiegato_su` esiste per questo. Senza, un
modello che sbaglia due volte porta a un carosello: quattro modelli
in quattro turni, nessuno che finisce un lavoro.

La terza, e quella che questo file verifica sul serio: quando il
ripiego NON c'e' — nessuna alternativa misurata — non si fa finta. Deve
dire che non ha alternative. Una decisione che non c'e', presentata
come se ci fosse, si riconosce solo dal silenzio.

Il segno si cancella quando il nuovo modello funziona: altrimenti la
s sessione non ripiega piu' per il resto della vita, il che e' un
altro modo di mentire in direzione opposta.
"""

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.routing import SOGLIA_DI_CAMBIO  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# --------------------------------------------------------------------------
# Un agente finto che sbaglia quanto gli si dice di sbagliare.
class Stato:
    def __init__(self, errori=0):
        self.consecutive_errors = errori


class Agentino:
    def __init__(self):
        self.state = Stato(0)


@dataclass
class Info:
    id: str
    short: str = ""
    is_free: bool = True


@dataclass
class Prof:
    info: Info
    scores: dict = field(default_factory=dict)
    livelli: dict = field(default_factory=dict)
    frazioni: dict = field(default_factory=dict)
    task_per_cat: dict = field(default_factory=dict)


@dataclass
class Modello:
    id: str


class Cat:
    """Un catalogo finto: tre modelli misurati, in ordine decrescente."""

    def __init__(self, ids):
        punteggi = {"a/first": 1.0, "b/secondo": 0.8, "c/terzo": 0.6}
        self.models = {
            m: Prof(info=Info(m), scores={"code": punteggi[m]},
                    livelli={"code": "l3"})
            for m in ids
        }

    def with_tools(self):
        return list(self.models.values())


class Ponte:
    """Il ponte finto: il metodo vero chiama `self.bridge.emit`."""

    def __init__(self, fuori):
        self.fuori = fuori

    def emit(self, kind, data):
        self.fuori.append((kind, data))


class Sessione:
    """La parte di Session che il ripiego tocca, e nient'altro."""

    def __init__(self, agent, catalogo=None, modello="a/first"):
        self.agent = agent
        self._catalogo_per_costo = catalogo
        self._modello = modello
        self._ripiegato_su = None
        self.eventi = []

    def modello_in_uso(self):
        return self._modello

    def cambia_modello(self, m):
        self._modello = m
        return True

    @property
    def bridge(self):
        return Ponte(self.eventi)

    # il metodo vero, rieseguito qui sopra una Sessione finta
    from orchestra.session import Session
    _ripiego_se_ripetono = Session._ripiego_se_ripetono


cat = Cat(["a/first", "b/secondo", "c/terzo"])

print("[1] Con un solo errore non succede niente")
s = Sessione(Agentino(), cat)
s.agent.state.consecutive_errors = 1
s._ripiego_se_ripetono("fai qualcosa")
check("nessun cambio", s.modello_in_uso() == "a/first", s.modello_in_uso())
check("e nessun evento", not s.eventi, str(s.eventi[:1]))
check("la soglia e' dichiarata", SOGLIA_DI_CAMBIO == 2, str(SOGLIA_DI_CAMBIO))

print("\n[2] Con due errori di fila cambia modello")
s = Sessione(Agentino(), cat)
s.agent.state.consecutive_errors = 2
s._ripiego_se_ripetono("fai qualcosa")
check("ha cambiato", s.modello_in_uso() == "b/secondo", s.modello_in_uso())
check("e l'ha detto", any(k == "routing" for k, _ in s.eventi), str(s.eventi[:1]))
motivo = next((d.get("motivo", "") for k, d in s.eventi if k == "routing"), "")
check("il motivo cita gli errori", "errori" in motivo, motivo)
check("e il nuovo modello", "b/secondo" in motivo, motivo)
check("il contatore e' azzerato", s.agent.state.consecutive_errors == 0,
      str(s.agent.state.consecutive_errors))

print("\n[3] E non cambia di nuovo al turno dopo")
s.agent.state.consecutive_errors = 2
prima = s.modello_in_uso()
s._ripiego_se_ripetono("fai qualcosa")
check("resta sullo stesso", s.modello_in_uso() == prima, s.modello_in_uso())
check("il segno e' ricordato", s._ripiegato_su == prima, str(s._ripiegato_su))

print("\n[4] Se nessuno sbaglia, il segno si cancella")
# Il caso che chiude il ciclo. Un modello ripiegato che poi funziona
# deve poter ripiegare DI NUOVO in futuro: altrimenti la sessione si
# blocca sul primo ripiego e un modello sbagliato scelto due errori fa
# addosso anche dopo tre messaggi buoni.
#
# Questo test era scritto a metà — diceva "qui il codice deve azzerare
# il segno" e non lo verificava. Il codice NON lo azzerava, e il
# docstring del metodo prometteva il contrario: la descrizione e' stata
# scritta prima dell'implementazione, e non l'ho seguita.
s = Sessione(Agentino(), cat)
s.agent.state.consecutive_errors = 2
s._ripiego_se_ripetono("primo")          # ripiega su b/secondo
check("ha ripiegato", s.modello_in_uso() == "b/secondo", s.modello_in_uso())
check("il segno c'e'", s._ripiegato_su == "b/secondo", str(s._ripiegato_su))

# un turno pulito
s.agent.state.consecutive_errors = 0
s._ripiego_se_ripetono("turno pulito")
check("il segno e' stato cancellato", s._ripiegato_su is None,
      str(s._ripiegato_su))

# e adesso, se di nuovo sbaglia due volte, ripiega una seconda volta.
#
# Qui la mia aspettativa iniziale era sbagliata: avevo scritto che
# doveva tornare "c/terzo", come se il ripiego fosse una rotazione in
# ordine. Non e' cosi', e non deve esserlo: il ripiego prende il
# MIGLIORE fra quelli che restano, e a/first ha 1.0 contro 0.6 di
# c/terzo. Torna indietro di punteggio, ma avanti rispetto al
# modello che stava sbagliando — che e' la cosa che conta.
s.agent.state.consecutive_errors = 2
s._ripiego_se_ripetono("secondo ripiego")
check("ha ripiegato ancora", s.modello_in_uso() != "b/secondo",
      s.modello_in_uso())
check("e NON e' tornato sul modello che sbagliava",
      s.modello_in_uso() == "a/first", s.modello_in_uso())
check("scegliendo il migliore fra quelli che restano",
      s.modello_in_uso() == "a/first",
      "a/first=1.0 vince su c/terzo=0.6")

print("\n[5] Senza alternative, si dice che non ce ne sono")
solo = Cat(["a/first"])
s2 = Sessione(Agentino(), solo)
s2.agent.state.consecutive_errors = 5
s2._ripiego_se_ripetono("fai qualcosa")
check("non ha cambiato", s2.modello_in_uso() == "a/first", s2.modello_in_uso())
check("e l'ha dichiarato", bool(s2.eventi), "nessun evento")
motivo2 = next((d.get("motivo", "") for k, d in s2.eventi if k == "routing"), "")
check("il motivo lo dice", "nessuna alternativa" in motivo2, motivo2)

print("\n[6] Senza catalogo non succede niente, e non si alza")
s3 = Sessione(Agentino(), None)
s3.agent.state.consecutive_errors = 9
try:
    s3._ripiego_se_ripetono("fai qualcosa")
    ok, dove = True, ""
except Exception as e:  # noqa: BLE001
    ok, dove = False, f"{type(e).__name__}: {e}"
check("non ha sollevato", ok, dove)
check("e non ha cambiato", s3.modello_in_uso() == "a/first")

print("\n[7] L'evento dice TUTTO, non solo che ha cambiato")
s4 = Sessione(Agentino(), cat)
s4.agent.state.consecutive_errors = 2
s4._ripiego_se_ripetono("fai qualcosa")
d = next((dd for k, dd in s4.eventi if k == "routing"), {})
check("ha il modello", d.get("modello") == "b/secondo", str(d.get("modello")))
check("ha il perche'", bool(d.get("motivo")), str(d.get("motivo")))
check("ha la spiegazione", bool(d.get("spiegazione")), str(d.get("spiegazione"))[:50])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)