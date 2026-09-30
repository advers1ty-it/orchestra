"""Esegue i file JS del frontend come fa il browser, in ordine.

Lo split e' stato fatto tagliando per numero di riga senza eseguire
niente, e ha prodotto file che non partivano. I test precedenti non
potevano vederlo: leggevano il blocco <script> inline, che dopo lo split
non esiste piu'. Qui si esegue davvero, nell'ordine che dichiara
index.html, e si controlla che:

1. nessun file lancia un errore (una ReferenceError ferma tutto: e' la
   causa di "nessun pulsante funziona")
2. i simboli che un file definisce sono visibili agli altri
3. il selettore si popola

In un browser let/const di uno <script> sono visibili agli altri, quindi
i file vengono concatenati ed eseguiti insieme: e' l'ordine di
caricamento reale.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "orchestra", "web")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------- struttura
with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
    html = fh.read()

scripts = re.findall(r'<script src="([^"]+)"', html)
styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)

print("\n[1] Struttura")
check("l'HTML dichiara piu' script", len(scripts) >= 2, str(scripts))
check("ogni file dichiarato esiste",
      all(os.path.exists(os.path.join(WEB, s.lstrip("/"))) for s in scripts), str(scripts))
check("ogni CSS dichiarato esiste",
      all(os.path.exists(os.path.join(WEB, s.lstrip("/"))) for s in styles), str(styles))
# La diagnostica e' inline per scelta: deve girare anche se i file
# esterni non arrivano, altrimenti non puoi sapere che non sono arrivati.
# E' l'unico blocco inline ammesso, ed e' identificabile.
_inline_scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
check("nessun CSS inline oltre alla diagnostica", html.count("<style>") <= 1,
      f"{html.count('<style>')} blocchi style")
check("l'unico script inline e' la diagnostica",
      len(_inline_scripts) <= 1 and
      (not _inline_scripts or "__diagErrors" in _inline_scripts[0]),
      f"{len(_inline_scripts)} script inline")
check("la diagnostica c'è", "__diagErrors" in html)
check("la diagnostica viene prima dei file esterni",
      html.index("__diagErrors") < html.index("script src"))
# Gli script stanno in fondo al body SENZA defer: il browser li esegue in
# ordine documentale, quindi non serve defer per garantire l'ordine, e toglie
# un attributo da interpretare. I file sono gia' in coda al body, quindi
# eseguono a DOM pronto.
check("gli script sono in fondo al body",
      html.index("<body") < html.index("script src"), "prima dei tag c'e' altro")
check("nessuno script usa defer", " defer" not in html,
      "defer non serve e aggiunge un modo di fallire")
check("core.js viene per primo", scripts and "core" in scripts[0], str(scripts))

# ---------------------------------------------------------------- esecuzione
sources = {}
for s in scripts:
    name = os.path.basename(s)
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        sources[name] = fh.read()

# harness: DOM finto, ma con lo scope condiviso che ha il browser
harness = """
const IDS = ["log","main","input","btn-send","btn-cancel","btn-reset","dot","stats","conn",
             "model-pick","btn-bench","bench","bench-sample","bench-cat","bench-run",
             "bench-log","bench-out","bench-close","ver"];
function mkEl(tag) {
  const isSelect = tag === "select";
  const st = {
    tagName: tag, children: [], _text: "", className: "", style: {}, dataset: {},
    disabled: false, _value: undefined, selectedIndex: -1,
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get innerHTML() { return ""; },
    set innerHTML(v) { if (v === "") this.children = []; },
    appendChild(c) { this.children.push(c); return c; },
    replaceChildren() { this.children = Array.prototype.slice.call(arguments);
                         for (const n of this.children) {} },
    get options() { return isSelect ? this.children.filter(c => c.tagName === "option") : []; },
    get value() {
      if (isSelect) {
        if (this._value !== undefined) return this._value;
        const s = this.options.find(o => o.selected);
        return s ? s.value : "";
      }
      return this._value === undefined ? "" : this._value;
    },
    set value(v) {
      const str = (v === undefined || v === null) ? "" : String(v);
      if (isSelect) {
        let f = false;
        for (const o of this.options) { o.selected = (o.value === str); if (o.selected) f = true; }
        this._value = f ? str : "";
        return;
      }
      this._value = str;
    },
    addEventListener(k, f) { this._on = this._on || {}; this._on[k] = f; },
    removeEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    scrollIntoView() {}, focus() {}, blur() {}, click() {},
    getBoundingClientRect() { return { top:0, left:0, width:100, height:30, bottom:30, right:100 }; },
  };
  st._cl = {
    _s: new Set(),
    add(...c) { c.forEach(x => st._s.add(x)); st.className = [...st._s].join(" "); },
    remove(...c) { c.forEach(x => st._s.delete(x)); st.className = [...st._s].join(" "); },
    toggle(c) { st._s.has(c) ? st._s.delete(c) : st._s.add(c); st.className = [...st._s].join(" "); },
    contains(c) { return st._s.has(c); },
  };
  return st;
}
globalThis.Option = function (text, value) {
  const o = mkEl("option");
  o._text = String(text);
  o.value = (value === undefined) ? String(text) : String(value);
  o.selected = false;
  return o;
};
const REG = {};
IDS.forEach(function (id) {
  const sel = id === "model-pick" || id === "bench-sample" || id === "bench-cat";
  REG[id] = mkEl(sel ? "select" : "div");
});
globalThis.document = {
  createElement: function (t) { return mkEl(t); },
  getElementById: function (id) { return REG[id] || null; },
  createTextNode: function (t) { const e = mkEl("#text"); e._text = String(t); return e; },
  addEventListener: function () {}, body: mkEl("body"),
};
// i marcatori dei file scrivono su window.__diagFiles
globalThis.window = globalThis;
globalThis.addEventListener = function () {};
globalThis.getComputedStyle = function () { return {}; };
globalThis.CSS = { escape: function (s) { return String(s); } };
globalThis.EventSource = class { constructor(u) { this.url = u; } close() {} };
globalThis.addEventListener = function () {};
globalThis.setInterval = function () { return 0; };
globalThis.clearInterval = function () {};
globalThis.fetch = async function (u) {
  if (u === "/api/models")
    return { ok:true, status:200, json: async () => ({ provider:"or", current:"vendor/a:free", models:[
      { id:"vendor/a:free", short:"a", free:true, context:100000, prompt_price:0, scores:{}, current:true },
      { id:"vendor/b:free", short:"b", free:true, context:200000, prompt_price:0, scores:{}, current:false },
    ] }) };
  if (u === "/api/state")
    return { ok:true, status:200, json: async () => ({ ready:true, version:"0.4.0", messages:[], busy:false }) };
  return { ok:true, status:200, json: async () => ({ running:false, log:[], result:null }) };
};
"""

probe = """
const OUT = { errore: null };
(async function () {
  try {
    await loadModels();
  } catch (e) {
    OUT.erroreCaricamento = e.message;
  }
  const fn = {};
  for (const n of ["loadModels","setBusy","addText","handle","send","openBench",
                   "renderStats","connect","showBanner","addTool","cancel","reset"])
    fn[n] = typeof eval(n);
  const vr = {};
  for (const n of ["log","main","input","btnSend","btnCancel","btnReset","dot","stats","conn","modelPick"])
    vr[n] = typeof eval(n);
  OUT.fn = fn; OUT.vr = vr;
  const mp = REG["model-pick"];
  OUT.opzioni = mp.children.length;
  OUT.disabled = mp.disabled;
  OUT.valori = mp.options.map(o => o.value);
  OUT.tagPrimi = mp.children.map(c => c.tagName);
  console.log("SPLIT" + JSON.stringify(OUT));
})();
"""

# scope condiviso: i file concatenati ed eseguiti insieme, come nel browser
joined = "\n;\n".join(sources[os.path.basename(s)] for s in scripts)

prog = harness + joined + "\n" + probe
f = tempfile.mktemp(suffix=".js")
with open(f, "w", encoding="utf-8") as fh:
    fh.write(prog)
r = subprocess.run(["node", f], capture_output=True, text=True, timeout=120)
try:
    os.unlink(f)
except OSError:
    pass

out = {}
for line in r.stdout.splitlines():
    if line.startswith("SPLIT"):
        out = json.loads(line[5:])

if not out:
    print("\n[2] Esecuzione")
    print("  NESSUN OUTPUT — il probe non e' arrivato in fondo")
    for line in (r.stderr or "").splitlines()[:10]:
        print("   ", line)
    print(f"\nPASS {len(PASS)}  FAIL {len(FAIL) + 1}")
    sys.exit(1)

print("\n[2] Esecuzione reale dei file, nell'ordine di index.html")
fn = out.get("fn", {})
mancanti = [k for k, v in fn.items() if v == "undefined"]
check("nessuna funzione mancante", not mancanti, str(mancanti))
vr = out.get("vr", {})
ref_mancanti = [k for k, v in vr.items() if v == "undefined"]
check("nessuna variabile mancante", not ref_mancanti, str(ref_mancanti))
check("nessun errore durante il caricamento", not out.get("erroreCaricamento"),
      out.get("erroreCaricamento", ""))

print("\n[3] Effetto")
check("loadModels ha girato", out.get("opzioni") == 2, str(out.get("opzioni")))
check("selettore abilitato", out.get("disabled") is False, str(out.get("disabled")))
check("opzioni vere", all(t == "option" for t in out.get("tagPrimi", [""])),
      str(out.get("tagPrimi")))
check("opzioni con value", all(out.get("valori") or []), str(out.get("valori")))
if r.stderr.strip():
    print("   [stderr]", r.stderr.strip().splitlines()[0][:200])

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
