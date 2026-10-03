/* Esecuzione reale del bundle con un DOM finto: i due selettori del
   servizio vengono popolati davvero e il cambio viene eseguito davvero,
   non letto nel sorgente. Serve a coprire la sincronizzazione, che e'
   la parte fragile: due menu che devono dire la stessa cosa. */
globalThis.window = globalThis;
globalThis.document = {
  _els: {},
  getElementById(id) { return this._els[id] || null; },
  // Il bundle interroga il document per classe, non solo per id.
  // Senza, collegaSezioni() moriva alla prima riga e il pannello
  // Opzioni restava senza sezioni: cinque tab che non cambiano
  // niente, e un errore in console che parlava di una funzione.
  querySelectorAll(sel) {
    const out = [];
    const push = (e) => { if (e && !out.includes(e)) out.push(e); };
    // Entrambi i registri: questo modulo tiene _els, ma alcuni test
    // costruiscono il proprio (REG) e sostituiscono il document. Se si
    // guarda solo uno dei due, in quel test la sezione non esiste e
    // il bundle muore su "document.querySelectorAll is not a
    // function" — che vuol dire "manca un metodo", non "manca un
    // elemento", e manda a cercare nel posto sbagliato.
    const R = Object.assign({}, globalThis.REG || {}, this._els || {});
    if (sel === ".opz-sez" || sel === "section.opz-sez") {
      for (const n of ["modelo", "skill", "servizi", "permessi", "gratis"]) {
        push(R["opz-sez-" + n]);
      }
    } else if (sel === ".opzioni-tab" || sel === "button.opzioni-tab") {
      for (const n of ["modelo", "skill", "servizi", "permessi", "gratis"]) {
        push(R["opz-tab-" + n]);
      }
    } else if (sel === ".opzioni-nav" || sel === "nav.opzioni-nav") {
      push(R["opzioni-nav"]);
    }
    return out;
  },
  querySelector(sel) {
    const t = this.querySelectorAll(sel);
    return t.length ? t[0] : null;
  },
  createElement(tag) { return mk(tag); },
  createTextNode(t) { return { text: t }; },
  addEventListener() {},
};
globalThis.__diagErrors = [];
globalThis.EventSource = function () {
  this.close = () => {};
  this.onopen = null; this.onerror = null; this.onmessage = null;
};
globalThis.addEventListener = () => {};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};

function mk(tag) {
  const e = {
    tagName: String(tag).toUpperCase(), children: [], options: [],
    _handlers: {}, value: "", textContent: "", disabled: false, className: "",
    // dataset per tab e sezioni: il pannello ci legge "sez". Senza,
    // il click su una tab non sapeva quale sezione aprire e il test
    // sarebbe passato sul nulla.
    dataset: {},
    // classList e' quello che il bundle usa per segnare la tab attiva:
    // `t.classList.add("attiva")` su un oggetto senza classList
    // solleva, e il probe moriva prima del primo check.
    // classList e' quello che il bundle usa per segnare la tab attiva.
        // Quello qui sotto e' l'unico: ne esisteva un secondo, aggiunto
        // perche' sembrava mancasse, e in un oggetto JavaScript due
        // chiavi uguali si sovrascrivono — la seconda vince, e la prima
        // e' codice morto. Il sintomo era `attiva()` che restituiva
        // sempre None, e sei check di fila che fallivano per quello.
        classList: {
          _s: new Set(),
          add(...c) { for (const x of c) this._s.add(x); },
          remove(...c) { for (const x of c) this._s.delete(x); },
          contains(c) { return this._s.has(c); },
          toggle(c, forza) {
            const deve = forza === undefined ? !this._s.has(c) : forza;
            if (deve) this._s.add(c); else this._s.delete(c);
            return deve;
          },
        },
    appendChild(c) {
      this.children.push(c);
      if (c.tagName === "OPTION") { this.options.push(c); c.parent = this; }
      return c;
    },
    replaceChildren(...cs) { this.children = []; this.options = []; for (const c of cs) this.appendChild(c); },
    addEventListener(ev, fn) { (this._handlers[ev] = this._handlers[ev] || []).push(fn); },
    getAttribute(nome) {
          // L'attributo `hidden` e' l'unico che va tenuto traccia a
          // parte, perche' il bundle lo alterna con removeAttribute e la
          // verita' e' nel suo essere presente o no.
          //
          // Prima la logica era `this._hidden === false ? null : ""`, che
          // vuol dire "nascosta" anche quando l'attributo NON e' mai stato
          // impostato: `_hidden` undefined non e' false. Il risultato era
          // che la sezione che doveva essere aperta risultava nascosta e
          // quella che doveva essere nascosta risultava aperta — esattamente
          // l'opposto, e su tutti e dieci i check. Una cosa che funziona in
          // un verso solo e' un ottimo indicatore che sia al contrario.
          if (nome === "hidden") return this._hidden ? "" : null;
          return this._attrs ? (this._attrs[nome] || null) : null;
        },
    setAttribute(nome, v) {
      this._attrs = this._attrs || {};
      this._attrs[nome] = v;
      if (nome === "hidden") this._hidden = v !== "";
    },
    removeAttribute(nome) {
      if (this._attrs) delete this._attrs[nome];
      if (nome === "hidden") this._hidden = false;
    },
    // Registrato a mano: gli elementi vivono in una mappa per id, e per
    // trovarli per classe serve un elenco. Il bundle lo chiede solo per
    // '.opz-sez' e '.opzioni-tab', quindi si registrano esplicitamente e
    // non si finge un parser HTML che qui non c'e'.
    querySelectorAll(sel) {
      const out = [];
      const push = (e) => { if (e) out.push(e); };
      const R = globalThis.REG || document._els || {};
      // I nomi vengono da SEZIONI_E_TAB, che li ha letti dall'HTML
      // vero: elencarli qui era il terzo posto con lo stesso refuso.
      if (sel === ".opz-sez") {
        for (const id of SEZIONI_E_TAB) {
          if (id.indexOf("opz-sez-") === 0) push(R[id]);
        }
      } else if (sel === ".opzioni-tab") {
        for (const id of SEZIONI_E_TAB) {
          if (id.indexOf("opz-tab-") === 0) push(R[id]);
        }
      } else if (sel === ".opzioni-tab.attiva"
                 || sel === ".opzioni-tab:not(.attiva)") {
        // Il probe cerca la tab attiva per classe composta, e qui non
        // c'e' un parser di selettori. Sono due selettori e la
        // domanda e' sempre la stessa: quale delle tab ha quella
        // classe.
        const vuoleAttiva = sel === ".opzioni-tab.attiva";
        for (const id of SEZIONI_E_TAB) {
          if (id.indexOf("opz-tab-") !== 0) continue;
          const e = R[id];
          if (e && e.classList.contains("attiva") === vuoleAttiva) push(e);
        }
      } else if (sel === ".opzioni-nav") {
        // Il contenitore della barra. Serve perche' il bundle ci
        // aggancia il gestore delle frecce: senza questo elemento la
        // ricerca risponde vuota e il codice si ferma a meta', con un
        // errore che parla di addEventListener e non della barra.
        push(R["opzioni-nav"]);
      }
      return out;
    },
    querySelector(sel) {
      const t = this.querySelectorAll(sel);
      return t.length ? t[0] : null;
    },
    dataset: {},
    style: {},
    focus() {}, click() {},
    fire(ev) { for (const fn of (this._handlers[ev] || [])) fn({ target: this }); },
  };
  return e;
}
globalThis.Option = function (testo, val) {
  const o = mk("option"); o.text = testo; o.value = val; return o;
};

/* elementi che il bundle cerca */
// Gli id delle sezioni e delle tab si leggono da index.html, e non si
// scrivono a mano: due volte questo pannello si e' rotto per un nome
// scritto qui dentro (`opz-tab-modelo` invece di `opz-tab-modello`), e
// in entrambi i casi tredici check fallivano insieme senza dire perche'.
//
// Il percorso e' relativo a __dirname e poi risolto: il bundle finisce
// in un file temporaneo di sistema, quindi __dirname punta lì e un
// percorso relativo semplice non trova niente. E non va bene ne'
// process.cwd(), perche' il runner lancia i test da una cartella
// diversa dalla root. Si prova il primo, e se non c'e' il secondo: il
// file c'e' in uno dei due, e se non c'e' in nessuno il throw dice
// quale — invece di lasciare il DOM vuoto e ogni check passare per
//che' non c'era niente da misurare.
const _fs = require("fs");
const _path = require("path");
const _percorsi = [
  _path.join(__dirname, "..", "orchestra", "web", "index.html"),
  _path.join(process.cwd(), "orchestra", "web", "index.html"),
];
const _trovato = _percorsi.find((p) => _fs.existsSync(p));
if (!_trovato) {
  throw new Error("index.html non trovato in nessuno di: "
    + _percorsi.join(", "));
}
const _html = _fs.readFileSync(_trovato, "utf-8");
const SEZIONI_E_TAB = (_html.match(/id="(opz-(?:sez|tab)-[a-z]+)"/g) || [])
  .map((m) => m.slice(4, -1));
if (!SEZIONI_E_TAB.length) {
  throw new Error("nessuna sezione trovata in index.html: il DOM finto "
    + "sarebbe vuoto e ogni check passerebbe perche' non c'e' niente "
    + "da misurare");
}

// Gli id vengono letti dall'HTML, non elencati qui.
//
// Qui erano una terza copia della stessa lista, e questa era quella
// rotta: `skill-ricarica` e `skill-importa` ci sono nell'HTML ma non
// erano registrati, quindi il bundle chiamava on($("skill-ricarica")),
// il finto DOM rispondeva null, e il codice vero — che funziona —
// risultava non funzionante.
//
// Dopo i due refusi precedenti (opz-tab-modelo, sez-modello) la regola
// e' che in questo file i nomi non si scrivono: si leggono. Ogni id
// presente nell'HTML viene registrato, e se un domani ne aggiunge uno
// non c'e' niente da ricordare.
const _ID_NELL_HTML = Array.from(
  new Set((_html.match(/id="([a-zA-Z0-9_-]+)"/g) || [])
    .map((m) => m.slice(4, -1))));

// questi non sono nell'HTML ma il bundle li cerca: senza, il cambio
// servizio finisce in "cambio fallito" e il test misurerebbe un
// problema del finto DOM invece del codice.
const _ID_INVENTATI = ["log", "main", "input", "ver", "conn",
                       "opzioni-nav", "routing-out"];

for (const id of _ID_NELL_HTML.concat(_ID_INVENTATI)) {
  if (document._els[id]) continue;
  // Il contenitore e' un div, non una select: un <option> dentro un
  // <div> e' sbagliato, e il bundle mette li' dentro i testi lunghi.
  const _tag = (id === "log" || id === "main" || id === "opzioni-nav"
                || id === "routing-out" || id === "conn") ? "div" : "select";
  const e = mk(_tag);
  // L'id va sull'oggetto, non solo nella mappa: querySelectorAll
  // restituisce gli elementi e il codice ne legge `.id`. Senza,
  // ogni elemento tornava senza id e un check come "la tab attiva
  // segue" non poteva mai passare — non perche' il codice fosse
  // sbagliato, ma perche' il finto DOM non aveva quello che il
  // browser dà gratis.
  e.id = id;
  // il nome della sezione, come nell'HTML: data-sez="skill" e cosi'
  const m = /^opz-(?:sez|tab)-([a-z]+)$/.exec(id);
  if (m) e.dataset.sez = m[1];
  // Le classi vengono dall'HTML, non si indovinano. Senza, il bundle
  // cerca `.opzioni-tab` e non trova niente: il click sulle tab non
  // aggancia nessun handler, e il test diceva che il pannello non
  // funziona mentre funzionava. Erano sei le classi da mettere a
  // mano, e una sola sbagliata bastava a far fallire tutto.
  const _tag2 = new RegExp('<[^>]*id="' + id + '"[^>]*>').exec(_html);
  if (_tag2) {
    const _cls = /class="([^"]*)"/.exec(_tag2[0]);
    if (_cls) {
      e.className = _cls[1];
      for (const _c of _cls[1].split(/\s+/)) {
        if (_c) e.classList.add(_c);
      }
    }
    // hidden e' gia' sull'elemento nell'HTML: senza, tutte le sezioni
    // risultano visibili e "una sola aperta" non ha senso.
    if (/ hidden[=>]/.test(_tag2[0])) e.setAttribute("hidden", "");
  }
  document._els[id] = e;
}

// Le sezioni nascoste lo sono davvero: senza, tutte e cinque risultano
// visibili e il test del cambio sezione passerebbe perche' non c'e'
// mai stato niente da nascondere.
for (const n of SEZIONI_E_TAB) {
  const id = n.replace("tab-", "sez-");
  if (id !== "opz-sez-modello") document._els[id].setAttribute("hidden", "");
}
document._els["opz-tab-modello"].classList.add("attiva");

const CHIAVI = [
  { chiave: "OPENROUTER_API_KEY", presente: true },
  { chiave: "GROQ_API_KEY", presente: true },
  { chiave: "NVIDIA_API_KEY", presente: true },
];
let servizioCorrente = "openrouter";
let modelliChiamati = 0;

globalThis.fetch = async function (u) {
  const ok = (o) => ({ ok: true, status: 200, json: async () => o });
  if (u === "/api/chiavi")
    return ok({ provider: servizioCorrente, chiavi: CHIAVI, motori: [],
                nota_gratis: "", servizi_gratis: [] });
  if (String(u).startsWith("/api/provider")) {
    servizioCorrente = JSON.parse(globalThis.__corpoChiamata).provider;
    return ok({ ok: true, provider: servizioCorrente });
  }
  if (u === "/api/models") {
    modelliChiamati++;
    return ok({ provider: servizioCorrente, current: servizioCorrente + "/m1", models: [
      { id: servizioCorrente + "/m1", short: "m1", free: true, context: 8000, prompt_price: 0, scores: {} },
      { id: servizioCorrente + "/m2", short: "m2", free: false, context: 32000, prompt_price: 0.002, scores: {} },
    ] });
  }
  if (String(u).startsWith("/api/modelli")) {
    return ok({ modelli: [
      { id: servizioCorrente + "/x1", short: "x1", free: true, context: 8000, prompt_price: 0, scores: {} },
    ] });
  }
  if (u === "/api/state")
    return ok({ ready: true, version: "0.4.0", messages: [], busy: false });
  return ok({ running: false, log: [], result: null });
};
/* catturiamo il corpo della POST provider */
const _f = globalThis.fetch;
globalThis.fetch = async function (u, o) {
  if (String(u).startsWith("/api/provider") && o && o.body) {
    globalThis.__corpoChiamata = o.body;
  }
  return _f(u, o);
};
