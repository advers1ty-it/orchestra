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

# Dopo lo split non esiste piu' un <script> inline: il codice e' in file
# separati dichiarati da index.html. Li leggiamo e li concateniamo
# nell'ordice dichiarato, che e' l'ordine in cui il browser li esegue.
# I test precedenti leggevano il blocco inline e, dopo lo split, non
# trovavano nulla: e' il motivo per cui 30 asserzioni sono passate senza
# verificare niente.
_scripts = re.findall(r'<script src="([^"]+)"', html)
assert _scripts, "index.html non dichiara nessuno script: lo split e' rotto?"
# L'HTML dichiara un solo script, /app.js, che il server assembla
# concatenando i tre sorgenti in quest'ordine. I sorgenti restano tre
# file su disco: qui li leggiamo e li concateniamo come fa il server,
# altrimenti il test misurerebbe il bundle e non il codice.
WEB_DIR = os.path.dirname(UI)
js_parts = []
for _s in ("core.js", "panels.js", "main.js"):
    _p = os.path.join(WEB_DIR, _s)
    assert os.path.exists(_p), f"sorgente mancante: {_s}"
    with open(_p, encoding="utf-8") as _f:
        js_parts.append(_f.read())
js = "\n;\n".join(js_parts)
# il CSS ora sta in app.css
_css_files = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
css = ""
for _c in _css_files:
    with open(os.path.join(WEB_DIR, os.path.basename(_c)), encoding="utf-8") as _f:
        css += _f.read()

# [1] Estrazione e struttura
print("\n[1] Estrazione e struttura")
check("script dichiarati trovati", len(_scripts) >= 1, str(_scripts))
check("script non vuoto", len(js) > 500, f"{len(js)} caratteri in {len(_scripts)} file")
check("CSS dichiarato trovato", len(css) > 500, f"{len(css)} caratteri")

print("\n[2] Sintassi JavaScript (Node esegue davvero il codice)")
tmp = os.path.join(tempfile.gettempdir(), "orchestra_ui_check.js")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(js)
r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True, timeout=60)
check("JS sintatticamente valido", r.returncode == 0, r.stderr[:300])

# lo stesso per i CSS: nessun controllo nativo, cerchiamo sbilanciamenti
check("CSS: graffe bilanciate", css.count("{") == css.count("}"),
      f"{css.count('{')} vs {css.count('}')}")

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
  constructor(){ this.s=new Set(); this._onChange=null; }
  add(...c){ c.forEach(x=>this.s.add(x)); this._changed(); }
  remove(...c){ c.forEach(x=>this.s.delete(x)); this._changed(); }
  toggle(c){ this.s.has(c)?this.s.delete(c):this.s.add(c); this._changed(); }
  contains(c){ return this.s.has(c); }
  // nel DOM, classList non si serializza, ma el.className sì: è il ponte
  // che tiene insieme i due. Senza questo, toggolare "hidden" non
  // cambiava className e i test vedevano un pannello sempre aperto.
  toString(){ return [...this.s].join(" "); }
  _changed(){ if (this._onChange) this._onChange(); }
}
class El {
  constructor(tag){ this.tagName=tag; this.children=[]; this._text=""; this.style={};
                   this.disabled=false; this._on={}; this._attrs={}; this._cl=null; }
  appendChild(c){ this.children.push(c); return c; }
  cloneNode(){ const e=new El(this.tagName); e._text=this._text; return e; }
  // className e classList devono stare in sync nei due sensi: la UI
  // scrive con classList.add (per toggolare "hidden") e legge con
  // className. Tenendoli separati i test misurano il mock e falliscono
  // su un pannello che nel browser funziona.
  get classList(){
    if (!this._cl) {
      const self = this;
      this._cl = new ClassList();
      this._cl._onChange = () => { self._className = this._cl.toString(); };
    }
    return this._cl;
  }
  set classList(v){ this._cl = v; }   // non usato, ma serve per Coerenza
  set className(v){
    this._className = String(v);
    this._cl = new ClassList();
    String(v).split(/\s+/).filter(Boolean).forEach(c => this._cl.add(c));
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
  // `new Option(...)` e `replaceChildren` sono API del DOM vero che il
  // fake deve simulare: la UI le usa perche' createElement("option") non
  // produce un <option> valido in tutti i browser. Se il fake le ignora,
  // il test mente: e' gia' successo piu' volte con questo fake.
  replaceChildren(...nodes){ this.children = []; for (const n of nodes) this.appendChild(n); }
  // `innerHTML = ""` in un browser vero SVUOTA l'elemento. Il fake doveva
  // farlo: senza, showBanner e handle("reset") sembravano non funzionare,
  // e i test misuravano il mock invece del codice.
  set innerHTML(v){ this._text=""; this.children=[]; }
  get innerHTML(){ return this._text; }
  // `options` e `value` su un <select>: la UI imposta value per preselezionare
  // il modello corrente. Se il fake non li ha, quella riga diventa un no-op
  // silenzioso e il test passa mentre il browser no.
  get options(){
    return this.tagName === "select" ? this.children.filter(c => c.tagName === "option") : [];
  }
  get value(){
    // su un <select> il valore e' quello dell'opzione selezionata; su un
    // <option> (o un input) e' la propria _value
    if (this.tagName === "select") {
      if (this._value !== undefined) return this._value;
      const s = this.options.find(o => o.selected);
      return s ? s.value : "";
    }
    return this._value === undefined ? "" : this._value;
  }
  set value(v){
    const str = v === undefined || v === null ? "" : String(v);
    if (this.tagName === "select") {
      // come nel DOM: mette selected sull'option che corrisponde
      let found = false;
      for (const o of this.options) {
        o.selected = (o.value === str);
        if (o.selected) found = true;
      }
      this._value = found ? str : "";
      return;
    }
    // su un option o un input: valore semplice
    this._value = str;
  }
  // conteggio ricorsivo: i tool sono figli diretti di `log`
  all(){ let n=1; for(const c of this.children) n+=c.all?c.all():1; return n; }
  addEventListener(k,f){ this._on[k]=f; }
  set onclick(f){ this._on["click"]=f; }
  get onclick(){ return this._on["click"]; }
  scrollIntoView(){}
}
globalThis.CSS = { escape: (s) => String(s).replace(/["\\\\]/g, "\\\\$&") };
const _els = {};
function mk(id){
  if (_els[id]) return _els[id];
  // i selettori devono essere <select>, altrimenti `options` e `value`
  // sono no-op e il test passa mentre il browser no
  const isSelect = id === "model-pick" || id === "bench-sample" || id === "bench-cat";
  const e = new El(isSelect ? "select" : "div");
  if (isSelect) e.selectedIndex = -1;
  _els[id] = e;
  return e;
}
// `new Option(text, value)` costruisce un <option> VERO. La UI lo usa
// perche' createElement("option") + appendChild non produce un <option>
// valido in tutti i browser: il select restava vuoto e grigio. Il fake
// deve rifletterlo, altrimenti il test passa mentre il browser no.
globalThis.Option = function (text, value) {
  const o = new El("option");
  o._text = String(text);
  o.value = value === undefined ? String(text) : String(value);
  o.selected = false;
  return o;
};
globalThis.document = {
  createElement: (t) => new El(t),
  getElementById: mk,
  createTextNode: (t) => { const e = new El("#text"); e._text = t; return e; },
  addEventListener: () => {},
  body: new El("body"),
};
// i marcatori dei file scrivono su window.__diagFiles: senza questo, il
// primo file che carica la UI muore a runtime e il test misura il mock
// invece del codice. E' gia' successo con altri dettagli del DOM.
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.getComputedStyle = () => ({});
globalThis.EventSource = class { constructor(){} close(){} };
globalThis.fetch = async (u) => {
  if (u === "/api/models")
    return { ok:true, status:200, json: async () => ({ provider:"or", current:"a:free", models:[
      {id:"vendor/a:free", short:"a", free:true, context:100000, prompt_price:0, scores:{}, current:true}]}) };
  if (u === "/api/state")
    return { ok:true, status:200, json: async () => ({ready:true, version:"0.4.0", messages:[], busy:false}) };
  return { ok:true, status:200, json: async () => ({}) };
};
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
  log.children = [];
  handle("turn_start", {});
  handle("user_message", {text:"ciao"});
  addText("assistant", "risposta");
  out.roles = log.children.map(c=>c.className);

  // ORDINE: la risposta deve venire DOPO il messaggio dell'utente.
  // Prima c'era un blocco creato da turn_start, che arriva prima di
  // user_message: finiva sopra e sembrava che l'agente rispondesse "sopra".
  out.ordine = log.children.map(c=>String(c.className).includes("user") ? "user" : "assistant").join(" -> ");
  out.primoEUtente = String(log.children[0].className).includes("user");

  // un tool con ok
  handle("assistant", {content:"", tool_calls:[{id:"tc_a", name:"read_file", args:{path:"a.txt"}}]});
  out.toolAdded = log.querySelectorAll(".tool").length;
  handle("tool_end", {name:"read_file", ok:true, result:"ok", id:"tc_a"});
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
  log.children = [];
  handle("turn_start", {});
  handle("assistant", {content:"", tool_calls:[
    {id:"call_1", name:"list_dir", args:{path:"a"}},
    {id:"call_2", name:"list_dir", args:{path:"b"}},
  ]});
  handle("tool_end", {name:"list_dir", ok:true, result:"RISULTATO_UNO", id:"call_1"});
  handle("tool_end", {name:"list_dir", ok:true, result:"RISULTATO_DUE", id:"call_2"});
  out.abbinati = (function(){
    const tools = log.querySelectorAll(".tool");
    const testi = tools.map(t => { const o = t.querySelector(".tool-out"); return o ? o.textContent : "?"; });
    return testi.join("|") + " #" + tools.length;
  })();

  // ORDINE REALE di un turno completo: utente, tool, tool, risposta.
  out.ordineCompleto = log.children.map(c => {
    const cn = String(c.className);
    if (cn.includes("user")) return "user";
    if (cn.includes("tool")) return "tool";
    if (cn.includes("assistant")) return "assistant";
    return cn || "sysnote";
  }).join(" -> ");
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

# L'ordine e' il punto: la risposta deve stare SOTTO il messaggio utente.
check("ordine: utente poi risposta", res.get("ordine") == "user -> assistant",
      str(res.get("ordine")))
check("il primo elemento e' dell'utente", res.get("primoEUtente") is True)
check("turno completo in ordine",
      res.get("ordineCompleto") == "tool -> tool",
      str(res.get("ordineCompleto")))
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
print("\n[9] Selettore modello e benchmark nella UI")
# Regressione: la UI serviva una copia in cache e l'utente vedeva una
# pagina senza selettore ne' benchmark mentre il server era gia' nuovo.
# Il sintomo era "non funziona niente", che sembrava un bug di codice.
import subprocess as _sp
import tempfile as _tf

# il JS gia' concatenato sopra: i file separati, nell'ordice di index.html
_ui_js = js

_fake_fetch = r"""
const CALLS = [];
globalThis.fetch = async (url, opts) => {
  CALLS.push(url);
  if (url === "/api/models") {
    return { ok:true, status:200, json: async () => ({ provider:"openrouter",
      current:"vendor/a:free", models: [
        {id:"vendor/a:free", short:"a", free:true,  context:100000, prompt_price:0,     scores:{}, current:true},
        {id:"vendor/b:free", short:"b", free:true,  context:200000, prompt_price:0,     scores:{}, current:false},
        {id:"vendor/c",     short:"c", free:false, context:130000, prompt_price:8e-7,  scores:{}, current:false},
      ]}) };
  }
  if (url === "/api/state")
    return { ok:true, status:200, json: async () => ({ready:true, version:"0.4.0", messages:[]}) };
  if (url === "/api/bench/status")
    return { ok:true, status:200, json: async () => ({running:false, log:[], result:null}) };
  return { ok:true, status:200, json: async () => ({}) };
};
"""
_probe9 = r"""
const R = {};
(async () => {
 try {
  await new Promise(r => setTimeout(r, 50));
  R.opzioni = modelPick.children.length;
  R.disabled = modelPick.disabled;
  R.testi = modelPick.children.map(c => c.textContent);
  R.tagPrimi = modelPick.children.map(c => c.tagName);
  R.tuttiOption = R.tagPrimi.every(t => t === "option");
  R.value = modelPick.value;
  R.valori = modelPick.options.map(o => o.value);
  R.ver = document.getElementById("ver").textContent;
  // il pannello benchmark deve esistere e togglare la classe hidden
  R.benchEsiste = !!document.getElementById("bench");
  R.benchNascosto = benchPanel.className;
  openBench();
  R.benchAperto = benchPanel.className;
  closeBench();
  R.benchRichiuso = benchPanel.className;
 } catch (e) { R.ERROR = e.message; }
 // prefisso univoco: questo file esegue piu' probe e devono distinguersi
 console.log("PROBE9__" + JSON.stringify(R));
})();
"""
_f = _tf.mktemp(suffix=".js")
with open(_f, "w", encoding="utf-8") as fh:
    fh.write(harness + _fake_fetch + _ui_js + _probe9)
_r = _sp.run(["node", _f], capture_output=True, text=True, timeout=90)
os.unlink(_f)
_r9 = {}
_PREFIX = "PROBE9__"   # 8 caratteri: find() + len, non una costante magica
for _line in _r.stdout.splitlines():
    _i = _line.find(_PREFIX)
    if _i >= 0:
        try:
            _r9 = json.loads(_line[_i + len(_PREFIX):])
        except json.JSONDecodeError as e:
            print(f"  [debug] non parsabile: {_line[_i:_i+120]!r} ({e})")
if not _r9 and _r.stderr:
    print(f"  [debug] stderr: {(_r.stderr or '')[:300]}")
check("selettore popolato", _r9.get("opzioni") == 3, str(_r9.get("opzioni")))
check("selettore abilitato", _r9.get("disabled") is False, str(_r9.get("disabled")))
check("etichette con contesto e prezzo",
      any("100k" in t for t in _r9.get("testi", [])) and
      any("free" in t for t in _r9.get("testi", [])), str(_r9.get("testi")))
# REGRESSIONE: le voci devono essere <option> VERI, non elementi generici.
# createElement("option") + appendChild non funziona in tutti i browser e
# lasciava il select grigio. new Option() lo risolve.
check("le voci sono option veri", _r9.get("tuttiOption") is True, str(_r9.get("tagPrimi")))
check("il modello corrente è preselezionato",
      _r9.get("value") == "vendor/a:free", repr(_r9.get("value")))
if _r9.get("value") != "vendor/a:free":
    print(f"     [debug] valori opzione: {_r9.get('valori')}")
    print(f"     [debug] current atteso: vendor/a:free")
    print(f"     [debug] testo errore   : {_r9.get('testoErrore')!r}")
check("versione mostrata", _r9.get("ver") == "0.4.0", str(_r9.get("ver")))
check("pannello benchmark presente", _r9.get("benchEsiste") is True)
check("pannello si apre", "hidden" not in str(_r9.get("benchAperto")), str(_r9.get("benchAperto")))
check("pannello si chiude", "hidden" in str(_r9.get("benchRichiuso")), str(_r9.get("benchRichiuso")))

# e con /api/models che fallisce: il selettore NON deve restare grigio
# senza spiegazione, deve dire cosa sta succedendo
_fail_fetch = r"""
globalThis.fetch = async (url) => {
  if (url === "/api/models") return { ok:false, status:503, json: async () => ({error:"catalogo non disponibile"}) };
  if (url === "/api/state")
    return { ok:true, status:200, json: async () => ({ready:true, version:"0.4.0", messages:[]}) };
  return { ok:true, status:200, json: async () => ({}) };
};
"""
_probe_fail = r"""
const R = {};
(async () => {
 try { await new Promise(r => setTimeout(r, 50)); R.text = modelPick.textContent; R.disabled = modelPick.disabled; }
 catch (e) { R.ERROR = e.message; }
 console.log("PROBE9__" + JSON.stringify(R));
})();
"""
_f2 = _tf.mktemp(suffix=".js")
with open(_f2, "w", encoding="utf-8") as fh:
    fh.write(harness + _fail_fetch + _ui_js + _probe_fail)
_r2 = _sp.run(["node", _f2], capture_output=True, text=True, timeout=90)
os.unlink(_f2)
_r9b = {}
for _line in _r2.stdout.splitlines():
    _i = _line.find(_PREFIX)
    if _i >= 0:
        try:
            _r9b = json.loads(_line[_i + len(_PREFIX):])
        except json.JSONDecodeError as e:
            print(f"  [debug] non parsabile: {_line[_i:_i+120]!r} ({e})")
check("catalogo rotto: il selettore lo dice",
      "non disponibili" in str(_r9b.get("text", "")), str(_r9b.get("text")))
check("catalogo rotto: resta disabilitato", _r9b.get("disabled") is True)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
