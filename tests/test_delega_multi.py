"""Più figli insieme: il tetto, la scadenza, e i risultati separati.

La delega sincrona è sbagliata per i compiti indipendenti: tre letture
che non si parlano fra loro, messe in fila, costano tre volte il tempo
della più lenta. Ma il parallelo porta tre difetti che il sincrono non
aveva, e sono i tre che questo test prova:

1. il conto dei figli si legge e si scrive da thread diversi, e un tetto
   che due thread leggono insieme non è un tetto;
2. aspettare per sempre non è aspettare: un figlio bloccato sul provider
   deve poter finire come "scaduto", che è diverso da "errore" — non si sa
   se ha sbagliato, si sa che non ha finito;
3. l'ordine dei risultati deve essere quello degli obiettivi, non quello
   in cui i figli hanno finito, altrimenti il padre attribuisce la
   risposta al compito sbagliato.

E una cosa che il test NON può verificare, e va detta: il merge. I
risultati restano separati apposta, e unirli è una decisione del padre.
"""

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Il registro dello storico non deve riempirsi di conversazioni finte:
# questo test costruisce una sessione vera, e la sessione salva.
os.environ.setdefault("ORCHESTRA_HOME", tempfile.mkdtemp(prefix="delega-multi-"))

from orchestra.delega import Delegatore, Figlio  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


from orchestra.agent import AgentState          # noqa: E402
from orchestra.types import Message              # noqa: E402


def stato_reale(finale="", iterazioni=2, fermo="risposta_finale"):
    """Un AgentState VERO, con i campi che ha davvero (vedi test_delega)."""
    return AgentState(
        messages=[Message(role="user", content="domanda"),
                  Message(role="assistant", content=finale)],
        iterations=iterazioni,
        stopped_because=fermo,
    )


class AgenteFinto:
    def __init__(self, risposta="fatto", passi=2, attesa=0.0):
        self.risposta = risposta
        self.passi = passi
        self.attesa = attesa
        self.annullato = False

    def request_cancel(self):
        self.annullato = True

    def run(self, testo):
        if self.attesa:
            # a pezzi, così `request_cancel` ha modo di arrivare durante
            # l'attesa: un figlio vero controlla il flag fra un passo e
            # l'altro, non mentre dorme
            fine = time.time() + self.attesa
            while time.time() < fine and not self.annullato:
                time.sleep(0.02)
        return stato_reale(f"risposta a: {testo}", self.passi)


print("[1] Tre obiettivi, tre risposte, l'ordine è quello degli obiettivi")
durate = {"uno": 0.6, "due": 0.6, "tre": 0.6}
pronti = {}

def fabbrica_lenta(testo):
    chiave = testo.strip()
    ag = AgenteFinto(chiave, 3, durate.get(chiave, 0.0))
    pronti[chiave] = ag
    return ag

d1 = Delegatore(fabbrica_lenta, max_paralleli=3)
t0 = time.time()
figli = d1.delega_multi(["uno", "due", "tre"], timeout=15)
durata = time.time() - t0

check("tre risultati", len(figli) == 3, str(len(figli)))
check("tutti risposti", all(f.esito == "risposto" for f in figli),
      str([f.esito for f in figli]))
check("il primo è 'uno'", "uno" in figli[0].testo, figli[0].testo)
check("il secondo è 'due'", "due" in figli[1].testo, figli[1].testo)
check("il terzo è 'tre'", "tre" in figli[2].testo, figli[2].testo)
# in fila sarebbero 1,8s. In parallelo il muro è la più lenta.
check("hanno lavorato insieme, non in fila", durata < 1.4,
      f"{durata:.2f}s per tre compiti da 0,6s")

print("\n[2] Il tetto di concorrenza vale davvero")
in_corso = {"adesso": 0, "massimo": 0}
lock = threading.Lock()


def fabbrica_contata(testo):
    return AgenteFintoContato(testo)


class AgenteFintoContato(AgenteFinto):
    def run(self, testo):
        with lock:
            in_corso["adesso"] += 1
            in_corso["massimo"] = max(in_corso["massimo"], in_corso["adesso"])
        try:
            time.sleep(0.3)
            return stato_reale(f"risposta a: {testo}", 1)
        finally:
            with lock:
                in_corso["adesso"] -= 1


d2 = Delegatore(fabbrica_contata, max_paralleli=2)
t0 = time.time()
figli2 = d2.delega_multi(["a", "b", "c", "d"], timeout=15)
durata2 = time.time() - t0
check("quattro risposte", len(figli2) == 4 and all(f.ok for f in figli2))
check("mai più di due insieme", in_corso["massimo"] <= 2,
      f"massimo {in_corso['massimo']} con tetto 2")
check("e due insieme davvero (non in fila)", in_corso["massimo"] == 2,
      f"massimo {in_corso['massimo']}")
check("due ondate, non quattro", durata2 >= 0.55, f"{durata2:.2f}s")

print("\n[3] Chi non finisce in tempo è 'scaduto', non 'errore'")
lenti = {}


def fabbrica_mista(testo):
    attesa = 2.0 if testo.strip() == "lento" else 0.05
    ag = AgenteFinto(testo.strip(), 2, attesa)
    lenti[testo.strip()] = ag
    return ag


d3 = Delegatore(fabbrica_mista, max_paralleli=2, timeout_multi=0.4)
figli3 = d3.delega_multi(["lento", "veloce"])
lento, veloce = figli3[0], figli3[1]
check("il veloce ha risposto", veloce.esito == "risposto", veloce.esito)
check("il lento è scaduto", lento.esito == "scaduto", lento.esito)
check("scaduto NON è errore", lento.esito != "errore")
check("il motivo dice che non ha finito", "non ha finito" in lento.motivo,
      lento.motivo)
check("al figlio è stato chiesto di fermarsi", lenti["lento"].annullato)
check("e il padre legge che non è un risultato",
      "non e' un risultato" in lento.per_il_padre(), lento.per_il_padre())
check("il padre non riceve un esito finto come risposta", not lento.ok)

print("\n[4] Il tetto TOTALE dei figli vale anche in parallelo")
chiamate = {"n": 0}


def fabbrica_numerata(testo):
    chiamate["n"] += 1
    return AgenteFinto(testo, 1, 0.05)


d4 = Delegatore(fabbrica_numerata, max_figli=2, max_paralleli=3)
figli4 = d4.delega_multi(["primo", "secondo", "terzo"], timeout=10)
check("il terzo è rifiutato", figli4[2].esito == "errore", figli4[2].esito)
check("e dice perché", "troppi figli" in figli4[2].motivo, figli4[2].motivo)
check("solo due figli costruiti", chiamate["n"] == 2, str(chiamate["n"]))
check("il conto è quello vero", d4.n_figli == 2, str(d4.n_figli))

print("\n[5] Un figlio non delega: il tetto vale anche su delega_multi")
d5 = Delegatore(fabbrica_numerata, profondita=1)
figli5 = d5.delega_multi(["uno", "due"])
check("nessuno parte", all(f.esito == "errore" for f in figli5),
      str([f.esito for f in figli5]))
check("e il motivo è il tetto",
      all("profondità massima" in f.motivo for f in figli5),
      str([f.motivo for f in figli5]))

print("\n[6] Il costo per figlio è del modello che ha lavorato")
visti = []


def tariffa(token):
    # se il modello non è stato ancora dichiarato, il costo non si sa:
    # è proprio l'ordine sbagliato che questo controllo coglie
    return 1.5 if visti else None


d6 = Delegatore(lambda t: AgenteFinto(t, 2, 0.0),
                scegli_modello=lambda o: "modello-x",
                tariffa=tariffa, on_modello_usato=visti.append)
figli6 = d6.delega_multi(["uno", "due", "tre"], timeout=10)
check("ogni figlio ha un costo", all(f.costo == 1.5 for f in figli6),
      str([f.costo for f in figli6]))
check("il totale somma i costi", abs((d6.costo_totale or 0) - 4.5) < 1e-9,
      str(d6.costo_totale))
check("il resoconto lo dice", "4.5000 USD" in d6.resoconto(), d6.resoconto())

print("\n[7] Una delega scaduta non si conta due volte")
d7 = Delegatore(lambda t: AgenteFinto(t, 2, 0.8), max_paralleli=1)
figli7 = d7.delega_multi(["lento"], timeout=0.2)
check("risulta scaduta", figli7[0].esito == "scaduto", figli7[0].esito)
isa = len(d7.storia)
time.sleep(1.0)   # il figlio finisce DOPO la scadenza, e lo stesso
check("una sola voce in storia", len(d7.storia) == isa,
      f"{isa} → {len(d7.storia)}: {d7.storia}")

print("\n[8] Obiettivi vuoti: nessun figlio, e lo dice")
d8 = Delegatore(fabbrica_numerata)
check("lista vuota = nessun risultato", d8.delega_multi([]) == [])
figli8 = d8.delega_multi(["", "  "])
check("obiettivo vuoto = errore", all(f.esito == "errore" for f in figli8))
check("e il motivo lo dice", all("obiettivo vuoto" in f.motivo for f in figli8))

print("\n[9] Il tool nella sessione: registrato, e il resoconto si legge")
from orchestra.session import Session                      # noqa: E402
from orchestra.tools import default_registry               # noqa: E402
from orchestra.agent import LoopConfig                     # noqa: E402


class ProviderMuto:
    name = "finto"
    model = "finto-1"

    def chat(self, messages, tools=None, **kw):
        raise AssertionError("il provider non va chiamato in questo test")


s = Session(provider=ProviderMuto(), registry=default_registry(),
            system_prompt="sei un agente",
            config=LoopConfig(max_iterations=2))
s._fabbrica_figlio = lambda testo: AgenteFinto(testo, 1, 0.05)
check("la delega si attiva", s.attiva_delega())
nomi = {t.name for t in s.registry.elenco_attivi()}
check("il padre ha `delega`", "delega" in nomi, str(sorted(nomi)))
check("e ha `delega_multi`", "delega_multi" in nomi, str(sorted(nomi)))
tool = next(t for t in s.registry.elenco_attivi()
            if t.name == "delega_multi")
testo = tool.handler(obiettivi=["uno", "due"], contesto="il contesto")
check("il resoconto numera i figli",
      "[1/2]" in testo and "[2/2]" in testo, testo[:200])
check("ogni figlio ha la sua risposta", testo.count("risposta a:") == 2,
      testo[:300])
check("dice che i risultati sono separati", "SEPARATI" in testo)
check("il contesto è arrivato ai figli", "il contesto" in testo)
check("un obiettivo vuoto non esplode",
      "serve una lista" in tool.handler(obiettivi=[]))

print("\n[10] Un profilo scelto non spegne la delega a fine turno")
from orchestra.types import LLMResponse                     # noqa: E402


class ProviderRisponde(ProviderMuto):
    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="ho finito", model="finto-1")


s2 = Session(provider=ProviderRisponde(), registry=default_registry(),
             system_prompt="sei un agente",
             config=LoopConfig(max_iterations=2, tool_profile="base"))
s2._fabbrica_figlio = lambda testo: AgenteFinto(testo, 1, 0.0)
s2.attiva_delega()
s2.send("ciao")
s2.wait(timeout=20)
nomi2 = {t.name for t in s2.registry.elenco_attivi()}
# `delega` e `delega_multi` non compaiono in nessun profilo: senza la
# riattivazione dopo `applica_profilo` il primo turno li spegneva, e
# l'agente perdeva la delega senza che niente lo dicesse.
check("`delega` sopravvive al profilo", "delega" in nomi2, str(sorted(nomi2)))
check("`delega_multi` pure", "delega_multi" in nomi2, str(sorted(nomi2)))
check("e il profilo resta quello scelto", "browser_apri" not in nomi2,
      str(sorted(nomi2)))

print("\n[11] Nei goal: i due tool ci sono, e il profilo non li spegne")
import orchestra.catalog as catalog_mod                  # noqa: E402
from orchestra.goal import _attacca_delega                # noqa: E402
from orchestra.delega import riattiva_delega              # noqa: E402
from orchestra.tools import applica_profilo               # noqa: E402

# `_attacca_delega` prova a scaricare il catalogo per far scegliere il
# modello ai figli. Nel test non c'è rete: il fallimento è previsto (la
# delega resta possibile, senza scelta del modello), ma non deve farlo
# aspettare un timeout.
_vero_fetch = catalog_mod.Catalog.fetch.__func__


def _niente_rete(cls, provider):
    raise RuntimeError("niente rete nel test")


catalog_mod.Catalog.fetch = classmethod(_niente_rete)
try:
    reg2 = default_registry()
    attiva_goal = _attacca_delega(reg2, {"ORCHESTRA_PROVIDER": "openrouter"}, 5)
finally:
    catalog_mod.Catalog.fetch = classmethod(_vero_fetch)

nomi3 = {t.name for t in reg2.elenco_attivi()}
check("il goal può delegare", attiva_goal is True, str(attiva_goal))
check("registra `delega`", "delega" in nomi3, str(sorted(nomi3)))
check("e `delega_multi`", "delega_multi" in nomi3, str(sorted(nomi3)))
tool_goal = next(t for t in reg2.elenco_attivi()
                 if t.name == "delega_multi")
check("un obiettivo vuoto non esplode nemmeno qui",
      "serve una lista" in tool_goal.handler(obiettivi=[]))

applica_profilo(reg2, "base")
check("il profilo da solo li spegne",
      "delega_multi" not in {t.name for t in reg2.elenco_attivi()})
riattiva_delega(reg2)
nomi3b = {t.name for t in reg2.elenco_attivi()}
check("`riattiva_delega` li riaccende",
      {"delega", "delega_multi"} <= nomi3b, str(sorted(nomi3b)))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
