"""Il ritorno del focus dai pannelli veri, non solo dal gestore isolato.

Ogni pannello passa il proprio pulsante ad apriFocusModale. Se un handler
smette di farlo, il pannello si apre ancora e Tab funziona, ma alla
chiusura il focus torna al controllo sbagliato. Qui si cliccano i
pulsanti del bundle reale e si chiude il pannello vero.

I caricamenti dati sono sostituiti da no-op: il test misura il focus, non
le API o il rendering. Il DOM e' finto, come negli altri test frontend.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "orchestra", "web")
with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
    HTML = f.read()
sys.path.insert(0, os.path.join(ROOT, "tests"))

from _ordine import ORDER  # noqa: E402

PASS, FAIL = [], []

# chiave, etichetta, id del pulsante, id del pannello, funzione che chiude
PANNELLI = [
    ("opzioni", "Opzioni", "btn-opzioni", "opzioni", "chiudiOpzioni"),
    ("progetti", "Progetti", "side-progetti-gestisci", "progetti-modal",
     "chiudiProgetti"),
    ("capacita", "Capacità", "side-cap", "capacita", "chiudiCapacita"),
    ("benchmark", "Benchmark", "opz-bench-apri", "bench", "closeBench"),
    ("diff", "Diff", "btn-diff", "diff-modal", "chiudiDiff"),
    ("mcp-aggiungi", "conferma MCP da Aggiungi", "mcp-add", "mcp-conferma",
     "mcpConfermaChiudi"),
]

SCENARI = "\n".join(
    f'  await provaPannello("{chiave}", "{id_pulsante}", {chiudi});'
    for chiave, _, id_pulsante, _, chiudi in PANNELLI
)



def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


js_parts = []
for sorgente in ORDER:
    with open(os.path.join(WEB, sorgente), encoding="utf-8") as f:
        js_parts.append(f.read())
bundle = "\n;\n".join(js_parts)

HARNESS = r"""
class El {
  constructor(tag){
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.className = "";
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this._text = "";
    this._on = {};
    this._attrs = {};
    this._cls = new Set();
  }
  appendChild(c){ this.children.push(c); return c; }
  replaceChildren(...c){ this.children = c; }
  set textContent(v){ this._text = v == null ? "" : String(v); this.children = []; }
  get textContent(){ return this._text; }
  addEventListener(k, f){ (this._on[k] = this._on[k] || []).push(f); }
  focus(){ globalThis.document.activeElement = this; }
  getClientRects(){ return this.hidden ? [] : [{}]; }
  get classList(){
    return {
      add: (...c) => c.forEach(x => this._cls.add(x)),
      remove: (...c) => c.forEach(x => this._cls.delete(x)),
      contains: (c) => this._cls.has(c),
    };
  }
  setAttribute(k, v){ this._attrs[k] = String(v); }
  getAttribute(k){ return this._attrs[k] === undefined ? null : this._attrs[k]; }
  hasAttribute(k){ return Object.prototype.hasOwnProperty.call(this._attrs, k); }
  querySelectorAll(){ return []; }
  querySelector(){ return null; }
}

const _els = {};
function mk(id){
  if (!_els[id]) _els[id] = new El("div");
  return _els[id];
}
globalThis.window = {addEventListener(){}};
globalThis.document = {
  body: new El("body"),
  activeElement: null,
  _on: {},
  getElementById: mk,
  createElement: (tag) => new El(tag),
  addEventListener(k, f){ (this._on[k] = this._on[k] || []).push(f); },
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
};
globalThis.document.activeElement = globalThis.document.body;
globalThis.localStorage = {getItem: () => null, setItem(){}, removeItem(){}};
globalThis.fetch = async () => ({ok: true, json: async () => ({})});
globalThis.EventSource = class { constructor(){ this.readyState = 0; } addEventListener(){} close(){} };
globalThis.Option = function(t, v){ const o = new El("option"); o.textContent = t; o.value = v; return o; };
"""

PROBE = r"""
const out = {};
function verifica(nome, cond){
  out[nome] = cond ? true : ("attivo: " + (document.activeElement && document.activeElement.id));
}
function click(el){
  const ev = {
    target: el, currentTarget: el,
    preventDefault(){}, stopPropagation(){},
  };
  return Promise.all((el._on.click || []).map(fn => fn(ev)));
}
try {
  // I caricamenti non servono al focus e trascinerebbero dentro il test
  // tutto il rendering dei pannelli.
  caricaDiff = () => {};
  caricaOpzioni = () => {};
  ricaricaMemoria = () => {};
  caricaProgetti = () => {};
  mostraCapTab = () => {};
  caricaSkill = () => {};
  pollBench = () => {};
  caricaRouting = () => {};

  const esca = new El("button");
  esca.id = "fuori";
  document.activeElement = esca;

  async function provaPulsante(nome, pulsante, chiudi){
    pulsante.tagName = "BUTTON";
    document.activeElement = esca;
    await click(pulsante);
    chiudi();
    verifica(nome, document.activeElement === pulsante);
  }
  async function provaPannello(nome, idPulsante, chiudi){
    const pulsante = mk(idPulsante);
    pulsante.id = idPulsante;
    await provaPulsante(nome, pulsante, chiudi);
  }

  // MCP: il preset richiede la conferma e il pulsante Aggiungi deve
  // diventare l'apertore del modale.
  mcpPresets = [{id: "potente", nome: "Server potente", richiede_conferma: true, campi: []}];
  mk("mcp-preset").value = "potente";
__SCENARI__

  // Lo stesso modale si apre dalla riga Connetti, costruita a runtime.
  const riga = mcpRiga({id: "s1", name: "Server uno", preset: "potente", connected: false});
  const azioni = riga.children.find(c => c.className === "goal-meta");
  const connetti = azioni.children[0];
  connetti.id = "mcp-connetti";
  await provaPulsante("mcp-connetti", connetti, mcpConfermaChiudi);
} catch (e) {
  out.ERROR = String(e && e.stack ? e.stack : e);
}
console.log("@@OUT@@" + JSON.stringify(out));
"""

tmp = os.path.join(tempfile.gettempdir(), "orchestra_focus_pannelli_probe.js")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(HARNESS + "\n" + bundle + "\n" + PROBE.replace("__SCENARI__", SCENARI))

try:
    r = subprocess.run(["node", tmp], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
except FileNotFoundError:
    print("  node non e' installato: la prova col DOM finto salta")
    r = None

if r is not None:
    m = re.search(r"@@OUT@@(\{.*\})", r.stdout or "")
    if not m:
        check("il probe ha girato", False,
              "FILE=" + tmp + " :: " + ((r.stderr or "") + (r.stdout or ""))[:600])
    else:
        out = json.loads(m.group(1))
        check("node esce senza errori", r.returncode == 0,
              ((r.stderr or "") + (r.stdout or ""))[:300])
        check("il probe non e' crashato", "ERROR" not in out,
              out.get("ERROR", "")[:300])
        for chiave, etichetta, _, _, _ in PANNELLI:
            check(f"{etichetta} torna al proprio pulsante",
                  out.get(chiave) is True, out.get(chiave, ""))
        check("conferma MCP da Connetti torna al proprio pulsante",
              out.get("mcp-connetti") is True, out.get("mcp-connetti", ""))

mancanti = []
for _, etichetta, id_pulsante, id_pannello, _ in PANNELLI:
    if not re.search(r'<button\b[^>]*\bid="' + re.escape(id_pulsante) + r'"', HTML):
        mancanti.append(f"{etichetta}: pulsante {id_pulsante}")
    if not re.search(r'\bid="' + re.escape(id_pannello) + r'"', HTML):
        mancanti.append(f"{etichetta}: pannello {id_pannello}")
check("pulsanti e pannelli esistono nel markup", not mancanti,
      "; ".join(mancanti[:5]))

if r is None or r.returncode == 0:
    try:
        os.remove(tmp)
    except OSError:
        pass
else:
    print("  (il probe e' rimasto in", tmp, ")")

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
    sys.exit(1)
print("Tutto verde.")
