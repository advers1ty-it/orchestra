"""Un errore di rete non è la fine del benchmark.

Il polling interrogava /api/bench/status ogni 1,5 secondi e, alla
prima richiesta fallita, si chiudeva: un errore transitorio — una
scossa di rete, un laptop che cambia access point — e la UI smetteva
per sempre, mentre il benchmark continuava a girare sul server.

Il risultato è la cosa peggiore che possa capitare: il lavoro avanza
e non lo vedi, la UI sembra morta, e la prima cosa che pensi è che il
benchmark sia crashato. Non è crashato niente.

Serve una prova che lo.fetch fallisca e poi torni, e che il polling
regga.
"""

import io
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANELS = os.path.join(ROOT, "orchestra", "web", "panels.js")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


src = io.open(PANELS, encoding="utf-8").read()
i = src.index("function pollBench()")
j = src.index("\nfunction ", i + 10)
corpo = src[i:j]

print("[1] Il polling non si chiude al primo errore")
_catch = corpo[corpo.index("} catch"):]
check("nel ramo di errore il timer si azzera solo dopo il tetto",
      _catch.index("errori < ") < _catch.index("clearInterval"),
      "il clearInterval arriva prima del controllo sul contatore: "
      "basta un errore e il polling muore")
check("c'e' un contatore di errori", "let errori = 0" in corpo)
check("si ritenta prima di rinunciare", "if (errori < " in corpo)
check("e il ritento non ferma il timer", corpo.count("return") >= 1,
      "un return dentro il catch: si riprova al giro dopo")
check("il messaggio di tentativo non e' un errore",
      "connessione instabile" in corpo and '"ko"' not in
      corpo[corpo.index("connessione instabile"):corpo.index("connessione instabile") + 120],
      "un 'instabile' colorato di errore fa scattare l'allarme sul torto")

print("\n[2] E quando rinuncia, dice cosa potrebbe essere successo")
check("il messaggio finale nomina il server",
      "puo' continuare sul server" in corpo,
      "senza questo sembra che tutto sia andato perso")
check("e conta i tentativi", "tentativi" in corpo)

print("\n[3] Il ramo che chiude davvero esiste ancora")
# se non chiude piu' mai, il timer continua per sempre e la UI continua
# a interrogare un benchmark finito: peggio del difetto di prima
check("chiude dopo N tentativi", corpo.count("clearInterval") >= 1)
check("quando non gira piu' mostra il risultato",
      "renderBenchResult" in corpo and 'if (d.running)' in corpo)

print("\n[4] Funziona davvero, non solo sembra")
# Si esegue il vero codice con un fetch che fallisce due volte e poi
# funziona: se il polling si chiudesse, il conto dei tentativi
# finirebbe a 1.
D = tempfile.mkdtemp()
harness = os.path.join(D, "h.js")
open(harness, "w", encoding="utf-8").write("""
// solo la funzione, con le dipendenze minime
let benchTimer = null, erroriProva = 0, chiamate = 0, chiuso = false;
const statoBench = (t, c) => { if (c === "ko") chiuso = true; };
const benchLog = { textContent: "", scrollTop: 0, scrollHeight: 0 };
const contaAvanzamento = () => {};
const renderBenchResult = () => {};
async function fetch(_u) {
  chiamate += 1;
  if (chiamate <= 2) throw new TypeError("Failed to fetch");
  return { json: async () => ({ running: false, log: ["  a: ok"], result: null }) };
}
""" + corpo + """
(async () => {
  const t = async () => { if (benchTimer) { clearInterval(benchTimer); benchTimer = null; } };
  // un orologio finto: l'attesa non e' quello che conta
  globalThis.setInterval = (fn) => { globalThis.__fn = fn; return 1; };
  globalThis.clearInterval = () => {};
  pollBench();
  const f = globalThis.__fn;
  await f();               // 1: fallisce
  console.log("VIVO_DOPO_1 " + (benchTimer !== null));
  await f();               // 2: fallisce
  console.log("VIVO_DOPO_2 " + (benchTimer !== null));
  await f();               // 3: funziona: qui chiude, ed e' giusto
  console.log("CHIAMATE " + chiamate);
  console.log("VIVO_AL_FINE " + (benchTimer !== null));
  console.log("CHIUSO " + chiuso);
})();
""")
r = subprocess.run(["node", harness], capture_output=True, text=True, timeout=60)
out = r.stdout
print("    " + out.strip().replace("\n", "\n    "))
check("ha fatto le tre richieste", "CHIAMATE 3" in out, out)
check("non si e' chiuso dopo il primo errore", "VIVO_DOPO_1 true" in out,
      "il timer e' stato azzerato al primo errore")
check("non si e' chiuso dopo il secondo", "VIVO_DOPO_2 true" in out,
      "due errori di fila e il polling si e' chiuso")
check("chiude quando il benchmark finisce davvero",
      "VIVO_AL_FINE false" in out,
      "il timer resta attivo anche dopo che il benchmark ha finito: "
      "continua a interrogare un risultato che non cambia piu'")
check("e non ha colorato di errore un tentativo", "CHIUSO false" in out, out)
if r.returncode != 0:
    print("    stderr:", r.stderr.strip()[:200])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)