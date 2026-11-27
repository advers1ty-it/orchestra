"""remote_stop non deve fidarsi del PID scritto in un file di stato.

Un file vecchio o modificato a mano non deve diventare un modo per
terminare un processo qualsiasi: prima si legge la command line e si
controlla che sia davvero `orchestra.cli web`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import webapp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("\n[1] Il comando viene riconosciuto")
check("accetta il server web di Orchestra",
      webapp._comando_e_orchestra(
          "python -m orchestra.cli web --host 0.0.0.0 --port 9000"))
check("accetta anche il percorso diretto di cli.py",
      webapp._comando_e_orchestra("python /opt/orchestra/cli.py web --remote"))
check("rifiuta un altro server", not webapp._comando_e_orchestra(
    "python -m http.server 8000"))
check("rifiuta un processo qualsiasi",
      not webapp._comando_e_orchestra("python -c import time;time.sleep(30)"))
check("rifiuta una stringa che nomina Orchestra senza avviarla",
      not webapp._comando_e_orchestra(
          "python -c 'print(\"orchestra.cli web\")'"))
check("rifiuta una stringa vuota", not webapp._comando_e_orchestra(""))

print("\n[2] Un PID estraneo non viene terminato")
proc = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(30)"])
try:
    time.sleep(0.2)
    tmp = tempfile.mkdtemp(prefix="remote-stop-")
    stato = os.path.join(tmp, ".remote_state.json")
    originale = webapp.REMOTE_STATE_PATH
    webapp.REMOTE_STATE_PATH = stato
    try:
        with open(stato, "w", encoding="utf-8") as f:
            json.dump({"pid": proc.pid, "port": 9999}, f)
        finto = type("Finto", (), {
            "_leggi_stato_remoto": webapp.Handler._leggi_stato_remoto,
        })()
        esito = webapp.Handler._api_remote_stop(finto, {})
        check("remote_stop rifiuta un processo non Orchestra",
              esito.get("ok") is False and "non e' un server Orchestra"
              in str(esito.get("errore")), str(esito))
        check("il processo estraneo e' ancora vivo",
              proc.poll() is None, f"exit={proc.poll()}")
        check("lo stato non piu' valido viene rimosso",
              not os.path.exists(stato))
    finally:
        webapp.REMOTE_STATE_PATH = originale
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    proc.wait(timeout=5)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
