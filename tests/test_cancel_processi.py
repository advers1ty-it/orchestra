"""Annullare deve fermare il comando, non solo il turno.

`request_cancel()` alzava un flag che il loop leggeva quando il tool
tornava: per un `sleep 300` o un `npm install` il ritorno arrivava alla
fine naturale, e l'utente vedeva "annullato" mentre il processo
continuava a scrivere sul disco.

Qui si avvia un comando che dorme, si annulla la sessione, e si verifica
che il comando sia morto davvero: il file che scriverebbe alla fine non
esiste, e il turno si chiude in pochi secondi invece che dopo la dormita.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "_probe_cancel_processi")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import LLMResponse, LoopConfig  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.tools import _guard  # noqa: E402
from orchestra.types import ToolCall, ToolRegistry  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


# Lo script segna di essere partito, dorme, e scrive "finito" solo se
# arriva alla fine. Il primo file serve al test per non annullare prima
# che il processo esista (una corsa che renderebbe il test instabile).
SCRIPT = os.path.join(WORK, "lento.py")
PARTITO = os.path.join(WORK, "partito.txt")
FINITO = os.path.join(WORK, "finito.txt")
for p in (PARTITO, FINITO):
    try:
        os.remove(p)
    except OSError:
        pass
with open(SCRIPT, "w", encoding="utf-8") as f:
    f.write(
        "import time, pathlib\n"
        f"pathlib.Path({PARTITO!r}).write_text('x')\n"
        "time.sleep(30)\n"
        f"pathlib.Path({FINITO!r}).write_text('x')\n"
    )

class AvviaLento:
    """Chiede una volta il comando lento, poi una risposta finale."""

    def __init__(self):
        self.n = 0
        self.name = "avvia_lento"
        self.model = "m"

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.n > 1:
            return LLMResponse(content="fine", model="m")
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(
                # Percorso RELATIVO: la root del turno e' questa
                # cartella, e un percorso assoluto all'interprete
                # finirebbe fuori dalla root (il guard lo negherebbe).
                id="t1", name="run_shell",
                arguments='{"command": "python lento.py"}',
            )],
            model="m",
        )


reg: ToolRegistry = ToolRegistry()
_rsh = default_registry().get("run_shell")
if _rsh is None:
    raise SystemExit("run_shell non e' nel registro di default")
reg.register(_rsh)


def attesa(condizione, secondi: float = 15.0) -> bool:
    fine = time.time() + secondi
    while time.time() < fine:
        if condizione():
            return True
        time.sleep(0.05)
    return False


print("== il processo parte e viene registrato ==")

s = Session(provider=AvviaLento(), registry=reg, system_prompt="SYS",
            config=LoopConfig(max_iterations=3))
s.send("lancia")
check("il comando lento e' partito",
      attesa(lambda: os.path.exists(PARTITO), 15),
      "il file 'partito' non e' comparso: il comando non e' mai partito")

# Il registro e' per thread: finche' il turno gira, il thread del turno
# deve avere almeno un processo.
check("il processo e' nel registro del turno",
      attesa(lambda: len(_guard._PROC) > 0, 5),
      f"registro={_guard._PROC}")

print("\n== annullare uccide il processo, subito ==")

t0 = time.time()
s.cancel()
s.wait(timeout=15)
durata = time.time() - t0
check("il turno si chiude senza aspettare la dormita", durata < 10,
      f"ha impiegato {durata:.1f}s: il processo non e' stato ucciso")
check("la sessione non e' piu' occupata", not s._busy)

# Il processo ucciso non deve arrivare in fondo: se ci arriva, e' vivo.
time.sleep(2.5)
check("il comando non e' arrivato alla fine", not os.path.exists(FINITO),
      "il file 'finito' esiste: il processo ha continuato a girare")

testi = []
for m in s.agent.state.messages:
    if m.role == "tool":
        testi.append(str(m.content))
check("il risultato dice che e' stato interrotto",
      any("INTERROTTO" in t for t in testi),
      f"risultati={[t[:80] for t in testi]}")

print("\n== il registro e' per thread ==")

check("termina_processi su un thread vuoto non fa nulla",
      _guard.termina_processi(123456789) == 0)
check("il registro del turno e' stato svuotato",
      len(_guard._PROC) == 0, f"registro={_guard._PROC}")

# Un processo registrato in un thread non deve essere ucciso annullando
# un ALTRO thread: due sessioni aperte non si ammazzano i comandi.
import threading  # noqa: E402


class Finto:
    pid = 999999
    ucciso = False


finto = Finto()
pronto = threading.Event()
vai = threading.Event()


def altro_thread():
    _guard.registra_processo(finto)
    pronto.set()
    vai.wait(5)


t = threading.Thread(target=altro_thread, daemon=True)
t.start()
pronto.wait(5)
check("annullare questo thread non tocca un altro thread",
      _guard.termina_processi() == 0)
check("il processo dell'altro thread e' ancora registrato",
      len(_guard._PROC) == 1, f"registro={_guard._PROC}")
vai.set()
t.join(timeout=5)
_guard.termina_processi(t.ident)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
