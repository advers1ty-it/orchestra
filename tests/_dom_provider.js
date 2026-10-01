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
    appendChild(c) {
      this.children.push(c);
      if (c.tagName === "OPTION") { this.options.push(c); c.parent = this; }
      return c;
    },
    replaceChildren(...cs) { this.children = []; this.options = []; for (const c of cs) this.appendChild(c); },
    addEventListener(ev, fn) { (this._handlers[ev] = this._handlers[ev] || []).push(fn); },
    getAttribute(nome) {
      if (nome === "hidden") return this._hidden === false ? null : "";
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
      if (sel === ".opz-sez") {
        for (const n of ["modelo", "skill", "servizi", "permessi", "gratis"]) {
          push(R["opz-sez-" + n]);
        }
      } else if (sel === ".opzioni-tab") {
        for (const n of ["modelo", "skill", "servizi", "permessi", "gratis"]) {
          push(R["opz-tab-" + n]);
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
    classList: {
      _s: new Set(),
      add(...c) { this._s.add(c[0]); },
      remove(...c) { this._s.delete(c[0]); },
      contains(c) { return this._s.has(c); },
    },
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
for (const id of ["provider-pick", "opt-provider", "opt-model", "model-pick",
                  "scope-pick", "provider-note", "opt-provider-msg", "dot",
                  "stats", "conn", "log", "main", "input", "btn-send",
                  "btn-cancel", "btn-reset", "ver", "scope-note",
                  // caricaOpzioni li tocca subito: senza, il cambio
                  // servizio finisce in "cambio fallito" e il test
                  // misura un problema del finto DOM, non del codice
                  "chiavi-lista", "gratis-lista", "opzioni-nota",
                  "permessi-stato", "permessi-msg", "routing-cat",
                  "routing-out", "routing-go",
                  // sezioni e tab del pannello Opzioni: senza queste,
                  // collegaSezioni() registra zero handler e il test
                  // misurerebbe un pannello vuoto, non uno funzionante
                  "opz-sez-modelo", "opz-sez-skill", "opz-sez-servizi",
                  "opz-sez-permessi", "opz-sez-gratis",
                  "opz-tab-modelo", "opz-tab-skill", "opz-tab-servizi",
                  "opz-tab-permessi", "opz-tab-gratis",
                  "opzioni-nav",
                  "skill-riepilogo", "skill-cartella",
                  "skill-categorie", "skill-generate",
                  "skill-scaricate", "skill-filtro",
                  "skill-vista", "skill-generate-nota"]) {
  const e = mk(id === "log" || id === "main" ? "div" : "select");
  // il nome della sezione, come nell'HTML: data-sez="skill" e cosi'
  const m = /^opz-(?:sez|tab)-([a-z]+)$/.exec(id);
  if (m) e.dataset.sez = m[1];
  document._els[id] = e;
}

// Le sezioni nascoste lo sono davvero: senza, tutte e cinque risultano
// visibili e il test del cambio sezione passerebbe perche' non c'e'
// mai stato niente da nascondere.
for (const n of ["skill", "servizi", "permessi", "gratis"]) {
  document._els["opz-sez-" + n].setAttribute("hidden", "");
}
document._els["opz-tab-modelo"].classList.add("attiva");

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
