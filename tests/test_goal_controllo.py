"""Controllo dei goal: contesto esplicito, stop e ripresa dopo un riavvio.

Questi test non chiamano un provider: sostituiscono `Agent` con un finto
che registra la root e puo' annullare il goal mentre il turno gira. E'
l'integrazione che conta — un `should_continue` solo dichiarato ma mai
passato a `agent.run` non fermerebbe niente, e un `running` rimasto nel
file non verrebbe mai ripreso.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


TMP = tempfile.mkdtemp(prefix="goal-controllo-")
os.environ["ORCHESTRA_HOME"] = TMP
root_a = os.path.join(TMP, "progetto-a")
root_b = os.path.join(TMP, "progetto-b")
os.makedirs(root_a)
os.makedirs(root_b)

from orchestra import goal as G  # noqa: E402
from orchestra import progetti as PR  # noqa: E402

PR.registra("Controllo", root_a)


class Stato:
    def __init__(self, fermo="risposta_finale"):
        self.stopped_because = fermo
        self.total_tokens = 7
        self.messages = [SimpleNamespace(role="assistant", content="fatto")]


class AgentFinto:
    mode = "ok"
    visto: dict = {}

    def __init__(self, *args, **kwargs):
        self.progetto = ""
        self.on_event = kwargs.get("on_event") or (lambda *a, **k: None)

    def run(self, testo, should_continue=None):
        from orchestra.tools._guard import _root
        gid = AgentFinto.visto.get("gid")
        AgentFinto.visto = {
            "gid": gid,
            "root": str(_root()),
            "project": getattr(self, "progetto", ""),
            "should_continue": callable(should_continue),
        }
        if AgentFinto.mode == "cancel":
            G.cancel(gid)
            if should_continue is not None and not should_continue(None):
                return Stato("canceled_da_should_continue")
        # Il testo finale lo produce l'evento, come nel loop vero. Il
        # provider non-streaming invece non emette niente: il suo testo
        # resta nel messaggio assistant dello stato.
        if AgentFinto.mode != "senza_eventi":
            self.on_event("testo", {"testo": "lavoro fatto"})
        return Stato()


print("\n[1] Progetto e root espliciti")
try:
    G.create("contesto sbagliato", project="Controllo", root=root_b)
    check("progetto e root diversi rifiutati", False, "accettato")
except ValueError as e:
    check("progetto e root diversi rifiutati", "non coincidono" in str(e), str(e))

try:
    G.create("progetto fantasma", project="NonEsiste")
    check("progetto sconosciuto rifiutato", False, "accettato")
except ValueError as e:
    check("progetto sconosciuto rifiutato", "sconosciuto" in str(e), str(e))

g_proj = G.create("lavora nel progetto", project="Controllo")
riga = G.get(g_proj) or {}
check("il goal salva il progetto",
      riga.get("project") == "Controllo", str(riga.get("project")))
check("il goal salva la root del progetto",
      os.path.realpath(str(riga.get("root"))) == os.path.realpath(root_a),
      str(riga.get("root")))

g_root = G.create("lavora in una cartella", root=root_b)
riga_root = G.get(g_root) or {}
check("la root esplicita resta nel goal",
      os.path.realpath(str(riga_root.get("root"))) == os.path.realpath(root_b),
      str(riga_root.get("root")))

print("\n[2] Annullamento di pending e running")
p = G.create("pending da annullare", root=root_b)
check("cancel accetta un pending", G.cancel(p) is True)
check("il pending diventa cancelled",
      (G.get(p) or {}).get("status") == "cancelled")
check("una seconda cancel non trova piu' niente", G.cancel(p) is False)

r = G.create("running da annullare", root=root_b)
G.update(r, status="running")
check("cancel accetta un running", G.cancel(r) is True)
rr = G.get(r) or {}
check("il running diventa cancelled",
      rr.get("status") == "cancelled" and rr.get("cancelled") is True)

print("\n[3] Riavvio: running orfano riconciliato")
s = G.create("interrotto dal riavvio", root=root_b)
G.update(s, status="running", attempts=1)
check("un running senza thread viene trovato", G.riconcilia_running() >= 1)
sg = G.get(s) or {}
check("torna pending dopo il riavvio", sg.get("status") == "pending",
      str(sg.get("status")))
check("l'errore dice perche'", "riavvio" in str(sg.get("error")),
      str(sg.get("error")))
check("il tentativo interrotto non viene consumato",
      sg.get("attempts") == 0, str(sg.get("attempts")))
check("riparte subito", float(sg.get("not_before") or 0) == 0.0,
      str(sg.get("not_before")))

attivo = G.create("ancora in esecuzione", root=root_b)
G.update(attivo, status="running")
G._ATTIVI.add(attivo)
G.riconcilia_running()
check("un running vivo non viene toccato",
      (G.get(attivo) or {}).get("status") == "running")
G._ATTIVI.discard(attivo)
G.update(attivo, status="cancelled")

print("\n[4] should_continue ferma il turno e la root arriva all'agente")
import orchestra.agent as agent_mod  # noqa: E402
import orchestra.providers as providers_mod  # noqa: E402
import orchestra.fallback as fallback_mod  # noqa: E402

originale_agent = agent_mod.Agent
originale_provider = providers_mod.build_provider
originale_delega = G._attacca_delega
originale_catena = fallback_mod.catena_per_agente
agent_mod.Agent = AgentFinto
providers_mod.build_provider = lambda *a, **k: object()
G._attacca_delega = lambda *a, **k: False
fallback_mod.catena_per_agente = lambda *a, **k: []
try:
    AgentFinto.mode = "ok"
    g_run = G.create("gira nella root giusta", project="Controllo")
    G.run_goal(g_run, env={})
    check("l'agente gira nella root del goal",
          AgentFinto.visto.get("root") == os.path.realpath(root_a),
          str(AgentFinto.visto.get("root")))
    check("l'agente conosce il progetto",
          AgentFinto.visto.get("project") == "Controllo",
          str(AgentFinto.visto.get("project")))
    check("il goal completa con la risposta finale",
          (G.get(g_run) or {}).get("status") == "done",
          str((G.get(g_run) or {}).get("status")))

    AgentFinto.mode = "senza_eventi"
    g_noevent = G.create("provider senza streaming", root=root_b)
    G.run_goal(g_noevent, env={})
    riga_noevent = G.get(g_noevent) or {}
    check("un provider senza eventi usa il messaggio assistant",
          riga_noevent.get("last_output") == "fatto",
          str(riga_noevent.get("last_output")))
    check("e il goal non chiude con un risultato vuoto",
          riga_noevent.get("status") == "done",
          str(riga_noevent.get("status")))

    # Lo scheduler prenota (running) e poi chiama `run_goal`: il percorso
    # prenotato deve eseguire, non essere scambiato per un goal gia' chiuso.
    AgentFinto.mode = "ok"
    g_sched = G.create("prenotato dallo scheduler", root=root_b, priority=50)
    prenotato = G.prenota_prossimo() or {}
    check("lo scheduler prenota il goal piu' urgente",
          prenotato.get("id") == g_sched, str(prenotato.get("id")))
    G.run_goal(g_sched, env={})
    check("un goal prenotato viene eseguito",
          (G.get(g_sched) or {}).get("status") == "done",
          str((G.get(g_sched) or {}).get("status")))

    AgentFinto.mode = "cancel"
    g_stop = G.create("fermati durante il turno", root=root_b)
    AgentFinto.visto["gid"] = g_stop
    G.run_goal(g_stop, env={})
    check("should_continue viene passato ad agent.run",
          AgentFinto.visto.get("should_continue") is True)
    fermo = G.get(g_stop) or {}
    check("il turno annullato chiude il goal come cancelled",
          fermo.get("status") == "cancelled", str(fermo))
    check("il goal annullato non resta attivo",
          g_stop not in G._ATTIVI)
finally:
    agent_mod.Agent = originale_agent
    providers_mod.build_provider = originale_provider
    G._attacca_delega = originale_delega
    fallback_mod.catena_per_agente = originale_catena
    AgentFinto.mode = "ok"

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
