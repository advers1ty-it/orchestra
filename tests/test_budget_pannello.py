"""Il pannello Budget: lo zero e' un valore, non un campo vuoto.

Difetto visto in uso: si mette un limite a 0 (che in Orchestra vuol dire
"illimitato"), si chiude e si riapre il pannello e il campo e' vuoto con
solo il placeholder. Da li' non si sa se il valore e' stato salvato o no.

Il server lo salvava: `/api/chiavi` risponde `task_tokens: 0` e
`check_limits` salta il confronto quando il limite e' zero. A perdere
l'informazione era la riga che riempie i campi:

    optBudgetTaskTokens.value = b.task_tokens || "";   // 0 || "" === ""

Vuoto e zero vogliono dire due cose diverse — "non deciso" e
"illimitato" — e a schermo erano la stessa. Qui si esegue il bundle
vero, si chiama `disegnaProvider` con tre risposte del server (tutti
zeri, tutti null, misti) e si leggono i campi.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "orchestra", "web")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from _ordine import ORDER  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


CAMPI = ["budget-task-tokens", "budget-task-cost", "budget-task-iters",
         "budget-sess-tokens", "budget-sess-cost", "budget-sess-reqs",
         "budget-day-cost", "budget-month-cost"]

PROBE = r"""
function leggiBudget() {
  const ids = %s;
  const out = {};
  for (const id of ids) {
    const e = document.getElementById(id);
    out[id] = e ? String(e.value) : "<manca>";
  }
  return out;
}

const OUT = { errori: [] };

async function disegna(budget, etichetta) {
  try {
    await disegnaProvider({ provider: "openrouter", chiavi: CHIAVI,
                            motori: [], budget: budget });
  } catch (e) {
    OUT.errori.push(etichetta + ": " + e.message);
  }
  return leggiBudget();
}

(async function () {
  OUT.zeri = await disegna({ task_tokens: 0, task_cost: 0.0,
                             task_iters: 0, sess_tokens: 0,
                             sess_cost: 0.0, sess_reqs: 0,
                             day_cost: 0.0, month_cost: 0.0 }, "zeri");
  OUT.vuoti = await disegna({ task_tokens: null, task_cost: null,
                              task_iters: null, sess_tokens: null,
                              sess_cost: null, sess_reqs: null,
                              day_cost: null, month_cost: null }, "vuoti");
  OUT.misti = await disegna({ task_tokens: 20000, task_cost: 0.5,
                              task_iters: 0, sess_tokens: 0,
                              sess_cost: 0.0, sess_reqs: 500,
                              day_cost: 0.0, month_cost: 200 }, "misti");
  OUT.senza = await disegna(null, "senza");
  console.log(JSON.stringify(OUT));
})();
""" % json.dumps(CAMPI)

src = "\n;\n".join(open(os.path.join(WEB, f), encoding="utf-8").read()
                   for f in ORDER)
dom = open(os.path.join(HERE, "_dom_provider.js"), encoding="utf-8").read()

script = os.path.join(tempfile.gettempdir(), "_run_budget.js")
with open(script, "w", encoding="utf-8") as f:
    f.write(dom + "\n" + src + "\n" + PROBE)

env = dict(os.environ)
env["ORCHESTRA_WEB_INDEX"] = os.path.join(WEB, "index.html")
try:
    r = subprocess.run(["node", script], capture_output=True, text=True,
                       timeout=90, cwd=ROOT, env=env)
    out = r.stdout
finally:
    try:
        os.unlink(script)
    except OSError:
        pass

if "zeri" not in out:
    print(out[:600])
    print(r.stderr[:400])
    print("\n  il probe non ha girato: nessuna verifica")
    sys.exit(1)

d = json.loads(out[out.index("{"):out.rindex("}") + 1])

print("[1] Il pannello si popola dal server, senza errori")
check("nessun errore nel popolamento", d["errori"] == [], str(d["errori"]))

print("\n[2] Limiti a zero: il campo mostra 0, non il vuoto")
for campo in CAMPI:
    check(f"{campo} = 0", d["zeri"].get(campo) == "0", d["zeri"].get(campo))

print("\n[3] Mai configurato (null): il campo resta vuoto")
for campo in CAMPI:
    check(f"{campo} vuoto", d["vuoti"].get(campo) == "", d["vuoti"].get(campo))

print("\n[4] Valori misti: ognuno mostra il suo")
attesi = {"budget-task-tokens": "20000", "budget-task-cost": "0.5",
          "budget-task-iters": "0", "budget-sess-tokens": "0",
          "budget-sess-cost": "0", "budget-sess-reqs": "500",
          "budget-day-cost": "0", "budget-month-cost": "200"}
for campo, atteso in attesi.items():
    check(f"{campo} = {atteso}", d["misti"].get(campo) == atteso,
          d["misti"].get(campo))

print("\n[5] Senza budget nella risposta i campi non si toccano")
check("nessun errore", d["errori"] == [], str(d["errori"]))
check("i valori precedenti restano", d["senza"] == d["misti"],
      f'{d["senza"]} vs {d["misti"]}')

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
