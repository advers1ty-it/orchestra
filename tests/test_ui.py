"""Verifica della UI senza browser: sintassi, DOM e logica degli handler.

Il browser in questo ambiente e' inaffidabile (timeout), e una pagina che
non parte non si vede finche' non la apri. Qui controlliamo tre cose che
sono il 90% dei bug di una UI fatta a mano:

  1. il JS e' sintatticamente valido (Node lo esegue)
  2. gli elementi che il JS cerca esistono nel markup
  3. la logica degli handler fa quello che dice (DOM finto)

Il DOM e' finto di proposito: implementa solo il minimo (createElement,
textContent, appendChild, classList, addEventListener) ed e' sufficiente
a esercitare renderStats, setBusy e il routing degli eventi, che sono le
parti dove stanno i bug silenziosi.

Nota: qui `innerHTML` e' solo LETTO, per verificare che renderStats non lo
usi. Non e' una scrittura e non c'e' nessun XSS possibile.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "orchestra", "web", "index.html")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


with open(UI, encoding="utf-8") as f:
    html = f.read()

print("\n[1] Estrazione e struttura")
m = re.search(r"<script>(.*?)</script>", html, re.S)
check("blocco <script> presente", m is not None)
js = m.group(1) if m else ""
check("script non vuoto", len(js) > 500, f"{len(js)} caratteri")

css = re.search(r"<style>(.*?)</style>", html, re.S)
check("blocco <style> presente", css is not None and len(css.group(1)) > 500)

print("\n[2] Sintassi JavaScript (Node esegue davvero il codice)")
tmp = os.path.join(tempfile.gettempdir(), "orchestra_ui_check.js")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(js)
r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True, timeout=60)
check("JS sintatticamente valido", r.returncode == 0, r.stderr[:300])

# lo stesso per i CSS: nessun controllo nativo, cerchiamo sbilanciamenti
css_text = css.group(1) if css else ""
check("CSS: graffe bilanciate", css_text.count("{") == css_text.count("}"),
      f"{css_text.count('{')} vs {css_text.count('}')}")

print("\n[3] Ogni getElementById punta a un id esistente nel markup")
declared = set(re.findall(r'id="([^"]+)"', html))
wanted = set(re.findall(r'\$\("([^"]+)"\)', js))
missing = wanted - declared
check("tutti gli id usati esistono", not missing, f"mancano: {sorted(missing)}")
check("ci sono id da usare", len(wanted) >= 8, str(len(wanted)))

print("\n[4] Logica degli handler, con DOM finto")
# Estraiamo le funzioni che ci interessano e le esercitiamo con un DOM finto.
harness = """
// --- DOM finto, minimo ma sufficiente ---
class ClassList {
  constructor(){ this.s=new Set(); }
  add(...c){ c.forEach(x=>this.s.add(x)); }
  remove(...c){ c.forEach(x=>this.s.delete(x)); }
  toggle(c){ this.s.has(c)?this.s.delete(c):this.s.add(c); }
  contains(c){ return this.s.has(c); }
}
class El {
  constructor(tag){ this.tagName=tag; this.children=[]; this._text=""; this.style={};
                   this.classList=new ClassList(); this.disabled=false; this._on={}; this._attrs={}; }
  appendChild(c){ this.children.push(c); return c; }
  cloneNode(){ const e=new El(this.tagName); e._text=this._text; return e; }
  // Nel DOM vero `el.className = "a b"` AGGIORNA classList. Il fake lo
  // ignorava, e `querySelectorAll(".tool")` non trovava nulla: i test
  // misuravano il mock invece del codice.
  set className(v){
    this._className = String(v);
    this.classList = new ClassList();
    String(v).split(/\s+/).filter(Boolean).forEach(c => this.classList.add(c));
  }
  get className(){ return this._className || ""; }
  set textContent(v){ this._text=String(v); this.children=[]; }
  get textContent(){ return this._text || this.children.map(c=>c.textContent).join(""); }
  setAttribute(k,v){ this._attrs[k]=v; this[k]=v; }
  getAttribute(k){ return this._attrs[k]; }
  // find ricorsivo: querySelector scende in profondita' nel DOM reale,
  // e tool_end lo usa per raggiungere .tool-status dentro .tool-head
  _find(pred, out){
    for(const c of this.children){
      if (pred(c)) out.push(c);
      if (c._find) c._find(pred, out);
    }
    return out;
  }
  // querySelector: supporta selettori per classe e per attributo
  querySelector(sel){
    if (sel.startsWith(".")) {
      const cls = sel.slice(1);
      const r = this._find(c => c.classList && c.classList.contains(cls), []);
      return r[0] || null;
    }
    const m = /^\[([\w-]+)="?([^"\]]*)"?\]$/.exec(sel);
    if (m) {
      const r = this._find(c => c._attrs && c._attrs[m[1]] === m[2], []);
      return r[0] || null;
    }
    return null;
  }
  querySelectorAll(sel){
    if (sel.startsWith(".")) {
      const cls = sel.slice(1);
      return this._find(c => c.classList && c.classList.contains(cls), []);
    }
    return [];
  }
  // `innerHTML = ""` in un browser vero SVUOTA l'elemento. Il fake doveva
  // farlo: senza, showBanner e handle("reset") sembravano non funzionare,
  // e i test misuravano il mock invece del codice.
  set innerHTML(v){ this._text=""; this.children=[]; }
  get innerHTML(){ return this._text; }
  // conteggio ricorsivo: i nodi vivono sia in `log` che dentro `turnEl`
  all(){ let n=1; for(const c of this.children) n+=c.all?c.all():1; return n; }
  addEventListener(k,f){ this._on[k]=f; }
  set onclick(f){ this._on["click"]=f; }
  get onclick(){ return this._on["click"]; }
  scrollIntoView(){}
}
globalThis.CSS = { escape: (s) => String(s).replace(/["\\\\]/g, "\\\\$&") };
const _els = {};
function mk(id){ return _els[id] || (_els[id] = new El("div")); }
globalThis.document = {
  createElement: (t) => new El(t),
  getElementById: mk,
  createTextNode: (t) => { const e=new El("#text"); e._text=t; return e; },
  addEventListener: () => {},
  body: new El("body"),
};
globalThis.getComputedStyle = () => ({});
globalThis.EventSource = class { constructor(){} close(){} };
globalThis.fetch = async () => ({ ok:true, json: async()=>({ok:true}) });
globalThis.autoGrow = () => {};

const out = {};
"""

# Eseguiamo lo script del browser dentro l'harness, catturando il risultato
probe = """
// --- prove ---
try {
  // renderStats: deve popolare stats col DOM, senza innerHTML.
  // Il fake ha un setter innerHTML che svuota e lascia _text: se il codice
  // lo usasse, stats._text sarebbe pieno e stats.children vuoto. Con
  // appendChild fa il contrario. E' l'unico modo di distinguerli qui.
  mk("stats").children = []; mk("stats")._text = "";
  renderStats({iterations: 3, tool_calls: 5, tool_errors: 1, total_tokens: 12345, compactions: 2});
  out.stats = mk("stats").textContent;
  out.statsViaNodi = mk("stats").children.length;
  out.statsTestoGrezzo = mk("stats")._text.length;

  // renderStats con stato vuoto
  mk("stats").children = [];
  renderStats({});
  out.empty = mk("stats").textContent;

  // setBusy abilita/disabilita coerentemente
  ready = true;
  setBusy(true);
  out.busyInputDisabled = mk("input").disabled;
  out.busySendDisabled = mk("btn-send").disabled;
  out.busyCancelEnabled = !mk("btn-cancel").disabled;
  setBusy(false);
  out.idleInputEnabled = !mk("input").disabled;
  out.idleDot = mk("dot").className;

  // setBusy con server non pronto
  ready = false;
  setBusy(false);
  out.notReadyInput = mk("input").disabled;
  ready = true;

  // testi e tool
  log.children = []; turnEl = null;
  newTurn();
  handle("turn_start", {});
  handle("user_message", {text: "ciao"});
  addText("assistant", "risposta");
  out.roles = log.children.map(c=>c.className);

  // un tool con ok
  handle("assistant", {content:"", tool_calls:[{name:"read_file", args:{path:"a.txt"}}]});
  out.toolAdded = turnEl.querySelectorAll ? true : false;
  handle("tool_end", {name:"read_file", ok:true, result:"ok"});
  handle("turn_end", {iterations:2, tool_calls:1, tool_errors:0, total_tokens:500});
  out.turnEndStats = mk("stats").textContent;

  // error e note
  handle("error", {message:"boom"});
  handle("retry", {attempt:1, error:"429"});
  handle("compaction", {tokens_before:100, tokens_after:40, tools_pruned:3, history_merged:1});
  handle("cancel_requested", {});
  out.nodesAfterAll = log.all() - 1;  // -1: il nodo log stesso

  // reset
  handle("reset", {});
  out.afterReset = log.children.length;

  // snapshot ricostruisce la conversazione e filtra i vuoti
  handle("snapshot", {ready:true, model:"m", provider:"p", busy:false, messages:[
    {role:"user", content:"domanda"},
    {role:"assistant", content:"risposta"},
    {role:"assistant", content:"   "},
  ]});
  out.snapshotMsgs = log.children.length;   // caso base: 2 messaggi
  out.snapshotEmpty = log.children.filter(c=>c.textContent==="").length;

  // server non pronto
  showBanner("errore di configurazione");
  out.banner = log.children[0].textContent;

  // send con testo vuoto non fa nulla
  busy = false; ready = true;
  const before = log.children.length;
  input.value = "   ";
  await send();
  out.emptySendNoop = log.children.length === before;

  // --- REGRESSIONE 1: content null non deve far esplodere la snapshot.
  // `m.content.trim()` su undefined solleva e blocca tutto il rendering,
  // lasciando la chat vuota senza errore in console: sembrava che
  // l'agente non rispondesse piu'.
  log.children = [];
  handle("snapshot", {ready:true, model:"m", provider:"p", busy:false, messages:[
    {role:"user", content:"prima domanda"},
    {role:"assistant", content:null},
    {role:"assistant", content:""},
    {role:"assistant", content:"risposta vera"},
    {role:"user"},
  ]});
  // il fatto che sia arrivata qui, senza eccezione, e' la prova:
  // prima `m.content.trim()` su undefined bloccava tutto il rendering
  out.snapshotRendered = true;
  out.snapshotNullMsgs = log.children.length;
  out.snapshotNullEmpty = log.children.filter(c=>c.textContent==="").length;

  // --- REGRESSIONE 2: due tool identici vanno abbinati per id.
  // Prima `tool_end` prendeva l'ultimo tool: il primo restava su "..."
  // per sempre, e i due risultati finivano sulla stessa riga.
  // `turnEl = null` E OBBLIGATORIO: punta ancora al turno precedente,
  // quindi i tool finivano fuori da `log` e i check non trovavano nulla.
  log.children = []; turnEl = null;
  handle("turn_start", {});
  handle("assistant", {content:"", tool_calls:[
    {id:"call_1", name:"list_dir", args:{path:"a"}},
    {id:"call_2", name:"list_dir", args:{path:"b"}},
  ]});
  handle("tool_end", {name:"list_dir", ok:true, result:"RISULTATO_UNO", id:"call_1"});
  handle("tool_end", {name:"list_dir", ok:true, result:"RISULTATO_DUE", id:"call_2"});
  out.abbinati = (function(){
    const tools = turnEl.querySelectorAll(".tool");
    const testi = tools.map(t => { const o = t.querySelector(".tool-out"); return o ? o.textContent : "?"; });
    return testi.join("|") + " #" + tools.length;
  })();
} catch (e) {
  out.ERROR = e.message + " @ " + (e.stack||"").split("\\n")[1];
}
console.log(JSON.stringify(out));
"""

script = harness + js + probe
tmp2 = os.path.join(tempfile.gettempdir(), "orchestra_ui_probe.js")
with open(tmp2, "w", encoding="utf-8") as f:
    f.write(script)

r = subprocess.run(["node", tmp2], capture_output=True, text=True, timeout=90)
if r.returncode != 0 or not r.stdout.strip():
    check("probe eseguita", False, (r.stderr or "")[:400])
    res = {}
else:
    res = json.loads(r.stdout.strip().splitlines()[-1])
    check("probe eseguita senza eccezioni", "ERROR" not in res, res.get("ERROR", ""))

print("\n[5] Comportamento degli handler")
check("renderStats scrive i contatori", "3" in res.get("stats", "") and "tok" in res.get("stats", ""),
      res.get("stats", ""))
check("renderStats usa il DOM, non innerHTML",
      res.get("statsViaNodi", 0) > 3 and res.get("statsTestoGrezzo") == 0,
      f"nodi={res.get('statsViaNodi')} testo_grezzo={res.get('statsTestoGrezzo')}")
check("stato vuoto mostra il trattino", res.get("empty") == "—", repr(res.get("empty")))
check("occupato disabilita l'input", res.get("busyInputDisabled") is True)
check("occupato disabilita l'invio", res.get("busySendDisabled") is True)
check("occupato abilita annulla", res.get("busyCancelEnabled") is True)
check("libero riabilita l'input", res.get("idleInputEnabled") is True)
check("pallino verde da libero", "ok" in res.get("idleDot", ""), res.get("idleDot", ""))
check("non pronto tiene l'input chiuso", res.get("notReadyInput") is True)
check("user e assistant in log", "user" in " ".join(res.get("roles", [])) and
      "assistant" in " ".join(res.get("roles", [])), str(res.get("roles")))
check("gli eventi aggiungono nodi", res.get("nodesAfterAll", 0) > 8, str(res.get("nodesAfterAll")))
check("reset svuota il log", res.get("afterReset") == 0, str(res.get("afterReset")))
check("snapshot ricostruisce 2 messaggi", res.get("snapshotMsgs") == 2, str(res.get("snapshotMsgs")))
check("snapshot scarta i messaggi vuoti", res.get("snapshotEmpty") == 0, str(res.get("snapshotEmpty")))
check("snapshot sopravvive a content null", res.get("snapshotRendered") is True)
check("snapshot con null: 3 messaggi (2 user + 1 assistant)",
      res.get("snapshotNullMsgs") == 3, str(res.get("snapshotNullMsgs")))
check("snapshot con null: niente righe bianche",
      res.get("snapshotNullEmpty") == 0, str(res.get("snapshotNullEmpty")))
check("due tool identici abbinati per id",
      res.get("abbinati") == "RISULTATO_UNO|RISULTATO_DUE #2",
      str(res.get("abbinati")))
check("banner di errore mostrato", "configurazione" in res.get("banner", ""), res.get("banner", ""))
check("send con spazi non spara nulla", res.get("emptySendNoop") is True)

os.unlink(tmp)
os.unlink(tmp2)
print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
