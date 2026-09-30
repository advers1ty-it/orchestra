/* Esecuzione reale del bundle con un DOM finto: i due selettori del
   servizio vengono popolati davvero e il cambio viene eseguito davvero,
   non letto nel sorgente. Serve a coprire la sincronizzazione, che e'
   la parte fragile: due menu che devono dire la stessa cosa. */
globalThis.window = globalThis;
globalThis.document = {
  _els: {},
  getElementById(id) { return this._els[id] || null; },
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
    appendChild(c) {
      this.children.push(c);
      if (c.tagName === "OPTION") { this.options.push(c); c.parent = this; }
      return c;
    },
    replaceChildren(...cs) { this.children = []; this.options = []; for (const c of cs) this.appendChild(c); },
    addEventListener(ev, fn) { (this._handlers[ev] = this._handlers[ev] || []).push(fn); },
    getAttribute() { return null; },
    setAttribute() {},
    removeAttribute() {},
    querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, contains() { return false; } },
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
                  "btn-cancel", "btn-reset", "ver", "scope-note"]) {
  document._els[id] = mk(id === "log" || id === "main" ? "div" : "select");
}

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
    return ok({ provider: servizioCorrente, chiavi: CHIAVI, motori: [] });
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
