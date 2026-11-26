"""Le istruzioni del progetto: AGENTS.md, CLAUDE.md e le altre.

Il difetto che questi controlli prevengono: un agente competente e fuori
contesto, che usa i comandi sbagliati perche' nessuno gli ha detto quali
sono. Il file esiste nel repository, e Orchestra non lo leggeva.

E il secondo difetto: le istruzioni sono del PROGETTO. Se stanno nel
prefisso costruito alla creazione della sessione, attivare un progetto
dopo non le porta, e cambiarlo lascia quelle vecchie. Devono stare nel
blocco volatile, risolte dal progetto attivo.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

TMP = tempfile.mkdtemp(prefix="orchestra_istruzioni_")
os.environ["ORCHESTRA_ROOT"] = TMP
# Anche i dati (progetti, memoria) in una cartella di prova: il blocco del
# progetto legge i file toccati da li', e non deve guardare quelli veri.
os.environ["ORCHESTRA_HOME"] = os.path.join(TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import SYSTEM_PROMPT  # noqa: E402
from orchestra import istruzioni_progetto as ip  # noqa: E402
from orchestra import webapp  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("\n[1] Senza file non si inventa niente")
ip.svuota_cache()
check("nessun file, nessun blocco", ip.blocco_prompt() == "",
      ip.blocco_prompt()[:120])


print("\n[2] AGENTS.md viene letto")
with open(os.path.join(TMP, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("# Progetto\n\n- Usa `make test`, non `pytest`.\n"
            "- Non toccare `vendor/`.\n")
blocco = ip.blocco_prompt()
check("il contenuto c'e'", "make test" in blocco and "vendor/" in blocco,
      blocco[:200])
check("il blocco dice da dove viene", "AGENTS.md" in blocco, blocco[:120])
check("il blocco e' dopo le regole di sicurezza",
      "vincono le regole di sicurezza" in blocco.lower(), blocco[:300])
check("il prefisso stabile NON porta istruzioni di progetto",
      "make test" not in webapp._prompt_base())
check("e le regole di Orchestra restano davanti",
      webapp._prompt_base().startswith(SYSTEM_PROMPT))


print("\n[3] CLAUDE.md arriva dopo, senza duplicare lo stesso testo")
with open(os.path.join(TMP, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("Stile: frasi brevi.\n")
blocco = ip.blocco_prompt()
check("ci sono entrambi", "make test" in blocco and "frasi brevi" in blocco)
check("AGENTS.md viene prima", blocco.index("AGENTS.md") < blocco.index("CLAUDE.md"))
with open(os.path.join(TMP, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# Progetto\n\n- Usa `make test`, non `pytest`.\n"
            "- Non toccare `vendor/`.\n")
ip.svuota_cache()
copia = ip.blocco_prompt()
check("lo stesso documento due volte non si ripete",
      copia.count("Non toccare `vendor/`") == 1, copia[:200])


print("\n[4] Un file enorme si tronca, e lo dice")
with open(os.path.join(TMP, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("REGOLA " + ("x" * 20000) + "FINE\n")
ip.svuota_cache()
grande = ip.blocco_prompt()
check("il blocco resta nel tetto", len(grande) <= ip.MAX_TOTALE + 300,
      str(len(grande)))
check("il troncamento e' dichiarato", "troncato" in grande, grande[-160:])


print("\n[5] Un file che non si legge non fa cadere il prompt")
ip.svuota_cache()
try:
    os.remove(os.path.join(TMP, "AGENTS.md"))
except OSError:
    pass
check("senza AGENTS.md resta CLAUDE.md", "CLAUDE.md" in ip.blocco_prompt())
check("chiamare due volte non cambia il risultato",
      ip.blocco_prompt() == ip.blocco_prompt())


print("\n[6] Al cambio progetto si rileggono le istruzioni")

P1 = tempfile.mkdtemp(prefix="orchestra_progetto_uno_")
P2 = tempfile.mkdtemp(prefix="orchestra_progetto_due_")
with open(os.path.join(P1, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("Usa `make test`, non `pytest`.\n")
with open(os.path.join(P2, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("Prima `npm run build`, poi `npm test`.\n")

from orchestra import progetti as prj  # noqa: E402
from orchestra.session import LoopConfig, Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, *a, **k):
        raise AssertionError("il test non fa turni")


def volatile_di(sess: Session) -> str:
    return next((m.content for m in sess.agent.state.messages
                 if m.role == "system" and m.name == "__contesto__"), "")


sess = Session(provider=ProviderFinto(), registry=default_registry(),
               system_prompt="PREFISSO-STABILE",
               config=LoopConfig(max_iterations=2))
prefisso = sess.agent.system_prompt

# Il percorso di un progetto si risolve dal nome, come in produzione. Il
# DB vero non si tocca: qui si sostituisce la sola funzione di lookup.
originale = prj.percorso_di
prj.percorso_di = lambda nome: {"progetto-uno": P1,
                                "progetto-due": P2}.get(nome, "")
try:
    sess.imposta_progetto("progetto-uno")
    uno = volatile_di(sess)
    check("attivando un progetto arrivano le sue istruzioni",
          "make test" in uno, uno[:300])
    check("il prefisso stabile non cambia",
          sess.agent.system_prompt == prefisso)
    check("e non contiene istruzioni di progetto",
          "make test" not in sess.agent.system_prompt)

    sess.imposta_progetto("progetto-due")
    due = volatile_di(sess)
    check("al cambio progetto arrivano le istruzioni nuove",
          "npm run build" in due, due[:300])
    check("e quelle del progetto precedente spariscono",
          "make test" not in due, due[:300])

    sess.imposta_progetto("")
    check("tornando senza progetto le istruzioni spariscono",
          "npm run build" not in volatile_di(sess), volatile_di(sess)[:200])
finally:
    prj.percorso_di = originale
    shutil.rmtree(P1, ignore_errors=True)
    shutil.rmtree(P2, ignore_errors=True)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
