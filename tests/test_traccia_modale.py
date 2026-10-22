"""La traccia si apre in un modale, non sotto la lista.

Il difetto: il dettaglio della traccia viveva in un <div> dentro la
sidebar, subito sotto la lista. La lista puo' essere lunga (15 righe) e
il dettaglio, con il suo max-height, finiva sotto il bordo della
finestra: si cliccava la riga e non si vedeva nulla. Il click "non
funzionava" — funzionava, ma il risultato era fuori schermo.

Qui si verifica il comportamento vero: il click apre un modale che si
vede, e il modale si chiude.

Il DOM e' finto, come in test_ui.py: qui serve solo il minimo per
far girare la logica.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "orchestra", "web")
UI = os.path.join(WEB, "index.html")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


with open(UI, encoding="utf-8") as f:
    html = f.read()

# ------------------------------------------------------- il markup c'e'
check("il modale della traccia e' nel markup",
      'id="traccia-modal"' in html,
      "manca il contenitore del modale")
check("il modale ha un bottone per chiudere",
      'id="traccia-chiudi"' in html)
check("il dettaglio sta dentro il modale",
      re.search(r'id="traccia-modal".*?id="side-traccia-dettaglio"', html, re.S) is not None,
      "il dettaglio deve stare DENTRO il modale, non nella sidebar")
check("il dettaglio non sta piu' nella sidebar",
      html.count('id="side-traccia-dettaglio"') == 1,
      "il dettaglio non deve esistere in due posti")

# ------------------------------------------------------- il CSS c'e'
with open(os.path.join(WEB, "app.css"), encoding="utf-8") as f:
    css = f.read()
check("il modale e' posizionato sopra tutto",
      re.search(r"\.traccia-modal\s*\{[^}]*position:\s*fixed", css) is not None)
check("il modale si vede quando ha la classe show",
      ".traccia-modal.show" in css)
check("il modale ha un'altezza limitata",
      re.search(r"\.traccia-modal-box\s*\{[^}]*height:", css) is not None)

# ------------------------------------------------------- il JS c'e'
js_parts = []
for _s in ("core.js", "panels.js", "modelpick.js", "main.js"):
    with open(os.path.join(WEB, _s), encoding="utf-8") as _f:
        js_parts.append(_f.read())
js = "\n;\n".join(js_parts)

check("il click apre il modale", "apriModaleTraccia" in js)
check("chiama l'API per prendere la traccia", "/api/tracce/" in js)
check("Escape chiude il modale", "Escape" in js and "chiudiModaleTraccia" in js)

# ------------------------------------------------------- il comportamento
# DOM finto: basta createElement, classList, appendChild, textContent,
# addEventListener, hidden e la proprieta' className.
HARNESS = r"""
class El {
  constructor(tag){ this.tagName=(tag||"div").toUpperCase(); this.children=[]; this._text="";
    this.className=""; this.hidden=false; this._on={}; this._cls=new Set(); }
  appendChild(c){ this.children.push(c); return c; }
  replaceChildren(...c){ this.children=c; }
  set textContent(v){ this._text=v===undefined||v===null?"":String(v); this.children=[]; }
  get textContent(){ return this._text; }
  set innerHTML(v){ this._text=String(v); }
  get innerHTML(){ return this._text; }
  addEventListener(k,f){ (this._on[k]=this._on[k]||[]).push(f); }
  dispatch(k,ev){ (this._on[k]||[]).forEach(f=>f(ev||{target:this,currentTarget:this,preventDefault(){},stopPropagation(){}})); }
  get classList(){ const s=this._cls; return {
    add:(...c)=>c.forEach(x=>{s.add(x); this.className=[...s].join(" ");}),
    remove:(...c)=>c.forEach(x=>{s.delete(x); this.className=[...s].join(" ");}),
    contains:(c)=>s.has(c),
    toggle:(c,f)=>{ if(f===undefined){ if(s.has(c)) s.delete(c); else s.add(c);} else if(f) s.add(c); else s.delete(c);
      this.className=[...s].join(" "); return s.has(c); },
  }; }
  querySelector(sel){ const id=sel.replace(/^#/, "");
    return globalThis.__byId ? globalThis.__byId(id) : null; }
  querySelectorAll(){ return []; }
  focus(){} blur(){} select(){}
  remove(){}
  setAttribute(k,v){ this["attr_"+k]=String(v); }
  getAttribute(k){ return this["attr_"+k]!==undefined?this["attr_"+k]:null; }
  removeAttribute(k){ delete this["attr_"+k]; }
  hasAttribute(k){ return this["attr_"+k]!==undefined; }
  get style(){ return this._style||(this._style={}); }
  set style(v){ this._style=v; }
  get dataset(){ return this._dataset||(this._dataset={}); }
  closest(){ return null; }
  getBoundingClientRect(){ return {top:0,left:0,width:0,height:0,bottom:0,right:0}; }
  append(...c){ c.forEach(x=>this.appendChild(x)); }
}
const _els={};
function mk(id){ if(_els[id]) return _els[id]; const e=new El("div"); _els[id]=e; return e; }
globalThis.__byId=(id)=>_els[id]||null;
globalThis.document={
  getElementById:(id)=>mk(id),
  createElement:(t)=>new El(t),
  createTextNode:(t)=>({textContent:t}),
  addEventListener:(k,f)=>{ (globalThis.__docOn[k]=globalThis.__docOn[k]||[]).push(f); },
  querySelector:()=>null,
  querySelectorAll:()=>[],
  body:new El("body"),
  dispatchEvent:()=>{},
};
globalThis.__docOn={};
globalThis.window={addEventListener:()=>{},location:{}};
globalThis.location={href:"",search:""};
globalThis.localStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
globalThis.sessionStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
globalThis.navigator={clipboard:{writeText:async()=>{}},userAgent:"node"};
globalThis.fetch=async()=>({ok:true,json:async()=>({})});
// I timer veri, salvati PRIMA di essere sostituiti: uno stub che chiama
// se stesso fa overflow di stack.
const _setTimeout = globalThis.setTimeout, _clearTimeout = globalThis.clearTimeout;
globalThis.setTimeout=(f,t)=>_setTimeout(f,t); globalThis.clearTimeout=(h)=>_clearTimeout(h);
globalThis.setInterval=()=>0; globalThis.clearInterval=()=>{};
globalThis.requestAnimationFrame=()=>0;
globalThis.CSS={escape:(s)=>String(s)};
// Lo stream degli eventi non serve al probe, ma il bundle lo apre subito:
// senza questo, il probe muore prima di arrivare alla traccia.
globalThis.EventSource=class{ constructor(){ this.readyState=0; }
  addEventListener(){} close(){} };
globalThis.Option=function(t,v){ const o=new El("option"); o.textContent=t; o.value=v; return o; };
"""

# Il probe simula quello che fa l'utente: clicca la riga della traccia
# e poi guarda se il modale si e' aperto.
PROBE = r"""
const out = {};
(async () => {
try {
  // la traccia che il server risponde
  // Due risposte diverse: la LISTA delle tracce e il DETTAGLIO di una.
  const RIEPIEGO = {id:1, modello:"m", iterazioni:2, token:10, durata_s:1.5,
                    esito:"risposta_finale", n_eventi:2, errori:0, ts:1700000000,
                    tool_chiamate:1};
  globalThis.fetch = async (url) => ({
    ok: true,
    json: async () => (String(url).indexOf("/api/tracce/") === 0
      ? {riepilogo: RIEPIEGO,
         eventi: [
           {tipo:"tool_start", dati:{name:"read_file"}},
           {tipo:"tool_end", dati:{name:"read_file", ok:true}},
         ]}
      : {tracce: [RIEPIEGO]}),
  });
  await caricaSideTracce();
  await new Promise(r=>setTimeout(r,50));
  const lista = mk("side-tracce");
  out.testoPrimaRiga = (lista.children[0] && lista.children[0].textContent || "").slice(0,60);
  out.righe = lista.children.length;
  const prima = lista.children[0];
  const btn = prima && prima.children[0];
  out.haBottone = !!(btn && btn._on && btn._on.click);
  if (btn) await btn._on.click[0]();
  const m = mk("traccia-modal");
  out.modaleNascosto = !!m.hidden;
  out.modaleMostrato = m.classList.contains("show");
  const det = mk("side-traccia-dettaglio");
  out.dettaglioTesto = (det.textContent || "").slice(0, 80);
  out.eventi = det.children.length;
  // e si chiude
  const chiudi = mk("traccia-chiudi");
  if (chiudi._on.click) chiudi._on.click[0]();
  out.chiusoDopo = !!m.hidden;
} catch (e) {
  out.ERROR = String(e && e.stack ? e.stack : e);
}
console.log("@@OUT@@" + JSON.stringify(out));
})();
"""

script = HARNESS + "\n" + js + "\n" + PROBE
tmp = os.path.join(tempfile.gettempdir(), "orchestra_traccia_probe.js")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(script)

try:
    r = subprocess.run(["node", tmp], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
except FileNotFoundError:
    print("  node non e' installato: la prova col DOM finto salta")
    r = None

if r is not None:
    m = re.search(r"@@OUT@@(\{.*\})", r.stdout or "")
    if not m:
        check("il probe ha girato", False, "FILE=" + tmp + " :: " + ((r.stderr or "") + (r.stdout or ""))[:600])
    else:
        out = json.loads(m.group(1))
        check("il probe non e' crashato", "ERROR" not in out, out.get("ERROR", "")[:300])
        check("la traccia e' stata caricata", out.get("righe", 0) >= 1,
              "nessuna riga nella lista")
        check("la riga ha un bottone cliccabile", out.get("haBottone") is True,
              "prima riga: " + str(out.get("testoPrimaRiga")) + " / righe=" + str(out.get("righe")))
        check("il click apre il modale", out.get("modaleMostrato") is True,
              "il modale non si e' aperto")
        check("il modale non e' piu' nascosto", out.get("modaleNascosto") is False)
        check("il dettaglio ha il contenuto", out.get("eventi", 0) >= 1,
              "nessun evento mostrato")
        check("il bottone Chiudi chiude il modale", out.get("chiusoDopo") is True)

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
