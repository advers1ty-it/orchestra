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

# La temporal dead zone colpisce quando una funzione che legge una
# `const` viene CHIAMATA prima che la `const` sia dichiarata. Il
# runtime te lo dice in una console ("Cannot access 'progElenco'
# before initialization") e la promise si rifiuta: la pagina resta
# viva, la lista resta vuota, e un test che guarda solo "il bundle ha
# girato" dice che va tutto bene.
#
# Il controllo e' a runtime, non statico: e' il trappola sotto
# (__rifiutate) a beccarlo, perche' a runtime la chiamata a livello
# di file esegue davvero prima della dichiarazione. Uno statico
# dovrebbe indovinare quali chiamate sono "a livello di file", e
# sbaglia.

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
             "side-traccia-dettaglio","traccia-modal","traccia-chiudi",
              "side-progetto-input","side-progetto-lista","side-progetto-ok","side-progetto-fatti",
              "side-sez-progetti","side-progetti","side-progetto-nuovo-nome","side-progetto-nuovo-percorso",
              "side-progetto-nuovo-ok","side-progetti-file","side-progetto-nuovo-alias",
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
// Le promesse rifiutate NON fanno fallire il bundle: il codice va avanti
// e la pagina sembra funzionante. Il sintomo era una lista che restava
// vuota e una riga in console ("PROMESSA RIFIUTATA: Cannot access
// 'progElenco' before initialization") — l'unico posto in cui si vedeva.
// Senza questa trappola il test diceva "tutto va bene" mentre la coda
// dei progetti non c'era.
globalThis.__rifiutate = [];
process.on("unhandledRejection", function (e) {
  const msg = String((e && e.message) || e);
  globalThis.__rifiutate.push(msg);
  // Stampata su una riga a parte: il test legge l'ULTIMA riga SPLIT,
  // e una rejection emessa dopo quella stampa non ci arriverebbe.
  // Su una riga propria la vede comunque, quando arriva.
  console.log("SPLITREJ" + JSON.stringify(msg));
});
globalThis.addEventListener = function () {};
globalThis.setInterval = function () { return 0; };
// setTimeout resta FINTO, come prima: e' quello che il bundle
// si aspetta, e i suoi timer non devvero girare davvero in un test
// (uno di quelli crashava Node, e il test moriva per quello invece
// di dire perche').
//
// Ma il PROBE ha bisogno di tempo vero: e' l'attesa che serve alle
// promise del bundle per assestarsi, ed e' proprio li' che la
// temporal dead zone si manifesta. Senza, la rejection non arriva
// mai e il test passerebbe senza vedere nulla.
// Il timer di Node viene salvato PRIMA: sovrascrivendolo, la
// funzione chiamerebbe se stessa all'infinito.
const _setTimeoutNode = setTimeout;
globalThis.__setTimeoutReale = function (f, t) { return _setTimeoutNode(f, t); };
globalThis.setTimeout = function () { return 0; };
// clearTimeout deve essere coerente col setTimeout finto: se il
// bundle chiama clearTimeout su un id che non e' un timer vero,
// Node lo accetta, ma se il timer e' finto e il clear no', non
// succede niente. Coerenza, non funzionalita'.
globalThis.clearTimeout = function () { return 0; };
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
                   "renderStats","connect","showBanner","addTool","cancel","reset"]) {
    try { fn[n] = typeof eval(n); } catch (e) { fn[n] = "ASSENTE: " + e.message; }
  }
  const vr = {};
  for (const n of ["log","main","input","btnSend","btnCancel","btnReset","dot","stats","conn","modelPick"]) {
    try { vr[n] = typeof eval(n); } catch (e) { vr[n] = "ASSENTE: " + e.message; }
  }
  OUT.fn = fn; OUT.vr = vr;
  OUT.goalFn = {};
  for (const n of ["goalGate","goalRiga","caricaGoal"]) {
    try { OUT.goalFn[n] = typeof eval(n); } catch (e) { OUT.goalFn[n] = "ASSENTE: " + e.message; }
  }
  // Il percorso dei progetti, perche' e' l'ultima cosa aggiunta e
  // tocca una `const` dichiarata in fondo al file: se il caricamento
  // parte PRIMA della dichiarazione, la promise si rifiuta e la lista
  // dei progetti resta vuota — senza che nessun errore fermi il bundle.
  // Il tipo di ogni simbolo, senza far crashare il probe: se uno
  // manca, `eval(n)` su un nome inesistente lancia ReferenceError e
  // il probe muore PRIMA di stampare — e allora il test non dice
  // niente, solo "13 falliti" senza spiegazione.
  OUT.progFn = {};
  for (const n of ["caricaProgetto","caricaProgetti","impostaProgetto"]) {
    try { OUT.progFn[n] = typeof eval(n); }
    catch (e) { OUT.progFn[n] = "ASSENTE: " + e.message; }
  }
  try { OUT.progElenco = typeof eval("progElenco"); }
  catch (e) { OUT.progElenco = "ASSENTE: " + e.message; }
  // Il bundle deve SAPERE che il progetto e' cambiato: e' l'evento
  // che dice all'utente in che cartella si sta scrivendo. Un bundle
  // che non lo ascolta cambia cartella in silenzio, e l'utente
  // crede di lavorare da una parte mentre i file finiscono altrove.
  OUT.progEvent = typeof eval("handle");
  if (OUT.progEvent === "function") {
    // Si chiama davvero: se il ramo nel switch non esiste, non
    // succede nulla e non si vede. Il testo della nota e' la prova
    // che il ramo c'e'.
    try {
      const _prima = log.children.length;
      handle("progetto_cambiato", {progetto:"Sito Ristorante", percorso:"D:/lavori/sito"});
      OUT.progNota = (log.children.length > _prima)
        ? (log.children[log.children.length-1].textContent || "") : "";
    } catch (e) { OUT.progNota = "ERRORE: " + e.message; }
  }
  // Il tempo alle promise: e' quello che serve a una rejection
  // (temporal dead zone) per manifestarsi. Il timer qui e' quello
  // VERO, non quello finto del bundle: e' l'unico posto in cui
  // deve scadere.
  await new Promise(function (r) { globalThis.__setTimeoutReale(r, 60); });
  // Anche i gate: se `goalGate` non esiste, il probe muore qui e
  // non stampa niente. Ogni chiamata e' protetta, cosi' il test
  // dice QUALE pezzo manca invece di tacere.
  try {
    OUT.gateOk = goalGate({status:"done", last_output:"fatto"}).testo;
    OUT.gateKo = goalGate({status:"failed", error:"accettazione fallita: stop anomalo: max_iterations"}).testo;
    OUT.gateParz = goalGate({status:"done", last_output:"[parziale accettato: stop anomalo: max_iterations]" + String.fromCharCode(10) + "quasi"}).testo;
    OUT.gateAttesa = goalGate({status:"pending"}).testo;
  } catch (e) {
    OUT.gateErrore = String(e && e.message || e);
  }
  const mp = REG["model-pick"];
  OUT.opzioni = mp.children.length;
  OUT.disabled = mp.disabled;
  OUT.valori = mp.options.map(o => o.value);
  OUT.tagPrimi = mp.children.map(c => c.tagName);
  console.log("SPLIT" + JSON.stringify(OUT));
})().catch((e) => { console.log("SPLIT" + JSON.stringify({crash: String(e && e.stack || e)})); });
"""

# scope condiviso: i file concatenati ed eseguiti insieme, come nel browser
def _esegui(src_map):
    """Esegue il bundle e restituisce (out, rifiutate, stderr)."""
    f = tempfile.mktemp(suffix=".js")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(harness + "\n;\n".join(src_map[n] for n in BUNDLE_ORDER)
                 + "\n" + "try {\n" + probe + "\n} catch (e) {\n"
                 + '  console.log("SPLIT" + JSON.stringify({crash: String(e && e.stack || e)}));\n'
                 + "}\n")
    res = subprocess.run(["node", f], capture_output=True, text=True, timeout=120)
    o, rej = {}, []
    for line in res.stdout.splitlines():
        if line.startswith("SPLITREJ"):
            rej.append(json.loads(line[8:]))
        elif line.startswith("SPLIT"):
            o = json.loads(line[5:])
    rej.extend(o.pop("rifiutate", []) or [])
    o["rifiutate"] = rej
    return o, rej, (res.stderr or ""), f


out, rifiutate, stderr, f = _esegui(sources)

if not out:
    print("\n[2] Esecuzione")
    print("  NESSUN OUTPUT — il probe non e' arrivato in fondo")
    for line in (stderr or "").splitlines()[:10]:
        print("   ", line)
    print(f"\nPASS {len(PASS)}  FAIL {len(FAIL) + 1}")
    sys.exit(1)

# Il crash e' un esito, non un dettaglio: senza questa riga il test
# diceva "13 falliti" senza dire COSA era rotto, e quei 13 falliti
# erano tutti la conseguenza di un unico errore a monte. Un bundle
# che muore prima del probe non ha nessuna funzione da valutare.
if out.get("crash"):
    print("\n[2] Esecuzione")
    print("  IL BUNDLE E' CRASHATO:")
    for line in str(out.get("crash")).splitlines()[:12]:
        print("   ", line)
    print(f"\nPASS {len(PASS)}  FAIL {len(FAIL) + 1}")
    print("FALLITI: ['il bundle e' crashato'] +", FAIL)
    sys.exit(1)

# ------------------------------------------------------------ la trappola
# Un test che non puo' fallire non vale niente. Questo qui potrebbe
# passare sempre, anche se la trappola non scattasse piu': basterebbe
# che nessuno guardi. Per evitare che diventi un costume falso, il
# test esegue il bundle UNA SECONDA VOLTA su una copia con il
# difetto introdotto apposta (una `const` letta prima della sua
# dichiarazione), e pretende che quella copia venga segnalata.
#
# Se la copia col difetto non viene segnalata, la trappola e' rotta
# e il test lo dice: meglio un rosso che un verde che non guarda.
print("\n[2b] La trappola: se ne accorge davvero?")
_mutato = dict(sources)
_prima = _mutato["panels.js"]
# La chiamata PRIMA della dichiarazione di `progElenco`: e' il difetto
# che c'era, ridotto al minimo.
_mutato["panels.js"] = _prima.replace(
    'const progElenco = $("side-progetti");',
    # Una funzione ASINCRONA che legge la `const` prima della sua
    # dichiarazione: e' il difetto reale. Non un errore sincrono a
    # livello di file, che crasherebbe il bundle e produrrebbe un
    # altro sintomo — la temporal dead zone dentro una promise si
    # manifesta come rifiuto, e il rifiuto e' il sintomo che la
    # trappola deve vedere.
    # Il `catch` NON deve essere messo: se lo si mette, la rejection
    # viene gestita e `unhandledRejection` non la vede — la
    # trappola diventerebbe cieca proprio nel caso che deve
    # controllare. Qui si lascia propagare, che e' il comportamento
    # del difetto vero.
    'async function _tdz() { return progElenco; }\n'
    'if (sidebar) { _tdz(); }\n'
    'const progElenco = $("side-progetti");')
if _mutato["panels.js"] == _prima:
    print("  SKIP — il marcatore del difetto non e' piu' nel sorgente")
else:
    _o2, _rej2, _err2, _f2 = _esegui(_mutato)
    _beccata = bool(_rej2) or bool(_o2.get("crash")) \
        or any("progElenco" in str(m) for m in _rej2)
    check("la trappola vede il difetto introdotto", _beccata,
          "il bundle col difetto non ha prodotto nessuna rejection: "
          "la trappola non serve a niente")
    if _beccata and _rej2:
        print(f"   [trappola] {_rej2[0][:110]}")

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

print("\n[3b] I progetti: le funzioni ci sono e nessuna promise si rifiuta")
pf = out.get("progFn", {})
check("caricaProgetto definita", pf.get("caricaProgetto") == "function", str(pf))
check("caricaProgetti definita", pf.get("caricaProgetti") == "function", str(pf))
check("impostaProgetto definita", pf.get("impostaProgetto") == "function", str(pf))
check("l'elenco dei progetti esiste", out.get("progElenco") != "undefined",
      "progElenco non esiste: il campo non e' nel DOM")
# Il cambio di progetto deve essere DETTO. Senza questo ramo, la
# cartella in cui si scrive cambia in silenzio: l'utente crede di
# stare da una parte e i file finiscono dall'altra.
_nota = out.get("progNota", "")
check("il cambio di progetto viene annunciato",
      "Sito Ristorante" in _nota, f"la nota dice: {_nota!r}")
check("l'annuncio dice DOVE si scrive",
      "D:/lavori/sito" in _nota, f"la nota dice: {_nota!r}")
# I simboli che il bundle deve esporre: se uno manca, il probe lo
# dice per nome invece di tacere.
_assenti = [k for k, v in list(pf.items()) + list(out.get("goalFn", {}).items())
            if isinstance(v, str) and v.startswith("ASSENTE")]
check("nessun simbolo assente nel bundle", not _assenti, str(_assenti))
if out.get("gateErrore"):
    print(f"   [gate] {out.get('gateErrore')}")
# La promessa rifiutata e' l'unico sintomo di un `const` letto troppo
# presto: la lista resta vuota e la console si riempie. Qui si vede.
rifiutate = out.get("rifiutate", [])
check("nessuna promessa rifiutata", not rifiutate, "; ".join(rifiutate[:3]))

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
if stderr.strip():
    print("   [stderr]", stderr.strip().splitlines()[0][:200])

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
