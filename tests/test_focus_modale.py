"""Il focus dei modali: entra, gira dentro e torna al pulsante giusto.

Se il gestore ricava l'apertore da document.activeElement, alcuni browser
non hanno dato il focus al pulsante dopo il click e il ritorno finisce sul
controllo sbagliato. Qui l'apertore viene passato esplicitamente, mentre
document.activeElement punta di proposito altrove.

Il DOM e' finto, come negli altri test frontend: serve solo il minimo per
far girare il vero gestore di orchestra/web/core.js.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "orchestra", "web", "core.js")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


with open(CORE, encoding="utf-8") as f:
    core_js = f.read()

# Il minimo per caricare core.js: gli elementi del test sono FocusEl,
# con focus reale, discendenti focalizzabili e parentElement. Il resto
# del DOM serve solo a far agganciare gli handler del bundle.
HARNESS = r"""
class El {
  constructor(tag){
    this.tagName = String(tag || "div").toUpperCase();
    this.hidden = false;
    this.disabled = false;
    this.parentElement = null;
    this._attrs = {};
    this._on = {};
    this._text = "";
  }
  addEventListener(k, f){ (this._on[k] = this._on[k] || []).push(f); }
  querySelectorAll(){ return []; }
  getClientRects(){ return this.hidden ? [] : [{}]; }
  focus(){ globalThis.document.activeElement = this; }
  setAttribute(k, v){ this._attrs[k] = String(v); }
  getAttribute(k){ return this._attrs[k] === undefined ? null : this._attrs[k]; }
  hasAttribute(k){ return Object.prototype.hasOwnProperty.call(this._attrs, k); }
  get classList(){ return {contains: () => false}; }
  get textContent(){ return this._text; }
  set textContent(v){ this._text = v == null ? "" : String(v); }
  contains(el){
    for (let p = el; p; p = p.parentElement) if (p === this) return true;
    return false;
  }
}

class FocusEl extends El {
  constructor(tag, nome){
    super(tag);
    this.nome = nome || "";
    this._focusabili = [];
  }
  aggiungiFocus(c){
    this._focusabili.push(c);
    c.parentElement = this;
    return c;
  }
  querySelectorAll(){ return this._focusabili; }
}

const _els = {};
globalThis.window = globalThis;
globalThis.document = {
  body: new El("body"),
  activeElement: null,
  _on: {},
  getElementById(id){
    if (!_els[id]) _els[id] = new El("div");
    return _els[id];
  },
  createElement(tag){ return new El(tag); },
  addEventListener(k, f){ (this._on[k] = this._on[k] || []).push(f); },
};
globalThis.document.activeElement = globalThis.document.body;
"""

PROBE = r"""
const out = {};
function attivo(){ return document.activeElement && document.activeElement.nome; }
function verifica(nome, cond, dettaglio){
  out[nome] = cond ? true : (dettaglio || ("attivo: " + attivo()));
}
function tab(shift){
  const ev = {
    key: "Tab", shiftKey: !!shift, prevented: false,
    preventDefault(){ this.prevented = true; },
  };
  (document._on.keydown || []).forEach(fn => fn(ev));
  return ev;
}
try {
  // Il controllo che NON ha aperto il pannello: se il gestore lo usa al
  // posto dell'apertore, il ritorno finisce qui e il test lo vede.
  const apertore1 = new FocusEl("button", "apertore1");
  const esca = new FocusEl("button", "esca");
  const pannello1 = new FocusEl("section", "pannello1");
  const primo1 = pannello1.aggiungiFocus(new FocusEl("button", "primo1"));
  const ultimo1 = pannello1.aggiungiFocus(new FocusEl("button", "ultimo1"));

  document.activeElement = esca;
  apriFocusModale(pannello1, apertore1);
  verifica("focus_entra", document.activeElement === primo1);

  ultimo1.focus();
  const avanti = tab(false);
  verifica("tab_ciclo", document.activeElement === primo1 && avanti.prevented,
           "attivo: " + attivo() + ", bloccato: " + avanti.prevented);

  primo1.focus();
  const indietro = tab(true);
  verifica("shift_tab_ciclo", document.activeElement === ultimo1 && indietro.prevented,
           "attivo: " + attivo() + ", bloccato: " + indietro.prevented);

  chiudiFocusModale(pannello1);
  verifica("ritorno_apertore", document.activeElement === apertore1);

  // Il secondo modale si apre da un controllo DENTRO il primo: il suo
  // ritorno deve restare li', e Tab non deve scendere nel sottostante.
  const apertore2 = pannello1.aggiungiFocus(new FocusEl("button", "apertore2"));
  const pannello2 = new FocusEl("section", "pannello2");
  const primo2 = pannello2.aggiungiFocus(new FocusEl("button", "primo2"));

  document.activeElement = esca;
  apriFocusModale(pannello1, apertore1);
  apriFocusModale(pannello2, apertore2);
  verifica("focus_nel_superiore", document.activeElement === primo2);

  const sopra = tab(false);
  verifica("tab_resta_nel_superiore",
           document.activeElement === primo2 && sopra.prevented,
           "attivo: " + attivo() + ", bloccato: " + sopra.prevented);

  chiudiFocusModale(pannello2);
  verifica("ritorno_al_controllo_interno", document.activeElement === apertore2);

  chiudiFocusModale(pannello1);
  verifica("ritorno_al_primo_apertore", document.activeElement === apertore1);
} catch (e) {
  out.ERROR = String(e && e.stack ? e.stack : e);
}
console.log("@@OUT@@" + JSON.stringify(out));
"""

tmp = os.path.join(tempfile.gettempdir(), "orchestra_focus_modale_probe.js")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(HARNESS + "\n" + core_js + "\n" + PROBE)

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
        check("il probe non e' crashato", "ERROR" not in out,
              out.get("ERROR", "")[:300])
        check("l'apertura porta il focus dentro il pannello",
              out.get("focus_entra") is True, out.get("focus_entra", ""))
        check("Tab dall'ultimo controllo torna al primo e resta nel pannello",
              out.get("tab_ciclo") is True, out.get("tab_ciclo", ""))
        check("Shift+Tab dal primo controllo torna all'ultimo e resta nel pannello",
              out.get("shift_tab_ciclo") is True, out.get("shift_tab_ciclo", ""))
        check("la chiusura torna al controllo che ha aperto il pannello",
              out.get("ritorno_apertore") is True,
              out.get("ritorno_apertore", ""))
        check("il modale superiore riceve il focus",
              out.get("focus_nel_superiore") is True,
              out.get("focus_nel_superiore", ""))
        check("con due modali aperti Tab resta nel superiore",
              out.get("tab_resta_nel_superiore") is True,
              out.get("tab_resta_nel_superiore", ""))
        check("chiudendo il superiore si torna al suo controllo interno",
              out.get("ritorno_al_controllo_interno") is True,
              out.get("ritorno_al_controllo_interno", ""))
        check("chiudendo anche il primo si torna al suo apertore",
              out.get("ritorno_al_primo_apertore") is True,
              out.get("ritorno_al_primo_apertore", ""))

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
