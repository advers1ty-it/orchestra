"""Il tempo di attesa deve essere visibile, e non deve accumularsi.

Il buco: fra l'invio e la prima risposta del modello possono passare
40 secondi, e a schermo non succedeva niente. Sembrava che Orchestra
avesse smesso di funzionare.

La soluzione scelta sono gli step visibili e non lo streaming: su un
orchestratore il tempo si spende quasi tutto in tool, non in testo, e
il parser SSE con i `tool_calls` frammentati e' il punto dove un
modello smette di chiamare gli strumenti. Qui si dice che sta
lavorando, e basta.

Due regole, e la seconda e' quella che viene dimenticata:

1. durante un'attesa si vede qualcosa
2. dopo, non resta nulla — UNA riga che si aggiorna, non una per
   iterazione. Cinque tool in un turno e cinque righe "sto pensando"
   coprirebbero quello che e' successo davvero: e' lo stesso difetto
   del `[tool?]` su ottanta righe.

Questo test ESERCITA la logica su un DOM finto. Un test che legge il
sorgente e cerca una parola verifica che la parola ci sia, non che il
codice funzioni — ed e' esattamente il difetto che ha lasciato passare
il `servizioTace` di due giorni fa.
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "orchestra", "web", "core.js")
AGENT = os.path.join(ROOT, "orchestra", "agent.py")
CSS = os.path.join(ROOT, "orchestra", "web", "app.css")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


core = open(CORE, encoding="utf-8").read()
agent = open(AGENT, encoding="utf-8").read()
css = open(CSS, encoding="utf-8").read()

print("[1] Il backend emette l'attesa PRIMA di chiamare il modello")
# La posizione conta piu' del fatto che l'evento ci sia: emesso dopo
# la chiamata, arriverebbe quando la risposta e' gia' pronta e non
# servirebbe a niente.
i_think = agent.find('self._emit("thinking"')
i_call = agent.find("self._call_model_with_retry()")
check("l'evento esiste", i_think > 0)
check("ed e' PRIMA della chiamata al modello",
      0 < i_think < i_call,
      "emesso dopo, arriva quando la risposta e' gia' pronta")
check("dentro il ciclo delle iterazioni",
      agent.count("self._emit(\"thinking\"") == 1,
      "uno per iterazione: se fosse uno solo, la seconda attesa non "
      "mostrerebbe nulla")

print("\n[2] E la UI lo mostra")
check("gestisce l'evento", 'case "thinking"' in core)
check("chiamando la funzione dedicata", "mostraAttesa()" in core)

print("\n[3] Una riga sola che si aggiorna, non una per iterazione")
check("riusa lo stesso nodo", "if (!attesaNodo)" in core,
      "senza questo, ogni thinking aggiunge una riga")
check("e la toglie quando arriva qualcosa",
      "function togliAttesa" in core)
n_togli = core.count("togliAttesa()")
check("chiamata in almeno tre punti", n_togli >= 4,
      f"trovate {n_togli}: definizione piu' assistant, tool_end, "
      "tool_error. Se manca in uno, la riga resta e copre la "
      "risposta vera")
check("NON la toglie durante un retry",
      'case "retry"' not in core or "togliAttesa()" not in
      core.split('case "retry"')[1][:400],
      "durante un retry il modello sta ancora lavorando: e' proprio "
      "li che l'utente deve vedere che non e' morto")

print("\n[4] Il timer non resta appeso")
check("lo ripulisce", "clearInterval(attesaTimer)" in core,
      "un intervale che gira per sempre dopo la fine del turno "
      "continua a scrivere su una riga che non esiste piu'")
check("lo riavvia da zero quando serve", "attesaGiro = 0" in core)

print("\n[5] Il testo cambia col tempo")
# Tre frasi: la prima e' breve, la seconda dice che il modello e'
# lento, la terza che ci vogliono piu' passaggi. Tre messaggi che
# dicono cose diverse su un'attesa che sembra sempre uguale.
check("ha piu' di una frase", core.count("sto ragionando") >= 2)
check("la pulsazione esiste", "@keyframes attesa-pulse" in css)
check("e rispetta prefers-reduced-motion",
      "prefers-reduced-motion" in css.split("@keyframes attesa-pulse")[1][:300],
      "senza, chi ha chiesto meno animazioni si trova comunque una "
      "riga che pulsa")

print("\n[6] E funziona: esercizio vero, non lettura")
# Estrae le due funzioni dal sorgente e le esercita: cinque eventi
# thinking devono lasciare UNA riga, non cinque.
HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.env.CORE_JS, "utf-8");

function estrai(nome) {
  const i = src.indexOf("function " + nome);
  if (i < 0) throw new Error("non trovo " + nome);
  let d = 0, a = false;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") { d++; a = true; }
    else if (src[j] === "}") { d--; if (a && d === 0) return src.slice(i, j + 1); }
  }
  throw new Error("graffe non bilanciate in " + nome);
}

// Il DOM finto: un log che basta, e un elenco di orologi.
const _nodi = [];
globalThis.log = {
  appendChild(n) { _nodi.push(n); n.parentNode = log; },
  scrollTop: 0,
  scrollHeight: 0,
};
globalThis.scrollDown = function () {};
globalThis.setInterval = function () { return 1; };
globalThis.clearInterval = function () {};
globalThis.el = function (tag, cls) {
  return { tagName: tag, className: cls, textContent: "", children: [] };
};

// new Function ha scope proprio: vede globalThis ma non le variabili
// di questo modulo. Lo stub glielo si passa come argomento e si usa
// dentro — altrimenti muore con ReferenceError su `log`, che e' un
// modo di imparare che il codice era sbagliato guardando un errore
// che non parla di niente.
// Le frasi sono un array di stringhe letterali: si leggono con
// JSON.parse, non con eval. Eval su una riga di codice non serve per
// estrarre un array, e un test che esegue codice ricevuto dal
// sorgente si sta regalando un vettore.
const FRASI = JSON.parse(
  src.match(/const FRASI_ATTESA = (\[[\s\S]*?\]);/)[1]);

// new Function ha scope proprio: vede globalThis ma non le variabili
// di questo modulo, quindi lo stub glielo si passa come argomento.
//
// E le copie hanno un prefisso: dentro la stringa passata a
// new Function c'e' gia' la dichiarazione della funzione estratta,
// con i suoi nomi liberi — e senza prefisso Node risponde
// "Identifier has already been declared" su una riga che sembrava
// innocua. Sono state tre ricorrenze dello stesso errore, una per
// ogni nome: mostraAttesa, togliAttesa, FRASI_ATTESA.
const _mostra = new Function("log", "scrollDown", "setInterval",
  "clearInterval", "el", "FRASI_ATTESA",
  estrai("mostraAttesa") + "; return mostraAttesa;")(
    log, scrollDown, setInterval, clearInterval, el, FRASI);
const _togli = new Function("log", "clearInterval",
  estrai("togliAttesa") + "; return togliAttesa;")(
    log, clearInterval);

// cinque eventi di fila, come in un turno con quattro tool
for (let k = 0; k < 5; k++) _mostra();
const dopoCinque = _nodi.length;
const testoFinale = _nodi[_nodi.length - 1].textContent;

_togli();
const dopoTogli = _nodi.filter((n) => !n.removed).length;

console.log(JSON.stringify({
  nodi: dopoCinque,
  testoFinale: testoFinale,
  rimasti: dopoTogli,
  frasi: FRASI.length,
}));
"""


def esegui():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(HARNESS)
        path = fh.name
    try:
        import os as _os
        out = subprocess.run(["node", path], capture_output=True,
                             text=True, timeout=30,
                             env=dict(_os.environ, CORE_JS=CORE))
        if out.returncode != 0:
            return None, out.stderr[-300:]
        for line in out.stdout.split("\n"):
            if line.strip().startswith("{"):
                return json.loads(line), None
        return None, out.stdout[-200:]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


ris, err = esegui()
check("il codice gira", ris is not None, err or "")
if ris:
    check("cinque eventi lasciano UNA riga", ris["nodi"] == 1,
          f"trovate {ris['nodi']} righe: una per iterazione e il "
          "pannello si riempie di 'sto pensando'")
    check("il testo cambia col tempo",
          ris["testoFinale"] != "sto ragionando…",
          f"dopo 5 giri dovrebbe dire altro, dice {ris['testoFinale']!r}")
    check("dopo togliAttesa non resta nulla", ris["rimasti"] == 0,
          f"rimaste {ris['rimasti']}")
    check("le frasi sono piu' di una", ris["frasi"] >= 3,
          f"solo {ris['frasi']}: un'attesa lunga con un messaggio solo "
          "sembra un programma bloccato")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)