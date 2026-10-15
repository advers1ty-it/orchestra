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
check("l'HTML dichiara uno script", len(scripts) >= 1, str(scripts))
check("ogni CSS dichiarato esiste",
      all(os.path.exists(os.path.join(WEB, s.lstrip("/"))) for s in styles), str(styles))
# La diagnostica e' inline per scelta: deve girare anche se i file
# esterni non arrivano, altrimenti non puoi sapere che non sono arrivati.
# E' l'unico blocco inline ammesso, ed e' identificabile dal marcatore.
# Il nome del marcatero e' cambiato quando la diagnostica e' diventata
# permanente (da __diagErrors a __diagFiles): e il test ne' si accorgeva
# ne' segnalava niente, perche' guardava una stringa sparita. Meglio
# riconoscerlo per quello che fa, non per un nome che puo' cambiare.
MARCATORE_DIAG = "__diagFiles"
_inline_scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
check("nessun CSS inline oltre alla diagnostica", html.count("<style>") <= 1,
      f"{html.count('<style>')} blocchi style")
check("l'unico script inline e' la diagnostica",
      len(_inline_scripts) <= 1 and
      (not _inline_scripts or MARCATORE_DIAG in _inline_scripts[0]),
      f"{len(_inline_scripts)} script inline")
check("la diagnostica c'è", MARCATORE_DIAG in html,
      "manca il marcatore della diagnostica inline")
check("la diagnostica viene prima dei file esterni",
      html.index(MARCATORE_DIAG) < html.index("script src"))
check("la diagnostica ascolta gli errori",
      'addEventListener("error"' in html,
      "senza ascoltare gli errori la barra non serve a nulla")
# Lo script esterno sta in <head> CON defer. E' la combinazione che
# funziona: in head gira presto (prima che il body esista, quindi
# getElementById restituisce null e il bundle muore alla prima riga),
# e defer rimanda l'esecuzione a DOM pronto, nell'ordine dei file. Senza
# defer il bundle parte a meta' pagina e muore; con lo script in fondo
# al body non partiva proprio. Entrambi i modi sono stati provati.
check("lo script esterno e' in head", html.index("script src") < html.index("<body"),
      "non e' in head")
check("lo script esterno ha defer", " defer" in html,
      "senza defer gira prima che il body esista")
# Un solo script esterno, non tre. Tre richieste = tre modi in cui la
# pagina resta a meta'; e il sintomo era esattamente quello: CSS
# applicato, script mai eseguiti. I file restano separati su disco,
# li assembla il server.
check("un solo script esterno", len(scripts) == 1 and scripts[0] == "/app.js",
      str(scripts))

# ---------------------------------------------------------------- esecuzione
# L'HTML dichiara un solo script (/app.js, assemblato dal server), ma
# i sorgenti restano tre file su disco. Li leggiamo nell'ordine con cui il
# server li concatena: e' l'ordine in cui il browser li esegue.
BUNDLE_ORDER = ("core.js", "panels.js", "modelpick.js", "main.js")

sources = {}
for name in BUNDLE_ORDER:
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        sources[name] = fh.read()
check("i sorgenti esistono", len(sources) == 4, str(list(sources)))
check("ogni sorgente si annuncia", all(
    "__diagFiles" in src for src in sources.values()),
    "un file non ha il marcatore: non si puo' sapere se e' partito")

# harness: DOM finto, ma con lo scope condiviso che ha il browser
harness = """
const IDS = ["log","main","input","btn-send","btn-cancel","btn-reset","dot","stats","conn","ver","ragionamento",
             "model-pick","model-btn","model-label","btn-bench","bench","bench-sample","bench-cat","bench-count",
             "bench-free","bench-allfree","bench-models","bench-none","bench-run","bench-status","bench-log","bench-out","bench-close",
             "btn-capacita","capacita","capacita-close","cap-filtro","cap-lista","cap-msg",
             "btn-opzioni","opzioni","opzioni-close","opzioni-deps","opzioni-nota","opt-context-note","opt-max-iters",
             "opt-model","opt-provider","opt-provider-msg","opt-reasoning","opt-tool-profile","provider-note","provider-pick",
             "reasoning-pick","routing-cat","routing-go","routing-out","routing-top","scope-note","scope-pick",
             "prova-model","prova-out","prova-prompt","prova-run","btn-verifica","verifica-file","verifica-pop","verifica-tipo",
             "prior-copertura","prior-go","prior-out",
             "btn-side","sidebar","side-cap","side-cerca","side-elenco","side-mem-aggiungi","side-mem-cerca","side-mem-elenco",
             "side-mem-input","side-mem-stat","side-msg","side-nuova","side-ricarica","side-riduci","side-skill","side-tracce",
             "side-traccia-dettaglio",
             "memoria-aggiungi","memoria-elenco","memoria-msg","memoria-nuovo","memoria-percorso",
             "skill-cartella","skill-categorie","skill-cestino","skill-cestino-nota","skill-filtro","skill-generate",
             "skill-generate-nota","skill-importa","skill-ricarica","skill-riepilogo","skill-scaricate","skill-svuota","skill-vista",
             "storico-elenco","storico-msg","storico-nuova","storico-ricarica",
             "permesso","permesso-dettaglio","permesso-mai","permesso-percorso","permesso-ses","permesso-una",
             "permessi-msg","permessi-prova","permessi-stato",
             "budget-day-cost","budget-global-msg","budget-month-cost","budget-msg","budget-reset","budget-salva",
             "budget-sess-cost","budget-sess-reqs","budget-sess-tokens","budget-task-cost","budget-task-iters","budget-task-tokens",
             "locali-avviso","gratis-lista","chiavi-lista",
             "btn-allega","btn-diagnosi","btn-onboard","file-input","allegati-lista","onboard","onboard-cards","onboard-skip",
             "btn-goal","goal-bar","goal-input","goal-profile","goal-kind","goal-priority","goal-depends",
             "goal-maxiters","goal-attempts","goal-partial","goal-criteri","goal-recovery","goal-start",
             "goal-run-next","goal-stop","goal-refresh","goal-status","goal-pronti",
             "goal-sched","goal-sched-stat"];
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
    removeAttribute() {}, hasAttribute() { return false; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    scrollIntoView() {}, focus() {}, blur() {}, click() {},
    getBoundingClientRect() { return { top:0, left:0, width:100, height:30, bottom:30, right:100 }; },
  };
  st._cl = {
    _s: new Set(),
    add(...c) { c.forEach(x => this._s.add(x)); st.className = [...this._s].join(" "); },
    remove(...c) { c.forEach(x => this._s.delete(x)); st.className = [...this._s].join(" "); },
    toggle(c) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); st.className = [...this._s].join(" "); },
    contains(c) { return this._s.has(c); },
  };
  st.classList = st._cl;
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
const SELECT_IDS = new Set(["model-pick","bench-sample","bench-cat","bench-count","provider-pick","opt-provider","opt-model","opt-tool-profile","opt-reasoning","reasoning-pick","routing-cat","scope-pick","goal-profile","goal-kind"]);
const INPUT_IDS = new Set(["bench-free","bench-allfree","file-input","goal-priority","goal-maxiters","goal-attempts","goal-partial","goal-depends","goal-input"]);
IDS.forEach(function (id) {
  if (INPUT_IDS.has(id)) {
    const el = mkEl("input");
    el.checked = false;
    el.files = [];
    REG[id] = el;
    return;
  }
  REG[id] = mkEl(SELECT_IDS.has(id) ? "select" : "div");
});
// Gli elementi del pannello a sezioni servono anche qui: il bundle
// chiama document.querySelectorAll(".opzioni-tab") e, senza,
// collegaSezioni() muore e i pulsanti di Opzioni restano scollegati.
// Il bundle e' servito col try/catch, quindi il fallimento non si
// vede: la pagina sembra funzionante e i tab non cambiano sezione.
["modello", "skill", "cestino", "servizi", "permessi", "gratis"].forEach(
  function (n) {
    const sez = mkEl("section");
    sez.dataset = { sez: n };
    if (n !== "modello") sez.setAttribute("hidden", "");
    REG["opz-sez-" + n] = sez;
    const tab = mkEl("button");
    tab.dataset = { sez: n };
    REG["opz-tab-" + n] = tab;
  });
globalThis.document = {
  createElement: function (t) { return mkEl(t); },
  getElementById: function (id) { return REG[id] || null; },
  createTextNode: function (t) { const e = mkEl("#text"); e._text = String(t); return e; },
  addEventListener: function () {}, body: mkEl("body"),
  querySelectorAll: function (sel) {
    const out = [];
    const push = function (e) { if (e && out.indexOf(e) < 0) out.push(e); };
    if (sel === ".opz-sez" || sel === "section.opz-sez") {
      ["modello", "skill", "cestino", "servizi", "permessi", "gratis"]
        .forEach(function (n) { push(REG["opz-sez-" + n]); });
    } else if (sel === ".opzioni-tab" || sel === "button.opzioni-tab") {
      ["modello", "skill", "cestino", "servizi", "permessi", "gratis"]
        .forEach(function (n) { push(REG["opz-tab-" + n]); });
    } else if (sel === ".opzioni-nav" || sel === "nav.opzioni-nav") {
      push(REG["opzioni-nav"]);
    }
    return out;
  },
  querySelector: function (sel) {
    const t = this.querySelectorAll(sel);
    return t.length ? t[0] : null;
  },
};
// i marcatori dei file scrivono su window.__diagFiles
globalThis.window = globalThis;
globalThis.localStorage = (() => {
  const m = new Map();
  return {
    getItem(k) { return m.has(String(k)) ? m.get(String(k)) : null; },
    setItem(k, v) { m.set(String(k), String(v)); },
    removeItem(k) { m.delete(String(k)); },
    clear() { m.clear(); },
  };
})();
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
    return { ok:true, status:200, json: async () => ({ ready:true, version:"0.5.0", messages:[], busy:false }) };
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
  OUT.goalFn = {};
  for (const n of ["goalGate","goalRiga","caricaGoal"])
    OUT.goalFn[n] = typeof eval(n);
  OUT.gateOk = goalGate({status:"done", last_output:"fatto"}).testo;
  OUT.gateKo = goalGate({status:"failed", error:"accettazione fallita: stop anomalo: max_iterations"}).testo;
  OUT.gateParz = goalGate({status:"done", last_output:"[parziale accettato: stop anomalo: max_iterations]" + String.fromCharCode(10) + "quasi"}).testo;
  OUT.gateAttesa = goalGate({status:"pending"}).testo;
  const mp = REG["model-pick"];
  OUT.opzioni = mp.children.length;
  OUT.disabled = mp.disabled;
  OUT.valori = mp.options.map(o => o.value);
  OUT.tagPrimi = mp.children.map(c => c.tagName);
  console.log("SPLIT" + JSON.stringify(OUT));
})().catch((e) => { console.log("SPLIT" + JSON.stringify({crash: String(e && e.stack || e)})); });
"""

# scope condiviso: i file concatenati ed eseguiti insieme, come nel browser
joined = "\n;\n".join(sources[name] for name in BUNDLE_ORDER)

prog = (harness + joined + "\n"
        + "try {\n" + probe + "\n} catch (e) {\n"
        + '  console.log("SPLIT" + JSON.stringify({crash: String(e && e.stack || e)}));\n'
        + "}\n")
f = tempfile.mktemp(suffix=".js")
with open(f, "w", encoding="utf-8") as fh:
    fh.write(prog)
r = subprocess.run(["node", f], capture_output=True, text=True, timeout=120)
# Il file resta su disco se il probe non risponde: leggerlo dice
# l'errore vero, e "NESSUN OUTPUT" da solo non dice dove guardare.
pass  # il file resta

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

print("\n[4] Pannello goal: funzioni e gate visivo")
gf = out.get("goalFn", {})
check("goalGate definita", gf.get("goalGate") == "function", str(gf))
check("goalRiga definita", gf.get("goalRiga") == "function", str(gf))
check("caricaGoal definita", gf.get("caricaGoal") == "function", str(gf))
check("gate ok su done", out.get("gateOk") == "gate: ok", str(out.get("gateOk")))
check("gate bocciato su accettazione fallita",
      out.get("gateKo") == "gate: bocciato", str(out.get("gateKo")))
check("gate parziale dichiarato",
      out.get("gateParz") == "gate: parziale", str(out.get("gateParz")))
check("gate in attesa su pending",
      out.get("gateAttesa") == "gate: in attesa", str(out.get("gateAttesa")))
if r.stderr.strip():
    print("   [stderr]", r.stderr.strip().splitlines()[0][:200])

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
