"""Un job cron non deve essere una shell senza guardie.

Il caso: `cron` accettava `action_type=shell` e `command` senza passare da
`verifica_comando`; lo scheduler eseguiva con `subprocess.run(...,
shell=True)` e l'ambiente del processo padre. Un bot senza `run_shell`
poteva quindi creare un job e ottenere lo stesso comando, in modo
persistente, con tutte le chiavi API in ambiente.

Qui si prova: il comando fuori root viene rifiutato alla creazione e
all'aggiornamento; un job vecchio viene fermato anche all'esecuzione;
l'ambiente del figlio non contiene un segnaposto del padre.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="cron-sicurezza-")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.environ["ORCHESTRA_ROOT"] = os.path.join(_TMP, "root")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.makedirs(os.environ["ORCHESTRA_ROOT"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import cron as cron_mod  # noqa: E402
from orchestra.tools.cron import tool_cron  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


fuori = tempfile.mkdtemp(prefix="cron-fuori-")
file_fuori = os.path.join(fuori, "segreto.txt")
with open(file_fuori, "w", encoding="utf-8") as f:
    f.write("non doveva essere letto\n")

print("[1] Un comando normale si puo' ancora programmare")
job = cron_mod.crea("normale", "@daily", "shell", {"command": "echo ciao"})
check("il job e' creato", bool(job.get("id")), str(job))
check("lo schedule e' normalizzato", job.get("schedule") == "0 0 * * *",
      str(job.get("schedule")))

print("\n[2] Un percorso fuori dalla root viene rifiutato")
try:
    cron_mod.crea("cattivo", "@daily", "shell",
                  {"command": "cat " + file_fuori})
    check("crea rifiuta il percorso fuori root", False, "nessuna eccezione")
except ValueError as e:
    check("crea rifiuta il percorso fuori root",
          "NON ESEGUITO" in str(e) or "fuori" in str(e), str(e))

print("\n[3] Anche l'aggiornamento passa dal controllo")
try:
    cron_mod.aggiorna(job["id"], action={"command": "cat " + file_fuori})
    check("aggiorna rifiuta il percorso fuori root", False, "nessuna eccezione")
except ValueError as e:
    check("aggiorna rifiuta il percorso fuori root",
          "NON ESEGUITO" in str(e) or "fuori" in str(e), str(e))

print("\n[4] Un job vecchio, mai validato, viene fermato all'esecuzione")
legacy = {
    "id": "legacy",
    "nome": "legacy",
    "schedule": "@daily",
    "action_type": "shell",
    "action": {"command": "cat " + file_fuori},
    "enabled": True,
    "created_at": "2026-01-01T00:00:00",
    "last_run": None,
    "next_run": None,
    "last_status": "",
    "last_output": "",
    "run_count": 0,
}
cron_mod._save([legacy])
r = cron_mod.esegui_job("legacy")
check("l'esecuzione non e' riuscita", not r.get("ok"), str(r))
check("il motivo e' esplicito",
      "NON ESEGUITO" in str(r.get("error", "")) or "fuori" in str(r.get("error", "")),
      str(r.get("error")))
check("il file fuori non e' stato letto",
      "non doveva" not in str(r.get("stdout", "")), str(r.get("stdout")))

print("\n[5] L'ambiente del job non contiene i segreti del padre")
os.environ["CANARY_CRON"] = "segreto-del-padre"
cmd = "set" if os.name == "nt" else "env"
job_env = cron_mod.crea("ambiente", "@daily", "shell", {"command": cmd})
r = cron_mod.esegui_job(job_env["id"])
uscita = (r.get("stdout") or "") + (r.get("stderr") or "")
check("il job e' partito", r.get("ok"), str(r))
check("il segnaposto del padre non e' nell'ambiente",
      "CANARY_CRON" not in uscita, uscita[:200])
del os.environ["CANARY_CRON"]

print("\n[6] La modifica parziale non riscrive enabled e action_type")
# `enabled=True` e `action_type="goal"` erano i default della firma, e
# finivano sempre nei campi aggiornati: modificare lo schedule di un job
# spento lo riaccendeva, e cambiare il comando di un job shell lo
# trasformava in un goal che poi falliva con "obiettivo mancante".
cron_tool = tool_cron()
j = cron_mod.crea("parziale", "@daily", "shell",
                  {"command": "echo ciao"}, enabled=False)
r = cron_tool.handler(azione="modifica", id=j["id"], schedule="@hourly")
agg = cron_mod.get(j["id"]) or {}
check("lo schedule e' cambiato", agg.get("schedule") == "0 * * * *",
      str(agg.get("schedule")))
check("enabled resta False", agg.get("enabled") is False,
      str(agg.get("enabled")))
check("action_type resta shell", agg.get("action_type") == "shell",
      str(agg.get("action_type")))
check("il comando resta quello",
      (agg.get("action") or {}).get("command") == "echo ciao",
      str(agg.get("action")))

r = cron_tool.handler(azione="modifica", id=j["id"], command="echo nuovo")
agg = cron_mod.get(j["id"]) or {}
check("cambiare solo command resta shell",
      agg.get("action_type") == "shell"
      and (agg.get("action") or {}).get("command") == "echo nuovo",
      str(agg))
check("e non riattiva il job", agg.get("enabled") is False,
      str(agg.get("enabled")))

cron_tool.handler(azione="modifica", id=j["id"], enabled=True)
agg = cron_mod.get(j["id"]) or {}
check("enabled esplicito lo riattiva", agg.get("enabled") is True,
      str(agg.get("enabled")))

g = cron_mod.crea("goal-parziale", "@daily", "goal",
                  {"objective": "fare cose", "profile": "base"},
                  enabled=False)
cron_tool.handler(azione="modifica", id=g["id"], nome="rinominato")
agg = cron_mod.get(g["id"]) or {}
check("goal: action_type resta goal", agg.get("action_type") == "goal",
      str(agg.get("action_type")))
check("goal: enabled resta False", agg.get("enabled") is False,
      str(agg.get("enabled")))
check("goal: l'obiettivo resta",
      (agg.get("action") or {}).get("objective") == "fare cose",
      str(agg.get("action")))

print("\n[7] Cambiare solo l'obiettivo non resetta il profilo ad auto")
g = cron_mod.crea("goal-profilo", "@daily", "goal",
                  {"objective": "prima", "profile": "base"})
r = cron_tool.handler(azione="modifica", id=g["id"],
                      objective="seconda")
agg = cron_mod.get(g["id"]) or {}
check("l'obiettivo e' cambiato",
      (agg.get("action") or {}).get("objective") == "seconda",
      str(agg.get("action")))
check("il profilo resta base",
      (agg.get("action") or {}).get("profile") == "base",
      str(agg.get("action")))

# Anche il modulo, chiamato direttamente, deve conservare il profilo.
cron_mod.aggiorna(g["id"], action={"objective": "terza"})
agg = cron_mod.get(g["id"]) or {}
check("aggiorna diretto conserva il profilo",
      (agg.get("action") or {}).get("profile") == "base",
      str(agg.get("action")))

cron_tool.handler(azione="modifica", id=g["id"],
                  objective="quarta", profile="pieno")
agg = cron_mod.get(g["id"]) or {}
check("un profilo esplicito viene applicato",
      (agg.get("action") or {}).get("profile") == "pieno",
      str(agg.get("action")))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
