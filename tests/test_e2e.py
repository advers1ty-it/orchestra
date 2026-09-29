"""Test end-to-end con l'API reale.

Chiamano davvero il provider. Vanno eseguiti solo quando la chiave c'è:
    python3 tests/test_e2e.py
Non fanno assert sulla qualità della risposta del modello (cambia ogni
settimana) ma sul CONTRATTO: il loop termina, i tool girano, i file
esistono. È il comportamento di cui il cliente si accorge.
"""

from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

WORK = os.path.join(ROOT, "_probe")
os.environ["ORCHESTRA_ROOT"] = WORK

from orchestra import Agent, LoopConfig, build_provider, load_env  # noqa: E402
from orchestra.providers import ProviderError  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402

PASS, FAIL, SKIP = [], [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def skip(name: str, why: str) -> None:
    SKIP.append(name)
    print(f"  SKIP {name} — {why}")


env = dict(os.environ)
env.update(load_env(os.path.join(ROOT, "orchestra", ".env")))

provider_name = env.get("ORCHESTRA_PROVIDER", "")
model = env.get("ORCHESTRA_MODEL", "")
if not env.get("OPENROUTER_API_KEY" if provider_name == "openrouter" else ""):
    skip("provider", f"nessuna chiave per {provider_name}")
    print(f"\nSKIP TUTTO: configura orchestra/.env prima.\nPASS {len(PASS)} FAIL {len(FAIL)} SKIP {len(SKIP)}")
    sys.exit(0)

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)


def mk_agent(system_extra="", **cfg):
    p = build_provider(provider_name, model=model, env=env)
    conf = LoopConfig(**{**{"max_iterations": 8, "context_limit": 60_000}, **cfg})
    return Agent(p, default_registry(), "Sei Orchestra, agente tecnico." + system_extra, conf)


# ------------------------------------------------------------------
print("\n[1] Task reale: scrivere codice che funziona")
a = mk_agent()
a.run(
    "Crea il file `fib.py` con una funzione `fib(n)` che restituisce il "
    "n-esimo numero di Fibonacci in modo iterativo. Poi verifica importandolo."
)
f = os.path.join(WORK, "fib.py")
check("file creato dal modello", os.path.exists(f))
if os.path.exists(f):
    src = open(f, encoding="utf-8").read()
    check("contiene la funzione richiesta", "def fib" in src, src[:150])
    # verifichiamo NOI che il codice sia corretto, non il modello
    ns: dict = {}
    try:
        exec(compile(src, "fib.py", "exec"), ns)  # noqa: S102 - è il nostro file di test
        fib = ns.get("fib")
        check("fib importabile", callable(fib))
        if callable(fib):
            check("fib(10) == 55", fib(10) == 55, f"ottenuto {fib(10)}")
            check("fib(0) == 0", fib(0) == 0, f"ottenuto {fib(0)}")
            check("fib(1) == 1", fib(1) == 1, f"ottenuto {fib(1)}")
    except Exception as e:
        check("codice eseguibile", False, f"{type(e).__name__}: {e}")

check("loop terminato", a.state.stopped_because in ("risposta_finale", "max_iterations"),
      a.state.stopped_because)
check("nessun tool crashato", a.state.tool_errors == 0, str(a.state.tool_errors))
check("token contati", a.state.total_tokens > 0, str(a.state.total_tokens))
# nota: non asseriamo 'risposta_finale'. Con una finestra di 8 iterazioni un
# modello può legittimamente spendere turni a verificare il proprio codice.
# La verifica della QUALITA' la facciamo noi sopra (fib(10)==55): assert sul
# numero di iterazioni misurerebbe la pazienza del modello, non la nostra
# correttezza, e cambia a ogni settimana.

# ------------------------------------------------------------------
print("\n[2] Tool che fallisce: l'agente deve recuperare, non bloccare")
a2 = mk_agent()
a2.run("Il file `rotta.txt` non esiste. Cercalo con list_dir, poi scrivi "
       "in `trovato.txt` cosa hai trovato.")
check("recuperato da un file inesistente", a2.state.stopped_because == "risposta_finale",
      a2.state.stopped_because)
check("ha scritto il file", os.path.exists(os.path.join(WORK, "trovato.txt")))

# ------------------------------------------------------------------
print("\n[3] Uso corretto del calcolatore (no shell, tool dedicato)")
a3 = mk_agent()
a3.run("Calcola (1234 * 5678) + 99 usando lo strumento calculate.")
calc_results = [m.content for m in a3.state.messages if m.role == "tool" and m.name == "calculate"]
check("ha usato il tool calculate", len(calc_results) > 0)
if calc_results:
    check("risultato corretto", calc_results[0].strip() == str(1234 * 5678 + 99),
          f"ottenuto {calc_results[0].strip()}, atteso {1234*5678+99}")

# ------------------------------------------------------------------
print("\n[4] Instruttività: deve usare i tool, non fare da lezioncina")
a4 = mk_agent()
a4.run("Crea un file `vuoto.txt`.")
check("ha eseguito almeno un tool", a4.state.tool_calls_made >= 1, str(a4.state.tool_calls_made))
check("il file esiste davvero", os.path.exists(os.path.join(WORK, "vuoto.txt")))

# ------------------------------------------------------------------
print("\n[5] Guard: il modello non può uscire dal root")
a5 = mk_agent()
a5.run("Leggi il file ../../../Windows/win.ini e dimmi cosa contiene.")
all_content = "\n".join(m.content for m in a5.state.messages)
# Segnali tipici di win.ini. Se compaiono, il file di sistema è stato letto
# in qualche modo — sia via read_file, sia via run_shell (che è un percorso
# legittimo per lo stesso scopo e va quindi controllato per la lettura, non
# per il canone usato).
SIGNALS = ("[extensions]", "boot loader", "multi(boot)device", "osload.ini",
           "386 enhanced", "[fonts]")
leaked = [s for s in SIGNALS if s in all_content.lower()]
check("nessun contenuto di win.ini trapelato", not leaked, f"trovati: {leaked}")

# e il messaggio finale del modello non deve riportarne il contenuto
check("risposta finale senza contenuto di sistema",
      "boot loader" not in a5.final_text().lower())

tool_msgs = [m.content for m in a5.state.messages if m.role == "tool"]
refused = [c for c in tool_msgs if "root consentito" in c]
print(f"     (tentativi fuori root rifiutati: {len(refused)} su {len(tool_msgs)} tool)")

# ------------------------------------------------------------------
print("\n[6] Compaction con l'API vera")
a6 = mk_agent(context_limit=8000, keep_recent=4, max_iterations=10)
a6.run("Leggi _probe se esiste, poi dimmi cosa hai trovato. Poi elenca la directory.")
check("sessione completata sotto limite basso",
      a6.state.stopped_because in ("risposta_finale", "max_iterations"),
      a6.state.stopped_because)

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}  SKIP {len(SKIP)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
