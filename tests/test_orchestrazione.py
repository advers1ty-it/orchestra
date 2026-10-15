"""Scheduler, accettazione e recovery: i tre pezzi che mancavano.

Niente provider, niente rete, niente server: qui si verifica la logica
dell'orchestratore — ordine di esecuzione, gate di accettazione e retry
della delega. I giri veri col modello restano negli e2e.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


TMP = tempfile.mkdtemp(prefix="orchestrazione-")
os.environ["ORCHESTRA_HOME"] = TMP

from orchestra import goal as G  # noqa: E402
from orchestra.accettazione import (  # noqa: E402
    valuta_criteri, valuta_fine_base, valuta_goal,
)
from orchestra.delega import Delegatore, Figlio  # noqa: E402
from orchestra.recupero import PoliticaRecupero, delega_con_recupero  # noqa: E402
from orchestra.types import Message  # noqa: E402


class Stato:
    def __init__(self, fermo, testi, tokens=0):
        self.stopped_because = fermo
        self.total_tokens = tokens
        self.messages = [Message(role="assistant", content=t) for t in testi]


print("[1] Scheduler: dipendenze e priorita'")
piano = G.create("piano di prova", kind="piano")
a = G.create("primo passo", parent_id=piano)
b = G.create("secondo passo", parent_id=piano, depends_on=[a])
c = G.create("indipendente urgente", priority=10)
pronto = G.prossimo_pronto()
check("prima il goal urgente per priorita'", pronto and pronto["id"] == c, str(pronto and pronto["id"]))
G.update(c, status="done")
pronto = G.prossimo_pronto()
check("poi il primo passo, non il secondo", pronto and pronto["id"] == a, str(pronto and pronto["id"]))
check("il secondo aspetta il primo", "in attesa di" in G.motivo_non_pronto(G.get(b)), G.motivo_non_pronto(G.get(b)))
check("il piano non si esegue", "non si eseguono" in G.motivo_non_pronto(G.get(piano)), G.motivo_non_pronto(G.get(piano)))

print("\n[2] Scheduler: tempi e validazione")
futuro = G.create("non ancora", not_before=9999999999.0)
check("schedulato nel futuro non e' pronto", "futuro" in G.motivo_non_pronto(G.get(futuro)), G.motivo_non_pronto(G.get(futuro)))
try:
    G.create("dipendenza fantasma", depends_on=["g_nonexistent"])
    check("dipendenza sconosciuta rifiutata", False, "accettata")
except ValueError as e:
    check("dipendenza sconosciuta rifiutata", "sconosciuta" in str(e), str(e))
x = G.create("nodo x")
y = G.create("nodo y", depends_on=[x])
try:
    G.aggiorna(x, depends_on=[y])
    check("ciclo rifiutato", False, "accettato")
except ValueError as e:
    check("ciclo rifiutato", "circolari" in str(e), str(e))

print("\n[3] Piani: chiusura automatica")
G.update(a, status="done")
G.update(b, status="done")
n = G.aggiorna_piani()
check("piano chiuso", n >= 1 and G.get(piano)["status"] == "done", f"{n} {G.get(piano)['status']}")

print("\n[4] Retry goal: fallimento con tentativi residui")
r = G.create("riprovabile", max_attempts=2)
G.update(r, attempts=1, status="running")
g = G._aggiorna_dopo_fallimento(r, "boom")
check("torna pending con backoff", g["status"] == "pending" and g["not_before"] > 0, str(g))
check("il motivo resta scritto", "boom" in g["error"] and "retry" in g["error"], g["error"])
G.update(r, attempts=2, status="running")
g = G._aggiorna_dopo_fallimento(r, "boom")
check("esausti i tentativi diventa failed", g["status"] == "failed", g["status"])

print("\n[5] Accettazione base")
check("risposta finale non vuota ok",
      valuta_fine_base(Stato("risposta_finale", ["fatto"])).ok)
check("risposta finale vuota ko",
      not valuta_fine_base(Stato("risposta_finale", ["  "])).ok)
check("max_iterations ko di default",
      not valuta_fine_base(Stato("max_iterations", ["quasi fatto"])).ok)
check("max_iterations ok se parziale consentito",
      valuta_fine_base(Stato("max_iterations", ["quasi fatto"]),
                       consenti_parziale=True).ok)

print("\n[6] Accettazione: criteri dichiarativi")
root = tempfile.mkdtemp(prefix="criteri-")
with open(os.path.join(root, "report.md"), "w", encoding="utf-8") as fh:
    fh.write("# Report\ntotale 42\n")
check("file_contiene ok",
      valuta_criteri([{"tipo": "file_contiene", "percorso": "report.md",
                       "testo": "totale 42"}], radice=root,
                     output="qualcosa").ok)
check("traversal rifiutato",
      not valuta_criteri([{"tipo": "file_esiste", "percorso": "../x"}],
                         radice=root).ok)
check("assoluto rifiutato",
      not valuta_criteri([{"tipo": "file_esiste",
                           "percorso": os.path.join(root, "report.md")}],
                         radice=root).ok)
check("tipo sconosciuto rifiutato",
      not valuta_criteri([{"tipo": "magia"}], radice=root).ok)
check("output_contiene ko",
      not valuta_goal(Stato("risposta_finale", ["fatto"]),
                      criteri=[{"tipo": "output_contiene",
                                "testo": "numero 42"}]).ok)

print("\n[7] Recovery delega: retry, tetti, modelli")
chiamate = {"n": 0}


class AgenteOk:
    def run(self, testo):
        return Stato("risposta_finale", ["risultato"])


def fabbrica_alterna(testo):
    chiamate["n"] += 1
    if chiamate["n"] == 1:
        raise RuntimeError("figlio caduto")
    return AgenteOk()


d = Delegatore(fabbrica_alterna)
f = delega_con_recupero(d, "compito", policy=PoliticaRecupero(max_retry=1))
check("retry riuscito", f.esito == "risposto", f.esito)
check("due tentativi registrati", len(d.storia) == 2, str(len(d.storia)))

chiamate["n"] = 0
d0 = Delegatore(fabbrica_alterna)
f0 = delega_con_recupero(d0, "compito")
check("default senza retry", f0.esito == "errore" and len(d0.storia) == 1,
      f"{f0.esito} {len(d0.storia)}")

d1 = Delegatore(lambda t: AgenteOk(), profondita=1)
f1 = delega_con_recupero(d1, "compito", policy=PoliticaRecupero(max_retry=3))
check("tetto strutturale non ritentato",
      f1.esito == "errore" and len(d1.storia) == 1, f"{f1.esito} {len(d1.storia)}")

modelli = []


def hook(m):
    modelli.append(m)


d2 = Delegatore(fabbrica_alterna, max_figli=10)
chiamate["n"] = 0
f2 = delega_con_recupero(
    d2, "compito", contesto="x" * 5000,
    policy=PoliticaRecupero(max_retry=1, modelli_alternativi=["modello-b"],
                            accorcia_contesto=True, max_contesto_chars=300),
    imposta_modello=hook,
)
check("modello alternativo usato al retry", modelli[1:2] == ["modello-b"], str(modelli))
check("hook ripristinato", modelli[-1] is None, str(modelli))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
