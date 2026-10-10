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

(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("core")<0)window.__diagFiles.push("core");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"core");}})();

"use strict";

const $ = (id) => document.getElementById(id);

// Aggancio un handler senza mai esplodere. Un elemento assente e' un
// errore da segnalare, non un motivo per uccidere tutto lo script che
// segue: e' successo tre volte, e ogni volta la pagina restava a meta'
// senza dire perche'.
const on = (el, evento, fn) => {
  // Se arriva una stringa, e' un id: si risolve. Il motivo e' che
  // passare l'id a on() e' l'errore piu' facile da fare — sembra
  // funzionare perche' una stringa e' truthy e passa la guardia
  // qui sotto, e si scopre solo quando la pagina muore con
  // "addEventListener is not a function". Accettare l'id e
  // risolverlo e' il comportamento che ti aspetteresti, e toglie
  // una classe intera di difetti.
  const bersaglio = typeof el === "string" ? $(el) : el;
  if (!bersaglio) {
    console.warn("elemento assente, handler '" + evento + "' non agganciato");
    return false;
  }
  if (typeof bersaglio.addEventListener !== "function") {
    // Non e' un elemento. Meglio dirlo con precisione che lasciare
    // la pagina morire due righe dopo: un TypeError su
    // addEventListener non dice quale handler e quale elemento.
    console.warn("non e' un elemento, handler '" + evento + "' non agganciato:",
                 bersaglio);
    return false;
  }
  bersaglio.addEventListener(evento, fn);
  return true;
};
const log = $("log"), main = $("main"), input = $("input");
const btnSend = $("btn-send"), btnCancel = $("btn-cancel"), btnReset = $("btn-reset");
const dot = $("dot"), stats = $("stats"), conn = $("conn");
const modelPick = $("model-pick");
const reasoningPick = $("reasoning-pick");
// id -> modello. Il popup del selettore serve il punteggio di una
// riga, e cercarlo rileggendo le option sarebbe una ricerca fra 400
// elementi per ognuna.
let modelliPerId = {};
// Il servizio dichiara il tool-calling? Li' calcolato in
// loadModels, letto anche dal popup del selettore.
let servizioDichiaraTool = true;
let servizioTace = false;

// Lo scope attivo e' la categoria di lavoro scelta nell'header. Vive qui
// perche' loadModels() la usa per scrivere il punteggio dentro ogni
// opzione: la stessa variabile governa anche la raccomandazione, e due
// copie di "quale scope e'" possono divergere senza che nessuno se ne
// accorga.
let scopeAttivo = "";

// Il punteggio che va mostrato nell'opzione. Su scope vuoto non mostriamo
// un numero: sarebbe una media di cose diverse. Con uno scope scelto, il
// numero vero, e "—" quando quel modello non e' stato misurato li'.
function punteggioPerScope(m, scope) {
  const s = m.scores || {};
  // Con uno scope scelto: il numero vero di QUELLA categoria, e "—"
  // quando quel modello non e' stato misurato li'.
  if (scope) {
    const v = s[scope];
    return (typeof v === "number") ? v.toFixed(2) : "—";
  }
  // Senza scope: il numero unico, che confronta tutto il benchmark.
  //
  // Prima qui si restituiva stringa vuota e il menu non mostrava
  // nessun punteggio finche' non avevi scelto una categoria nel
  // pannello Benchmark. Il numero c'era ed era giusto, ma solo a una
  // condizione che nessuno sapeva, e il menu sembrava semplicemente
  // muto.
  //
  // Il campo si chiama `punteggio_unico`, non `totale`: la rotta
  // /api/models lo espone gia' da prima. Avevo cercato un nome che
  // non esisteva invece di guardare cosa arrivava, e poi avevo
  // duplicato il dato sotto un altro nome per far quadrare il mio
  // errore. Due copie dello stesso numero divergono, e quella che
  // resta indietro e' quella che qualcuno crede sia quella giusta.
  const t = m.punteggio_unico;
  return (t && typeof t.punteggio === "number")
    ? String(Math.round(t.punteggio)) : "";
}

let busy = false;
let ready = false;

// Non esiste un "blocco turno": ogni elemento appende direttamente a
// `log`, in ordine di arrivo. Il blocco esisteva e veniva creato da
// `turn_start`, che arriva PRIMA di `user_message`: finiva un contenitore
// vuoto SOPRA il messaggio dell'utente, con la risposta dentro — e la
// chat sembrava aver l'agente che rispondeva "sopra". In una chat
// l'ordine di arrivo e' tutto, quindi basta appendere e basta.
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function seiInFondo() {
  // Il predicato da solo, perché a `tool_end` serve sapere DOVE era
  // l'utente quando il tool è partito, non dove sta adesso che il
  // risultato ha allungato il log di trecento righe.
  return main.scrollHeight - main.scrollTop - main.clientHeight < 140;
}

// L'utente stava seguendo quando questo turno è partito. Registrato a
// `turn_start` e consumato dal messaggio finale: un tool da 200 righe
// fa scendere "in fondo" per qualche secondo, e il messaggio che arriva
// dopo non troverebbe più nessuno in fondo. Il flag ricorda l'intento.
let seguiTurno = false;

function scrollDown() {
  // solo se l'utente è già in fondo: scrollare mentre legge sopra è irritante
  if (seiInFondo()) main.scrollTop = main.scrollHeight;
}

function setBusy(v) {
  busy = v;
  dot.className = "dot" + (v ? " busy" : " ok");
  input.disabled = !ready || v;
  btnSend.disabled = !ready || v;
  // La graffetta segue la chat: durante un turno la richiesta e' gia'
  // partita, e allegare un file adesso significherebbe che viaggia
  // con il messaggio DOPO, senza che nessuno lo dica.
  if (typeof btnAllega !== "undefined" && btnAllega) {
    btnAllega.disabled = !ready || v;
  }
  btnCancel.disabled = !v;
  $("btn-reset").disabled = v;
  // Il bottone del modello segue il select: senza, durante un turno
  // resterebbe cliccabile mentre il select e' disabilitato, e si
  // potrebbe aprire un pannello su un catalogo che il server sta
  // ricaricando.
  const mpB = document.getElementById("model-btn");
  if (mpB) mpB.disabled = v || modelPick.disabled;
  if (typeof mpSincronizzaEtichetta === "function") {
    mpSincronizzaEtichetta();
  }
}

function renderStats(s) {
  // Costruito col DOM, non con innerHTML: i valori vengono dal nostro
  // server ma restare strutturalmente immuni evita di doverlo ricordare
  // ogni volta che qui compare un numero.
  const parts = [];
  if (s.iterations) parts.push([s.iterations, "iter"]);
  if (s.tool_calls) parts.push([s.tool_calls, "tool"]);
  if (s.tool_errors) parts.push([s.tool_errors, "err", true]);
  if (s.total_tokens) parts.push([s.total_tokens.toLocaleString(), "tok"]);
  if (s.compactions) parts.push([s.compactions, "comp"]);

  stats.textContent = "";
  if (!parts.length) { stats.textContent = "—"; return; }
  // `sep`, non `dot`: `dot` e' il nome della variabile globale che setBusy
  // usa per lo stato di occupazione. Ombreggiarla qui funzionerebbe per
  // caso, ma renderebbe ogni lettura futura di setBusy un bug.
  const sep = document.createTextNode(" · ");
  parts.forEach(([v, label, isErr], i) => {
    if (i) stats.appendChild(sep.cloneNode());
    const b = el("b", null, String(v));
    if (isErr) b.style.color = "var(--err)";
    stats.appendChild(b);
    stats.appendChild(document.createTextNode(" " + label));
  });
}

// Non esiste un "blocco turno": tutto appende direttamente a `log`, in
// ordine di arrivo. Il blocco esisteva e veniva creato da `turn_start`,
// che arriva PRIMA di `user_message`: finiva cosi' un contenitore vuoto
// sopra il messaggio dell'utente, con la risposta dentro. Sembrava che
// l'agente rispondesse "sopra". In una chat l'ordine e' tutto.
// Se il ragionamento è aperto, resta in fondo: ogni cosa che arriva
// dopo (tool, testo, attesa) lo spingerebbe su, e dopo tre tool non si
// vedrebbe più. Sposta il nodo CORRENTE, non il primo della pagina: con
// un nodo per ciclo, "il primo" sarebbe un blocco storico già letto.
function tieniRagionamentoInFondo() {
  if (typeof ragionamentoCorrente !== "undefined" && ragionamentoCorrente) {
    if (ragionamentoCorrente.parentNode === log) log.appendChild(ragionamentoCorrente);
  }
  scrollDown();
}

function addText(role, text, markdown) {
  const m = el("div", "msg " + role);
  m.appendChild(el("div", "role", role));
  const corpo = el("div", "body");
  if (markdown) {
    // Il modello parla markdown (`**grassetto**`, liste, codice): senza
    // rendering si vedono gli asterischi crudi, come segnalato in uso.
    // Solo i messaggi assistant: quelli user restano letterali (li hai
    // scritti tu e si mostrano come li hai scritti), e gli output dei
    // tool restano testo (potrebbero contenere `**` che non c'entrano).
    corpo.innerHTML = renderMarkdown(text);
  } else {
    corpo.textContent = text;
  }
  m.appendChild(corpo);
  log.appendChild(m);
  tieniRagionamentoInFondo();
  scrollDown();
  return m;
}

// Markdown minimo per i messaggi del modello. Regola d'ordine: prima
// si scappa l'HTML (l'output del modello non è fidato: un `<script>`
// dentro una risposta non deve eseguirsi), POI si applica il markdown.
// Il codice viene estratto prima di tutto, o gli asterischi dentro un
// blocco ``` verrebbero letti come grassetto.
function renderMarkdown(text) {
  let h = String(text == null ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const pezzi = [];
  const accantona = (html) => "\u0000" + (pezzi.push(html) - 1) + "\u0000";
  h = h.replace(/```(\w*)\n?([\s\S]*?)(?:```|$)/g,
    (_, lang, cod) => accantona("blocco:" + "<pre><code>" + cod.replace(/\n$/, "") + "</code></pre>"));
  h = h.replace(/`[^`\n]+`/g,
    (m) => accantona("inline:" + "<code>" + m.slice(1, -1) + "</code>"));
  // evita che http://... diventi corsivo sugli slash: i link prima.
  // L'URL esclude le virgolette: senza, un `"` dentro l'URL chiuderebbe
  // l'href e il resto diventerebbe attributo — classica via d'uscita.
  h = h.replace(/\[([^\]]+)\]\((https?:[^)"'\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[\s(>])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  const righe = h.split("\n");
  let fuori = [], lista = null;
  const chiudiLista = () => {
    if (lista) { fuori.push((lista === "ul" ? "<ul>" : "<ol>") + listaHtml + (lista === "ul" ? "</ul>" : "</ol>")); lista = null; listaHtml = ""; }
  };
  let listaHtml = "";
  for (const r of righe) {
    let m;
    if (/^\u0000\d+\u0000$/.test(r.trim()) && pezzi[+r.trim().slice(1, -1)].startsWith("blocco:")) {
      chiudiLista();
      fuori.push(pezzi[+r.trim().slice(1, -1)].slice(7));
    } else if ((m = r.match(/^(#{1,3})\s+(.*)/))) {
      chiudiLista();
      fuori.push(`<div class="md-h${m[1].length}">${m[2]}</div>`);
    } else if ((m = r.match(/^\s*---+\s*$/))) {
      chiudiLista();
      fuori.push("<hr>");
    } else if ((m = r.match(/^\s*[-*]\s+(.*)/))) {
      if (lista !== "ul") { chiudiLista(); lista = "ul"; }
      listaHtml += "<li>" + m[1] + "</li>";
    } else if ((m = r.match(/^\s*\d+[.)]\s+(.*)/))) {
      if (lista !== "ol") { chiudiLista(); lista = "ol"; }
      listaHtml += "<li>" + m[1] + "</li>";
    } else if (/^\s*$/.test(r)) {
      chiudiLista();
    } else {
      chiudiLista();
      fuori.push("<p>" + r + "</p>");
    }
  }
  chiudiLista();
  h = fuori.join("\n");
  // i pezzi inline restano dentro i <p>: si rimettono al loro posto
  h = h.replace(/\u0000(\d+)\u0000/g, (_, n) => {
    const p = pezzi[+n];
    return p.startsWith("blocco:") ? p.slice(7) : p.slice(7);
  });
  return h;
}

function addNote(text) {
  log.appendChild(el("div", "sysnote", text));
  tieniRagionamentoInFondo();
  scrollDown();
}

// L'attesa: una riga sola che pulsa e sparisce quando arriva qualcosa.
//
// Il motivo di una riga sola invece di una per iterazione: dopo cinque
// tool in un turno il pannello avrebbe cinque righe "sto pensando",
// e cioe' cinque righe che dicono la stessa cosa e coprono quello che
// e' successo davvero. E' lo stesso difetto del [tool?] su ottanta
// righe: un'etichetta ripetuta smette di essere un'informazione.
const FRASI_ATTESA = [
  "sto ragionando…",
  "sto ragionando, e' un modello lento",
  "ci sto mettendo, questo richiede piu' passaggi",
];
let attesaNodo = null;
let attesaGiro = 0;
let attesaTimer = 0;

// Se la riga del ragionamento è aperta. Senza questo segno, ogni pezzo
// riaprirebbe il blocco e il testo ricomincerebbe da capo.
let ragionamentoVisibile = false;

function mostraAttesa() {
  if (!attesaNodo) {
    attesaNodo = el("div", "attesa");
    log.appendChild(attesaNodo);
  }
  tieniRagionamentoInFondo();
  attesaGiro += 1;
  const i = Math.min(attesaGiro - 1, FRASI_ATTESA.length - 1);
  attesaNodo.textContent = FRASI_ATTESA[i];
  // Il ronzio: i puntini che si muovono dicono "vivo" senza dire
  // nulla. Dopo quattro secondi il messaggio si fa piu' esplicito,
  // perche' a quel punto non e' piu' un'attesa ma e' un'attesa lunga.
  if (!attesaTimer) {
    attesaTimer = setInterval(() => {
      if (attesaNodo && !attesaNodo.textContent.endsWith("…")) {
        attesaNodo.textContent = "sto ragionando…  (" + attesaGiro + ")";
      }
    }, 4000);
  }
  scrollDown();
}

function togliAttesa() {
  if (attesaTimer) { clearInterval(attesaTimer); attesaTimer = 0; }
  if (attesaNodo && attesaNodo.parentNode) {
    attesaNodo.parentNode.removeChild(attesaNodo);
  }
  attesaNodo = null;
  attesaGiro = 0;
}

// Tool: intestazione cliccabile + output richiudibile.
const openTools = new Set();

// ------------------------------------------------------------- Permessi
// L'agente si e' fermo e aspetta. Questa e' l'unica schermata in cui
// il tempo conta: senza risposta, dopo cinque minuti il server nega
// da solo. Chiudere la scheda NON e' "nega" — e' lasciare l'agente
// appeso. Per questo la chiusura risponde "mai" esplicitamente, e i
// pulsanti non si disattivano fino a quando la risposta non e' partita.
const permessoBox = $("permesso");
let permessoAttivo = null;

function mostraPermesso(d) {
  permessoAttivo = d.id;
  $("permesso-percorso").textContent = d.percorso || "";
  $("permesso-dettaglio").textContent =
    "azione: " + (d.azione || "") + (d.dettaglio ? " — " + d.dettaglio : "");
  permessoBox.classList.remove("hidden");
  $("permesso-una").focus();
}

function nascondiPermesso() {
  permessoBox.classList.add("hidden");
  permessoAttivo = null;
}

async function rispondiPermesso(scelta) {
  if (!permessoAttivo) return;
  const id = permessoAttivo;
  // blocc subito: due clic non devono mandare due risposte, e la
  // seconda arriverebbe su una domanda gia' chiusa
  permessoAttivo = null;
  for (const b of ["permesso-una", "permesso-ses", "permesso-mai"]) {
    $(b).disabled = true;
  }
  nascondiPermesso();
  try {
    await fetch("/api/permesso", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, scelta }),
    });
  } catch (e) {
    // il server non ha ricevuto. Dopo cinque minuti nega da solo, e
    // quello e' l'esito sicuro: non riprovare, non insistere.
    addText("error", "risposta non arrivata: " + e);
  } finally {
    for (const b of ["permesso-una", "permesso-ses", "permesso-mai"]) {
      $(b).disabled = false;
    }
  }
}

on($("permesso-una"), "click", () => rispondiPermesso("una_volta"));
on($("permesso-ses"), "click", () => rispondiPermesso("sessione"));
on($("permesso-mai"), "click", () => rispondiPermesso("mai"));

// chiudere il pannello Opzioni mentre c'e' una domanda: la domanda
// resta, non e' un avviso che si nasconde
on($("btn-bench"), "click", () => { /* il benchmark non copre il permesso */ });

function addTool(name, args, key) {
  const t = el("div", "tool");
  // data-key: serve a `tool_end` per trovare il tool giusto quando ce n'e'
  // piu' di uno identico nello stesso turno
  t.setAttribute("data-key", key);
  if (openTools.has(key)) t.classList.add("open");
  const head = el("div", "tool-head");
  head.appendChild(el("span", "caret", "▶"));
  head.appendChild(el("span", "tool-name", name));
  const a = el("span", "tool-args", args);
  head.appendChild(a);
  const st = el("span", "tool-status run", "…");
  head.appendChild(st);
  const out = el("div", "tool-out");
  head.onclick = () => {
    t.classList.toggle("open");
    if (t.classList.contains("open")) openTools.add(key); else openTools.delete(key);
  };
  t.appendChild(head);
  t.appendChild(out);
  log.appendChild(t);
  // Si registra DOVE sta l'utente adesso: a `tool_end` il risultato avrà
  // allungato il log e il controllo "sei in fondo" direbbe sempre no —
  // ed è per quello che dopo un tool lungo la risposta arrivava senza
  // che nessuno scrollasse, e toccava farlo a mano.
  const seguiva = seiInFondo();
  t._segui = seguiva;
  // Coerente col flag: se l'utente seguiva, il tool nuovo va in fondo;
  // se era risalito a leggere, NON si scrolla — chiamare `scrollDown`
  // qui ignorava proprio l'intento appena registrato e strattonava chi
  // stava leggendo sopra. Il ragionamento (se c'è) resta ancorato a
  // fondo solo quando si segue.
  if (seguiva) { main.scrollTop = main.scrollHeight; }
  return { root: t, status: st, out };
}

// ---------------------------------------------------------------- SSE
let es = null;

function connect() {
  if (es) es.close();
  es = new EventSource("/api/stream");

  es.onopen = () => { conn.textContent = "connesso"; conn.style.color = "var(--ok)"; };

  es.onerror = () => {
    conn.textContent = "riconnessione…";
    conn.style.color = "var(--warn)";
    // EventSource riconnette da solo; non lo chiudiamo
  };

  es.onmessage = (e) => {
    let item;
    try { item = JSON.parse(e.data); } catch { return; }
    handle(item.kind, item.data || {});
  };
}

function handle(kind, d) {
  switch (kind) {
    case "snapshot": {
      if (d.ready === false) {
        showBanner(d.error || "server non pronto");
        ready = false; setBusy(false); return;
      }
      ready = true;
      renderStats(d);
      loadModels();
      // ricostruisci la conversazione
      log.innerHTML = "";
      // I risultati dei tool, indicizzati per id: le chiamate (dentro i
      // messaggi assistant) arrivano prima dei risultati (messaggi
      // role="tool"), ma raccoglierli prima rende il rendering immune
      // all'ordine. Stessa regola del live: si abbina per id, non
      // "l'ultimo tool".
      const risultatiTool = {};
      (d.messages || []).forEach((m) => {
        if (m && m.role === "tool" && m.tool_call_id) {
          risultatiTool[m.tool_call_id] = m;
        }
      });
      (d.messages || []).forEach((m) => {
        // `m.content` puo' essere null o mancante: `.trim()` su undefined
        // solleva e blocca TUTTO il rendering della snapshot, lasciando la
        // chat vuota senza alcun errore in console. Difesa esplicita.
        const text = (m && m.content != null) ? String(m.content) : "";
        if (m.role === "user") addText("user", text);
        else if (m.role === "assistant") {
          // Solo testo, niente riga bianca: un assistant con sole tool
          // call non ha niente da dire, e il suo contenuto sono i tool
          // sotto. La riga bianca era il motivo per cui questi messaggi
          // venivano omessi dallo snapshot.
          if (text.trim()) addText("assistant", text, true);
          (m.tool_calls || []).forEach((tc) => {
            const creato = addTool(tc.name, tc.arguments, tc.id);
            const ris = risultatiTool[tc.id];
            if (ris) {
              const male = String(ris.content || "").startsWith("ERRORE");
              const st = creato.root.querySelector(".tool-status");
              st.className = "tool-status " + (male ? "err" : "ok");
              st.textContent = male ? "errore" : "ok";
              creato.root.querySelector(".tool-out").textContent = ris.content || "";
            }
          });
        }
      });
      setBusy(!!d.busy);
      scrollDown();
      break;
    }
    case "permission_request":
      // l'agente si e' fermo e aspetta. Va mostrato subito e per
      // primo: e' l'unico evento che blocca tutto il resto.
      mostraPermesso(d);
      break;
    case "turn_start":
      // segnalava l'inizio del turno. Non crea piu' nulla: il blocco
      // finiva sopra il messaggio dell'utente e la risposta finiva dentro.
      //
      // Qui si registra se l'utente stava seguendo quando il turno è
      // partito. Non è la stessa cosa di "sei in fondo adesso": con un
      // tool da 200 righe, il messaggio finale arriva secondi dopo e in
      // quel lasso di tempo l'utente non è più esattamente in fondo —
      // quindi `scrollDown` (che controlla "sei in fondo adesso") lo
      // salta, e la risposta resta sotto. Il flag sopravvive ai tool.
      seguiTurno = seiInFondo();
      break;
    case "user_message":
      addText("user", d.text);
      break;
    case "thinking": {
      // Il tempo piu' lungo e piu' vuoto dello schermo era quello
      // fra "invio" e "prima risposta": 40 secondi per un modello che
      // ragiona, e a schermo non succedeva niente. Sembrava che
      // Orchestra avesse smesso di funzionare.
      //
      // UNA riga sola, che si aggiorna e sparisce: se ogni iterazione
      // lasciasse un segnaposto, dopo cinque tool ci sarebbero cinque
      // righe "sto pensando" e il pannello diventerebbe illeggibile —
      // che e' il difetto che il [tool?] aveva.
      mostraAttesa();
      // Nuovo ciclo di thinking = il ragionamento di prima è finito. Si
      // chiude il nodo, così il prossimo pezzo di ragionamento ne apre
      // uno nuovo in fondo (sotto i tool, non sopra). Senza questo, un
      // modello che ragiona, chiama un tool e ragiona ancora riempirebbe
      // il blocco iniziale, che i tool hanno già spinto in cima.
      // Il flag va azzerato insieme, o il prossimo pezzo crederebbe che
      // un blocco sia già aperto e non ne aprirebbe uno nuovo.
      ragionamentoVisibile = false;
      ragionamentoChiudi();
      break;
    }
    case "ragionamento": {
      // Il ragionamento arriva a pezzi. La riga d'attesa sparisce al primo
      // pezzo: da lì in poi c'è qualcosa da leggere, e tenerle tutte e due
      // direbbe due volte la stessa cosa.
      togliAttesa();
      if (!ragionamentoVisibile) {
        ragionamentoVisibile = true;
        ragionamentoApri();
      }
      ragionamentoAggiungi(d.testo || "");
      break;
    }
    case "assistant": {
      ragionamentoVisibile = false;
      ragionamentoChiudi();
      togliAttesa();
      if (d.content) {
        addText("assistant", d.content, true);
        // La risposta vera va in fondo SE l'utente stava seguendo il
        // turno — non "se è in fondo adesso". Con un tool da 200 righe,
        // quando la risposta arriva secondi dopo, nessuno è più in fondo
        // e `scrollDown` la lascia sotto. Questo è il "devo scrollare
        // io" segnalato in uso. Se l'utente era risalito a leggere, il
        // flag è falso e nessuno lo strattona.
        if (seguiTurno) { seguiTurno = false; main.scrollTop = main.scrollHeight; }
      }
      (d.tool_calls || []).forEach((tc) => {
        // chiave basata sull'id del tool call: `tool_end` lo cerca cosi' e
        // abbinano anche due tool identici emessi nello stesso turno.
        addTool(tc.name, JSON.stringify(tc.args), tc.id || (tc.name + "|" + JSON.stringify(tc.args)));
      });
      break;
    }
    case "tool_end": {
      togliAttesa();
      // abbiniamo per id, non "l'ultimo tool". Con due tool nello stesso
      // turno il risultato finiva sempre sulla stessa riga e l'altro
      // restava appeso su "..." per sempre. I tool vivono in `log`, non in
      // un blocco: per questo si cercano li'.
      const node = d.id ? log.querySelector('[data-key="' + CSS.escape(d.id) + '"]') : null;
      if (node) {
        const st = node.querySelector(".tool-status");
        st.className = "tool-status " + (d.ok ? "ok" : "err");
        st.textContent = d.ok ? "ok" : "errore";
        node.querySelector(".tool-out").textContent = d.result || "";
        // Il risultato ha allungato il log anche di centinaia di righe.
        // Se l'utente stava seguendo (registrato a `tool_start`), lo si
        // riporta in fondo: senza, il controllo di `scrollDown` direbbe
        // "non sei in fondo" da qui in poi — risposta finale inclusa — e
        // toccherebbe scrollare a mano. Se aveva scrollato su da solo, il
        // flag è falso e nessuno lo disturba.
        if (node._segui) main.scrollTop = main.scrollHeight;
      }
      break;
    }
    case "tool_error":
      togliAttesa();
      addNote(`errore tool ${d.tool}: ${d.error}`);
      break;
    case "compaction":
      addNote(`contesto compattato: ${d.tokens_before} → ${d.tokens_after} token ` +
              `(potati ${d.tools_pruned} tool, fusi ${d.history_merged} turni)`);
      break;

    // Self-correzione: il loop "agisci → verifica oggettiva → correggi".
    // Va detto a schermo quando scatta: un controllo automatico che non
    // si vede è indistinguibile da uno che non esiste — e qui il modello
    // potrebbe "correggersi" e l'utente deve sapere che è stato rimandato
    // indietro, non che l'agente ha risposto due volte a caso.
    case "verifica": {
      if (d.ok) {
        addNote(`verifica superata (tentativo ${d.tentativo})`);
      } else {
        addNote(`verifica FALLITA (tentativo ${d.tentativo}): ${d.motivo} ` +
                `— rimando al modello con il motivo esatto`);
      }
      break;
    }
    case "verifica_esaurita":
      addNote(`self-correzione esaurita dopo ${d.tentativi} tentativi: ${d.motivo}. ` +
              `Restituisco il lavoro così com'è, col motivo.`);
      break;
    case "gira_a_vuoto":
      addNote(`fermato: ripeteva \`${d.tool}\` con gli stessi argomenti, sempre lo stesso errore. ` +
              `Chiudo col lavoro fatto invece di girare a vuoto.`);
      break;

    // Instradamento e delega: le due cose che Orchestra fa da sola.
    // Senza una riga qui, l'agente cambia modello e chiede a un
    // sub-agente senza che nulla lo dica, e un comportamento
    // automatico che non si vede e' indistinguibile da uno che non
    // esiste.
    case "routing": {
      const chi = d.modello ? `${d.categoria || "?"} → ${d.modello}` : "routing";
      const p = (d.punteggio !== null && d.punteggio !== undefined)
        ? ` (${Math.round(d.punteggio)}% su ${Math.round(d.prove || 0)} prove)` : "";
      addNote(`instradamento: ${chi}${p} — ${d.motivo || ""}`);
      break;
    }
    case "figlio": {
      // Il sub-agente lavora: mostro i suoi passi, annotati come "figlio".
      // Solo l'essenziale — tool chiamati e testo — non ogni evento, o il
      // log del padre si riempie dei passi del figlio e non si distingue
      // più chi sta facendo cosa.
      const t = d.tipo || "";
      if (t === "tool_start") {
        addNote(`figlio → ${d.name}`);
      } else if (t === "assistant" && d.content && d.content.trim()) {
        addNote(`figlio: ${d.content.trim().slice(0, 120)}`);
      }
      break;
    }
    case "delega": {
      const esito = {risposto: "fatto", esaurito: "senza risposta",
                     errore: "errore"}[d.esito] || d.esito;
      addNote(`delega a un sub-agente (${d.modello || "senza modello"}, ` +
              `${d.passi || 0} passi): ${esito} — "${String(d.obiettivo || "").slice(0, 70)}"`);
      break;
    }
    case "log":
      addNote(d.text || "");
      break;
    case "retry":
      addNote(`retry ${d.attempt}: ${d.error}`);
      break;
    case "turn_end":
      renderStats({ ...d, compactions: 0 });
      break;
    case "error":
      addText("error", d.message);
      break;
    case "cancel_requested":
      addNote("annullamento richiesto, il turno in corso finirà");
      break;
    case "reset":
      log.innerHTML = "";
      stats.textContent = "—";
      break;
    case "idle":
      setBusy(false);
      break;
  }
}

function showBanner(msg) {
  const b = el("div", "banner", msg);
  log.innerHTML = "";
  log.appendChild(b);
}

// ------------------------------------------------------- selettore modello
// Il modello si cambia SENZA riavviare il server. Il contesto della
// conversazione resta: è un cambio di "chi risponde", non di "di cosa si
// parla". Cambiarlo a metà turno è vietato dal server (409) perché
// lascerebbe una conversazione con due modelli diversi e nessun senso.

async function loadModels() {
  try {
    const r = await fetch("/api/models");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    // svuota con replaceChildren, non textContent: su un <select> alcuni
    // browser trattano textContent="" come "nessuna opzione valida" e
    // rifiutano di accettarne altre. replaceChildren è esplicito.
    modelPick.replaceChildren();
    // i gratuiti per primi: sono quelli che si possono provare senza
    // pensarci, e sono la maggior parte di quello che c'è
    // Il servizio dichiara il tool-calling? Vera se ALMENO UN modello
    // lo dichiara: su OpenRouter tutti, su NVIDIA nessuno, su Groq
    // nessuno. E li' la differenza la fa solo se qualcuno dichiara
    // qualcosa — altrimenti non c'e' niente da distinguere e il
    // "forse" sarebbe identico su tutte le righe.
    const _tutti = d.models || [];
    const _dichiarati = _tutti.filter(
      (m) => m.tool_calling !== null && m.tool_calling !== undefined).length;
    servizioDichiaraTool = _dichiarati > 0;
    // Se il servizio NON dichiara niente, il piede del menu lo dice
    // una volta sola. E' l'unica parte che un utente deve leggere
    // prima di scegliere un modello su quel servizio.
    servizioTace = _tutti.length > 0 && _dichiarati === 0;
    const sorted = _tutti.slice().sort((a, b) =>
      (a.free === b.free) ? a.id.localeCompare(b.id) : (a.free ? -1 : 1));
    // Indicizzati per id: il popup del selettore cerca il punteggio di
    // una riga, e rileggere il testo dell'option per ognuna significa
    // cercare fra 400 elementi 400 volte. Una mappa costa una riga e
    // toglie 160.000 confronti ogni volta che si apre il menu.
    modelliPerId = {};
    for (const m of sorted) modelliPerId[m.id] = m;

    for (const m of sorted) {
      // new Option(...) invece di createElement("option"): costruisce
      // un <option> vero, con value e testo impostati nel modo giusto.
      // Con createElement + appendChild il <select> restava vuoto in
      // alcuni browser, perche' mancava l'attributo implicito.
      //
      // Il punteggio va nell'opzione, non in una tabella a parte: e'
      // la domanda che stai facendo ("quanto e' bravo su QUELLO che devo
      // fare") e la risposta deve stare dove scegli.
      //
      // "tool?" per i modelli di cui il provider NON dichiara il
      // tool-calling. Non e' un difetto: e' una domanda aperta, e
      // segnalarla vale piu' di fingere certezze. Su un "sconosciuto"
      // non si fa affidamento — ma non si nasconde nemmeno, perche' un
      // modello che nasconde le sue carte peggio di uno che ammette di
      // non sapere.
      // Tool: tre stati, e uno solo si ripete.
      //
      // "tool?" dice "non lo so". Su NVIDIA lo dicevano 80 righe su 80, e
      // su Groq 8 su 11: un'etichetta identica ovunque non distingue niente,
      // e insegnava a leggerla senza leggerla. Il dubbio è onesto su una
      // riga e rumore su ottanta.
      //
      // Quindi: il "forse" resta SOLO dove qualche modello lo dichiara e
      // qualche altro no — li' distingue davvero. Se il servizio non
      // dichiara niente, non si mette niente, e si dice UNA volta cosa
      // significa, nel piede del menu.
      //
      // "[niente tool]" invece resta su ogni riga: è un no definitivo e un
      // modello senza tool-calling non è Orchestra.
      const tc = m.tool_calling;
      const tool = tc === true ? ""
        : (tc === false ? "  [niente tool]" : (servizioDichiaraTool ? "  [tool?]" : ""));
      const punteggio = punteggioPerScope(m, scopeAttivo);
      // Il costo per 10k token va nell'opzione insieme al prezzo per
      // milione. Sono due numeri che dicono cose diverse: $0.01/1M e
      // $30/1M su un turno da 10k token sono un centesimo e trenta
      // centesimi, ma nel menu sembrano lontanissimi. Il costo della
      // richiesta e' quello che decide, quindi e' quello che si vede.
      const o = new Option(
        m.short + tool + (punteggio ? "  " + punteggio : "") +
        ctx_label(m.context) + " · " + price_label(m) +
        costo_breve(m, 10000), m.id);
      modelPick.appendChild(o);
    }
    // il modello corrente: si mette in mezzo solo se esiste davvero
    // nella lista. Senza questo controllo, cambiando servizio la select
    // si posiziona su un id che quel servizio non ha: si vede il
    // modello vecchio mentre il backend sta chiamando un altro, e la
    // divergenza si vede solo alla prima risposta.
    if (d.current && sorted.some((m) => m.id === d.current)) {
      modelPick.value = d.current;
    } else {
      const primo = sorted.find((m) => m.free) || sorted[0];
      modelPick.value = primo ? primo.id : "";
      if (d.current && primo && primo.id !== d.current) {
        // il modello in uso non esiste piu' su questo servizio: lo
        // diciamo. Un cambio silenzioso lascia l'utente convinto di
        // stare usando quello che ha scelto.
        const nota = $("provider-note");
        if (nota) {
          nota.textContent = "modello non disponibile su questo servizio, uso " + primo.id;
          nota.className = "provider-note rosso";
        }
      }
    }
    modelPick.disabled = false;
    mpSincronizzaEtichetta();
    // le liste del pannello benchmark e della prova manuale usano lo
    // stesso catalogo. Popolarle qui evita un secondo fetch e fa si'
    // che i tre selettori non possano contraddirsi.
    if (typeof aggiornaCatalogoUI === "function") {
      // in un try separato: se il pannello benchmark non c'esso' — una
      // pagina vecchia, un elemento rimosso, un test con un DOM
      // ridotto — la lista modelli deve restare comunque piena. Un
      // pannello opzionale che uccide il caricamento principale e' la
      // stessa classe di difetto di un pannello sparito dal parser:
      // si perde tutto per un pezzo che manca.
      try {
        aggiornaCatalogoUI(sorted, d.current);
      } catch (e) {
        if (typeof registraErroreDiagnostico === "function")
          registraErroreDiagnostico("aggiornaCatalogoUI: " + e);
      }
    }
  } catch (e) {
    modelPick.replaceChildren();
    modelPick.appendChild(new Option("modelli non disponibili", ""));
    modelPick.disabled = true;
    mpSincronizzaEtichetta();
  }
}

function ctx_label(context) {
  return context ? " " + Math.round(context / 1000) + "k" : "";
}
// I prezzi OpenRouter sono per TOKEN, non per milione. 5e-07 non e'
// "gratis con qualche cifra": e' $0.50 per un milione di token. Il
// codice prima lo stampava cosi' com'era e con toFixed(4), e il
// risultato era che 377 modelli su 379 dicevano "0.0000" — il 99% del
// menu diceva la stessa cosa, quindi non diceva niente.
//
// Perche' succedeva: i prezzi reali vanno da 7e-08 a 3e-05, e quattro
// decimali su 5e-07 danno 0.0000. Non era un problema di arrotondamento:
// era un problema di unita' di misura, e stavamo mostrando arrotondati
// dei centesimi di centesimo.
//
// Si divide per un milione e si sceglie il formato sul valore COSI'.
// Sotto 0.01 servono 4 decimali per non perdere il senso; sopra, 2
// bastano e 4 fanno solo rumore.
function price_label(m) {
  const p = Number(m.prompt_price);
  if (m.free || !isFinite(p) || p === 0) return "free";
  // -1 e' il prezzo di OpenRouter per "variabile": non e' gratis, e non
  // e' nemmeno un numero. Mostrarlo come -1 fa sembrare un modello a
  // pagamento quando puo' costare quanto vuole.
  if (p < 0) return "prezzo variabile";
  const per_milione = p * 1_000_000;
  const cifre = per_milione < 0.01 ? 4 : (per_milione < 1 ? 3 : 2);
  return "$" + per_milione.toFixed(cifre) + "/1M";
}

// Quanto costa UNA richiesta, non quanto costa il milione. E' il numero
// che decide: 30 $/1M su un turno da 10k token sono 30 centesimi, e
// 0.01 $/1M sono un centesimo. Senza questo, confrontare due modelli
// significa fare conti a mente dentro la testa.
//
// Il formato segue il numero, non l'abitudine: sotto un centesimo si
// vedono i decimali (un centesimo arrotondato a zero e' un centesimo
// che sembra gratis), sopra si no.
function costo_stimato(m, token) {
  const p = Number(m.prompt_price);
  if (m.free || !isFinite(p) || p <= 0) return null;
  // p e' $/TOKEN. Il costo e' semplicemente prezzo per token per numero
  // di token: 0.8 $/1M = 8e-07 $/token, e su 10000 token fa 0.008 $.
  //
  // Prima c'era una divisione per 1000 in piu', e il risultato era
  // 0.000008 — mille volte troppo piccolo, e con la formattazione
  // diventava "0.0000" per ogni modello sotto i 3 $/1M. Il numero
  // sembrava plausibile, quindi il difetto non si vedeva: sembrava
  // solo un prezzo basso.
  return p * (token || 0);
}

function costo_breve(m, token) {
  const c = costo_stimato(m, token);
  if (c === null) return "";
  // Le cifre seguono il numero, e non basta fermarsi a 4.
  //
  // Un modello a 0.0038 $/1M, su 10k token, costa 0.000038 $: con
  // toFixed(4) diventava "0.0000", cioe' "gratis". Non e' un
  // arrotondamento, e' un costo reale stampato come zero — che e' la
  // cosa piu' dannosa che si possa fare con un prezzo, perche' il
  // confronto fra due modelli parte gia' sbagliato.
  //
  // Meglio mostrare un numero che sembra piccolo che mentire sul
  // piccolo: sotto 1e-04 si passa alla notazione esponenziale, che e'
  // scomoda da leggere ma non mente.
  let testo;
  if (c >= 0.01) testo = "$" + c.toFixed(2);
  else if (c >= 0.0001) testo = c.toFixed(5);
  else testo = c.toExponential(1);
  return "  ·  ~" + testo + "/" + Math.round(token / 1000) + "k";
}

on(modelPick, "change", async () => {
  const id = modelPick.value;
  mpSincronizzaEtichetta();
  if (!id || busy) return;
  modelPick.disabled = true;
  mpSincronizzaEtichetta();
  try {
    const r = await fetch("/api/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: id }),
    });
    const d = await r.json();
    if (!r.ok) { addText("error", d.error || `errore ${r.status}`); return; }
    // la conversazione continua, ma annotiamo il cambio: senza, domani non
    // si sa che metà della chat l'ha scritta un modello diverso
    addText("system", `modello → ${id}`);
    // Il limite di compattazione segue il modello (75% della sua
    // finestra): senza ricaricare, la nota nelle Opzioni mostra il
    // valore vecchio e sembra che il cambio non faccia niente.
    if (typeof caricaOpzioni === "function") caricaOpzioni();
  } catch (e) {
    addText("error", String(e));
  } finally {
    modelPick.disabled = false;
    mpSincronizzaEtichetta();
  }
});

;
(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels")<0)window.__diagFiles.push("panels");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels");}})();
// -------------------------------------------------------------- benchmark

// ------------------------------------------------- scelta dei modelli da provare
// Con 396 modelli un campo "quanti" non basta: la scelta la fa chi guarda.
// Caselle + filtro free + due scorciatoie, e il conteggio sempre visibile
// perche' l'errore piu' comune e' lanciare trecento modelli per distrarsi.
const benchModels = $("bench-models");
const benchFree = $("bench-free");
const benchCount = $("bench-count");
const benchCat = $("bench-cat");
let tuttiModelli = [];

function modelliScelti() {
  return Array.from(benchModels.querySelectorAll("input:checked")).map((c) => c.value);
}

function aggiornaConteggio() {
  const n = modelliScelti().length;
  benchCount.textContent = n === 1 ? "1 scelto" : n + " scelti";
}

// Il punteggio sta nella riga, per la categoria scelta. Non in una
// tabella a parte: la scelta e la valutazione devono stare sulla stessa
// riga, o il confronto fra due modelli costa due sguardi a due posti.
// Un modello non misurato mostra "—": non e' zero, e' sconosciuto, e la
// differenza conta quando si tratta di soldi.
// Il punteggio e' una percentuale, non una frazione.
//
// "0.50" non dice niente di useful: con due task i valori possibili
// sono 0, 0.33, 0.5, 0.66, 1 — e due modelli con 0.67 e 0.66 sono
// indistinguibili, mentre uno che ne ha passati 1 su 2 sembra
// comparabile con uno che ne ha passati 10 su 20. In percento la
// scala e' continua e l'occhio la legge.
//
// Accanto c'e' sempre la frazione — "50 · 1/2" — perche' la
// percentuale da sola nasconde la base: 50 su 2 test e 50 su 20
// test non sono la stessa cosa, e tu non puoi saperlo altrimenti.
function punteggioDi(m, cat) {
  const s = m.scores || {};
  const base = m.passi || {};        // quanti ne ha passati, per categoria
  const totale = m.task_per_cat || {};

  // su "tutte" non c'e' un punteggio unico, e non lo si inventa. Un
  // 1.00 in codice e uno 0.00 in ragionamento non sono "0.50": sono
  // due fatti che la media nasconde. Mostriamo quante categorie sono
  // state misurate, che e' quello che ti dice se quel modello e'
  // confrontabile o e' ancora sconosciuto.
  if (cat === "all" || !cat) {
    const n = Object.keys(s).length;
    if (!n) return null;
    const unico = m.punteggio_unico;
    if (unico && typeof unico.punteggio === "number") {
      const cls = unico.punteggio >= 90 ? "alto"
                 : unico.punteggio > 0 ? "medio" : "basso";
      const contro = Math.round(unico.grezzo || 0);
      const scarto = Math.round((unico.grezzo || 0) - unico.punteggio);
      return {
        testo: Math.round(unico.punteggio) + "% · " + n + "/" + CATEGORIE_TOTALE,
        cls: cls,
        titolo: "VALORE UNICO su tutte le categorie\n"
          + "ogni categoria pesa uguale; dentro la categoria il livello\n"
          + "conta di piu' (facile x1, medio x1.5, difficile x2)\n"
          + "prove: " + (unico.prove || 0) + " · categorie coperte: "
          + n + "/" + CATEGORIE_TOTALE
          + "\ngrezzo " + contro + "%"
          + (scarto > 0 ? ", tirato verso la media di " + scarto + " punti"
                        + "\nperche' ha poche prove: con poche prove il"
                        + " numero resta\nun'indicazione, non una sentenza"
                        : "")
      };
    }
    return { testo: n + "/" + CATEGORIE_TOTALE, cls: "quante",
             titolo: "categorie misurate su " + CATEGORIE_TOTALE
                     + " — nessun numero unico disponibile" };
  }
  const v = s[cat];
  if (typeof v !== "number") return null;
  const pct = Math.round(v * 100);
  const f = base[cat];
  const n = totale[cat];
  const frazione = (typeof f === "number" && n) ? (" · " + f + "/" + n) : "";
  const cls = pct >= 99 ? "alto" : pct > 0 ? "medio" : "basso";
  const titolo = "percentuale di test passati in questa categoria"
    + frazione
    + "\nSolo confrontabile con un altro punteggio della STESSA "
      "categoria: le categorie hanno un numero di test diverso.";
  return { testo: pct + frazione, cls: cls, titolo: titolo };
}

// quante categorie esistono davvero: il totale nel "3/6" deve essere il
// numero reale, non una costante che invecchia da sola
let CATEGORIE_TOTALE = 6;

function disegnaModelli() {
  const soloFree = benchFree.checked;
  const cat = benchCat ? benchCat.value : "all";
  const lista = tuttiModelli.filter((m) => (soloFree ? m.free : true));
  benchModels.replaceChildren();
  for (const m of lista) {
    const riga = el("label", "mp-row");
    const cb = el("input");
    cb.type = "checkbox";
    cb.value = m.id;
    // i free partono gia' spuntati: e' quello che si prova per primo
    cb.checked = !!m.free;
    const nome = el("span", "mp-name");
    nome.textContent = m.short || m.id;
    const meta = el("span", "mp-meta");
    const p = punteggioDi(m, cat);
    if (p) {
      meta.textContent = p.testo;
      meta.className = "mp-meta punteggio " + p.cls;
    } else {
      meta.textContent = "—";
      meta.className = "mp-meta nonmisurato";
    }
    const free = el("span", "mp-free");
    free.textContent = m.free ? "free" : "";
    riga.appendChild(cb);
    riga.appendChild(nome);
    riga.appendChild(free);
    riga.appendChild(meta);
    benchModels.appendChild(riga);
  }
  aggiornaConteggio();
}

// Cambiare categoria ricalcola i punteggi mostrati: sono la stessa
// domanda con parametri diversi, non un dato fisso.
on(benchCat, "change", disegnaModelli);

on(benchModels, "change", aggiornaConteggio);
on(benchFree, "change", disegnaModelli);
on($("bench-allfree"), "click", () => {
  for (const cb of benchModels.querySelectorAll("input")) {
    const m = tuttiModelli.find((x) => x.id === cb.value);
    cb.checked = !!(m && m.free);
  }
  aggiornaConteggio();
});
on($("bench-none"), "click", () => {
  for (const cb of benchModels.querySelectorAll("input")) cb.checked = false;
  aggiornaConteggio();
});

// --------------------------------------------------------------- prova manuale
// Un prompt, un modello, tutta la trascrizione. Non c'e' un punteggio:
// quello che serve e' vedere cosa scrive e quali tool chiama, per capire
// perche' un modello perde un task automatico.
const provaPrompt = $("prova-prompt");
const provaModel = $("prova-model");
const provaOut = $("prova-out");

function disegnaProva(r) {
  provaOut.replaceChildren();
  if (r.error) {
    const e = el("div", "prova-err");
    e.textContent = "prova fallita: " + r.error;
    provaOut.appendChild(e);
    return;
  }
  const riga = el("div", "prova-meta");
  riga.textContent = r.model + " — " + r.seconds + "s · " + r.iterations +
    " iterazioni · " + r.completion_tokens + " token · " +
    r.tool_calls + " tool (" + r.tool_errors + " errori) · $" +
    (r.cost_usd || 0).toFixed(6);
  provaOut.appendChild(riga);
  const passi = el("div", "prova-steps");
  for (const s of r.steps || []) {
    if (s.tipo === "testo") {
      const p = el("div", "prova-step testo");
      p.textContent = s.testo;
      passi.appendChild(p);
    } else if (s.tipo === "tool") {
      const p = el("div", "prova-step tool");
      p.textContent = "→ " + s.nome + " " + JSON.stringify(s.argomenti || {}).slice(0, 200);
      passi.appendChild(p);
    } else if (s.tipo === "risultato") {
      const p = el("div", "prova-step res " + (s.ok ? "ok" : "ko"));
      p.textContent = (s.ok ? "✓ " : "✗ ") + String(s.testo || "").slice(0, 300);
      passi.appendChild(p);
    }
  }
  provaOut.appendChild(passi);
  if (r.reply) {
    const fin = el("div", "prova-step finale");
    fin.textContent = r.reply;
    provaOut.appendChild(fin);
  }
  if (r.stopped_because && r.stopped_because !== "max_iterations") {
    const w = el("div", "prova-err");
    w.textContent = "fermato: " + r.stopped_because;
    provaOut.appendChild(w);
  }
}

on($("prova-run"), "click", async () => {
  const prompt = (provaPrompt.value || "").trim();
  const model = (provaModel.value || "").trim();
  if (!prompt) { provaOut.textContent = "scrivi prima un compito"; return; }
  if (!model) { provaOut.textContent = "scegli un modello"; return; }
  const btn = $("prova-run");
  btn.disabled = true;
  provaOut.textContent = "in corso… " + model;
  try {
    const r = await fetch("/api/prova", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, model }),
    });
    const d = await r.json();
    if (!r.ok) { provaOut.textContent = d.error || ("errore " + r.status); return; }
    disegnaProva(d);
  } catch (e) {
    provaOut.textContent = "connessione fallita: " + e;
  } finally {
    btn.disabled = false;
  }
});

const benchPanel = $("bench");
const benchLog = $("bench-log");
const benchOut = $("bench-out");
let benchTimer = null;

function openBench() {
  benchPanel.classList.remove("hidden");
  pollBench();
}
function closeBench() {
  benchPanel.classList.add("hidden");
  if (benchTimer) { clearInterval(benchTimer); benchTimer = null; }
}
on($("btn-bench"), "click", openBench);
on($("bench-close"), "click", closeBench);
// via on(), non addEventListener diretto: se il pannello manca, questo
// era l'unico punto che uccideva TUTTO lo script che segue. Serve
// core.js perche' il bundle e' un unico script: un solo elemento
// assente e la pagina resta a meta' senza dire perche'.
on(benchPanel, "click", (e) => { if (e.target === benchPanel) closeBench(); });

on($("bench-run"), "click", async () => {
  const scelti = modelliScelti();
  // Niente selezione = niente benchmark. Meglio dirlo qui che lasciare
  // che il server campioni da solo: se vuoi tre modelli e ne hai scelti
  // zero, il risultato sarebbe un altro elenco e sembrerebbe funzionare.
  if (!scelti.length) {
    benchOut.textContent = "";
    benchLog.textContent = "nessun modello selezionato: spunta almeno una casella";
    return;
  }
  $("bench-run").disabled = true;
  benchOut.textContent = "";
  benchLog.textContent = "avvio… " + scelti.length + " modelli";
  try {
    const r = await fetch("/api/bench", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        models: scelti,
        category: $("bench-cat").value,
      }),
    });
    const d = await r.json();
    if (!r.ok) {
      // errore del server: si vede qui, non solo in fondo al pannello
      benchLog.textContent = "";
      statoBench(d.error || ("errore " + r.status), "ko");
      $("bench-run").disabled = false;
      addText("error", d.error || `errore ${r.status}`);
      return;
    }
    // il totale arriva subito: la percentuale ha un denominatore
    attesaTotale = d.runs || 0;
    statoBench("in corso — 0/" + attesaTotale + " run", "on");
    pollBench();
  } catch (e) {
    benchLog.textContent = "";
    // anche un errore di rete deve dirlo dove si guarda: se resta "in
    // corso" per sempre, sembra che stia lavorando
    statoBench("connessione fallita: " + e, "ko");
    $("bench-run").disabled = false;
    addText("error", String(e));
  } finally {
    $("bench-run").disabled = false;
    if (!benchTimer) pollBench();
  }
});

// Stato e avanzamento, in alto nel pannello. Il conteggio dei run
// e' quello che serve per capire quanto manca: un "sta girando" senza
// numeri non dice niente quando un benchmark dura tre minuti.
const benchStatus = $("bench-status");
let attesaTotale = 0;

function statoBench(testo, classe) {
  benchStatus.textContent = testo;
  benchStatus.className = "bench-status " + (classe || "");
}

// Il testo dell'avanzamento, senza mostrarlo. Serve a chi deve
// aggiungere qualcosa: il ramo "fermo da 30 secondi" scrive
// "59/88 run · attento, fermo da 44s", e per farlo deve poter
// leggere il conto invece di ricalcolarlo.
//
// contaAvanzamento non tornava niente — scriveva dentro e basta — e
// usarla come valore dentro una stringa stampava "undefined". Che su
// un pannello e' peggio di non stampare niente: sembra un dato.
function testoAvanzamento(log, finiti, modelliVisti) {
  // Il conto lo da' il server. Prima contavamo le righe di log
  // visibili, ma il server manda solo gli ultimi 60: con 88 run le
  // prime ~28 non arrivavano mai, e il numero non poteva superare
  // 60. Mostrava "59/88" quando in realta' era a meta' — non un
  // benchmark fermo, un contatore che non sapeva contare.
  //
  // Il fallback sul log serve solo se il server e' vecchio: senza, la
  // funzione restituirebbe zero e il pannello direbbe "0/88" su un
  // benchmark che sta funzionando.
  const n = (typeof finiti === "number") ? finiti
    : (log || []).filter((l) => /^\s{2}\S+:\s/.test(l)).length;
  const visti = (modelliVisti || []).length;
  const modelli = visti || new Set((log || []).filter((l) => /^== /.test(l))
    .map((l) => l.slice(3, -3))).size;
  if (!attesaTotale) return "in corso…";
  const pct = Math.min(100, Math.round((n / attesaTotale) * 100));
  return modelli + " modelli · " + n + "/" + attesaTotale +
    " run · " + pct + "%";
}

function contaAvanzamento(log, finiti, modelliVisti) {
  // una riga per run finito: "== modello ==" segna l'inizio, "  task:"
  // segna un risultato. Contiamo i risultati.
  statoBench("in corso — " + testoAvanzamento(log, finiti, modelliVisti), "on");
}

function pollBench() {
  if (benchTimer) return;
  // Quante volte si puo' sbagliare prima di dichiarare la connessione
  // persa. Una richiesta every 1,5 secondi per tre minuti sono
  // centoventi richieste: se basta che una fallisca per chiudere il
  // polling, una singola scossa di rete lascia la UI ferma mentre il
  // benchmark continua a girare sul server. Il lavoro va avanti e non
  // lo vedi piu', e la cosa sembra un crash.
  //
  // Non e' che il server sia andato via: si puo' chiedere. Solo se
  // falliscono piu' richieste di fila, e il server conferma che
  // risponde male, si smette.
  let errori = 0;
  benchTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/bench/status");
      const d = await r.json();
      errori = 0;
      benchLog.textContent = (d.log || []).join("\n");
      benchLog.scrollTop = benchLog.scrollHeight;
      if (d.running) {
              contaAvanzamento(d.log, d.finiti, d.modelli_visti);
              // Il conto può essere giusto e il lavoro fermo lo stesso: un
              // run è una chiamata a un servizio esterno, e se quella
              // chiamata si blocca il finally non arriva mai. Il pannello
              // continuerebbe a dire "in corso" all'infinito, e 59/88 non
              // distingue "ci manca un pezzo" da "manterrà così".
              //
              // La soglia è generosa: un modello lento (GLM risponde in
              // 43-55 secondi) è lento, non fermo. Due minuti senza un
              // passo solo non passano per un modello che sta pensando.
              const fermo = d.fermo_da || 0;
              if (fermo > 120) {
                statoBench("fermo da " + Math.floor(fermo / 60) + " min " +
                           (fermo % 60) + "s — non avanza. Riavvia il benchmark.",
                           "ko");
                addText("warn", "nessun passo da " + fermo + " secondi");
              } else if (fermo > 30) {
                statoBench(testoAvanzamento(d.log, d.finiti, d.modelli_visti) + " · attento, fermo da " +
                           fermo + "s", "on");
              } else {
                statoBench(testoAvanzamento(d.log, d.finiti, d.modelli_visti), "on");
              }
            } else {
        clearInterval(benchTimer);
        benchTimer = null;
        renderBenchResult(d.result);
        const n = (d.log || []).filter((l) => /^\s{2}\S+:\s/.test(l)).length;
        statoBench(n === 0 ? "nessun run eseguito" : "finito — " + n + " run", "ok");
      }
    } catch (e) {
      errori += 1;
      // Non e' finito: si riprova. Un benchmark dura minuti, e un
      // tentativo non riuscito non vuol dire che il server sia andato.
      if (errori < 12) {
        statoBench("connessione instabile — riprovo (" + errori + ")", "on");
        return;
      }
      clearInterval(benchTimer);
      benchTimer = null;
      statoBench("connessione persa dopo " + errori + " tentativi: " + e +
                 " — il benchmark puo' continuare sul server", "ko");
    }
  }, 1500);
}

// La tabella arriva come testo monospaziato dal backend, che l'ha
// costruita per il terminale. Riutilizzarla è più onesto che rifare la
// formattazione in JS e rischiare due versioni che divergono.
function renderBenchResult(res) {
  benchOut.textContent = "";
  if (!res) return;
  const pre = el("pre", "benchlog");
  pre.textContent = res.table || "";
  benchOut.appendChild(pre);

  if (res.unusable && res.unusable.length) {
    const n = el("div", "small dim");
    n.textContent = "Non misurati (il provider li riserva ad altri client): "
      + res.unusable.join(", ");
    benchOut.appendChild(n);
  }
  // i punteggi appena misurati finiscono nel selettore
  loadModels();
}

// Riceve il catalogo gia' ordinato da loadModels e riempie le liste del
// pannello. Una sola fonte: se il selettore in alto e le caselle qui
// prendessero i dati da due fetch separati, potrebbero mostrare modelli
// diversi e la scelta sarebbe illudente.


// ------------------------------------------------------------- Opzioni
// Il pannello piu' sensibile dell'app: qui si scrivono le credenziali.
//
// Regola che governa tutto il file: il valore di una chiave gia'
// salvata non viene mai letto, e non viene neanche rimesso nel campo.
// Il campo parte vuoto ogni volta, e se lasci vuoto e salvi, la chiave
// viene cancellata. E' l'unico modo per essere onesto su cosa succede
// al file .env: se il campo e' vuoto, sparisce anche la chiave.
const opzioniPanel = $("opzioni");
const chiaviLista = $("chiavi-lista");
const gratisLista = $("gratis-lista");
const opzioniNota = $("opzioni-nota");

function apriOpzioni() {
  opzioniPanel.classList.remove("hidden");
  caricaOpzioni();
}
function chiudiOpzioni() {
  opzioniPanel.classList.add("hidden");
}
on($("btn-opzioni"), "click", apriOpzioni);
on($("opzioni-close"), "click", chiudiOpzioni);
on(opzioniPanel, "click", (e) => { if (e.target === opzioniPanel) chiudiOpzioni(); });


// ---- Servizio e modello: due menu, non due campi di testo
// Erano due righe di chiavi come le altre, e si perdevano. Sono la
// configurazione, non una credenziale: un id scritto a mano che sbaglia
// fallisce solo alla prima chiamata, con un errore che sembra di rete.
// Un menu non puo' sbagliare.
//
// Il menu servizio elenca SOLO i provider che hanno una chiave: quelli
// senza si rifiutano al momento di usarne uno, quindi el menu direbbe
// "usa groq" e poi fallirebbe. I motori locali compaiono sempre, perche'
// non hanno bisogno di chiave e sono l'unica via senza account.
const optProvider = $("opt-provider");
const optModel = $("opt-model");
const optReasoning = $("opt-reasoning");
const optMaxIters = $("opt-max-iters");
const optContextNote = $("opt-context-note");
const optBudgetTaskTokens = $("budget-task-tokens");
const optBudgetTaskCost = $("budget-task-cost");
const optBudgetTaskIters = $("budget-task-iters");
const optBudgetSessTokens = $("budget-sess-tokens");
const optBudgetSessCost = $("budget-sess-cost");
const optBudgetSessReqs = $("budget-sess-reqs");
const optBudgetDayCost = $("budget-day-cost");
const optBudgetMonthCost = $("budget-month-cost");
const optBudgetSalva = $("budget-salva");
const optBudgetReset = $("budget-reset");
const optBudgetMsg = $("budget-msg");
const optBudgetGlobalMsg = $("budget-global-msg");
const optMsg = $("opt-provider-msg");

const NOME_PROVIDER = {
  openrouter: "OpenRouter",
  groq: "Groq",
  nvidia: "NVIDIA NIM",
  together: "Together",
  cerebras: "Cerebras",
  mistral: "Mistral",
  openai: "OpenAI",
  ollama: "Ollama (locale)",
  lmstudio: "LM Studio (locale)",
};

function chiaviConfigurate(d) {
  const out = new Set();
  for (const k of d.chiavi || []) {
    // ORCHESTRA_PROVIDER e ORCHESTRA_MODEL non sono chiavi: sono
    // configurazione, e non devono finire nella lista
    if (k.presente && k.chiave.endsWith("_API_KEY")) out.add(k.chiave);
  }
  return out;
}

function providerDaChiave(envVar) {
  // GROQ_API_KEY -> groq ; ORCHESTRA_OLLAMA_URL -> ollama
  if (envVar.startsWith("ORCHESTRA_")) {
    return envVar.slice("ORCHESTRA_".length, -"_URL".length).toLowerCase();
  }
  return envVar.slice(0, -"_API_KEY".length).toLowerCase();
}

function disegnaProvider(d) {
  const configurati = chiaviConfigurate(d);
  const disponibili = new Set();
  for (const k of d.chiavi || []) {
    if (k.presente && k.chiave.endsWith("_API_KEY")) {
      disponibili.add(providerDaChiave(k.chiave));
    }
  }
  // i motori locali non hanno chiave: se sono configurati, sono usabili
  for (const k of d.chiavi || []) {
    if (k.presente && k.chiave.endsWith("_URL")) {
      disponibili.add(providerDaChiave(k.chiave));
    }
  }
  for (const motore of d.motori || []) disponibili.add(motore);

  const corrente = d.provider || "";
  // I selettori del servizio sono due — Opzioni e header della chat —
  // e devono dire la stessa cosa. Se ne aggiungessi un terzo, questa
  // lista e' il posto dove metterlo: due copie che possono divergere
  // sono peggio di una sola che si aggiorna tardi.
  const selettori = [optProvider, $("provider-pick")].filter(Boolean);
  const utili = Array.from(disponibili).sort();
  for (const s of selettori) {
    s.replaceChildren();
    if (!utili.length) {
      s.appendChild(new Option("nessun servizio configurato", ""));
    } else {
      for (const p of utili) {
        s.appendChild(new Option(NOME_PROVIDER[p] || p, p));
      }
      s.value = utili.includes(corrente) ? corrente : utili[0];
    }
    s.disabled = false;
  }
  const segnalato = [optMsg, $("provider-note")].filter(Boolean);
    for (const m of segnalato) {
      // Solo quando qualcosa non torna. "ora: <nome>" e' il menu
      // a tendina con un altro livello di affidabilita', e quando il
      // servizio e' regolare la riga resta vuota.
      m.textContent = utili.length
        ? (utili.includes(corrente)
            ? ""
            : "servizio attuale non piu' disponibile")
        : "nessuna chiave API configurata";
      m.className = "small " + (utili.includes(corrente) ? "verde" : "rosso");
    }
      // Reasoning level from server state
      if (optReasoning) {
        const r = d.reasoning || "";
        optReasoning.value = r;
        optReasoning.disabled = false;
      }
      // Max iterazioni + limite contesto corrente. Il limite è calcolato
      // dal modello in uso (75% della sua finestra): si mostra, non si
      // imposta — cambiarlo a mano litigherebbe con l'allineamento
      // automatico al cambio modello.
      if (optMaxIters) {
        optMaxIters.value = d.max_iterations || "";
        optMaxIters.disabled = false;
      }
      if (optContextNote && typeof d.context_limit === "number") {
        const k = Math.round(d.context_limit / 1000);
        optContextNote.textContent = `compattazione oltre ~${k}k token (75% della finestra del modello)`;
      }
      // Header reasoning pick
      const hdrReasoning = $("reasoning-pick");
      if (hdrReasoning) {
        const r = d.reasoning || "";
        hdrReasoning.value = r;
        hdrReasoning.disabled = false;
      }

      // Budget: populate fields from server state
      if (d.budget) {
        const b = d.budget;
        optBudgetTaskTokens.value = b.task_tokens || "";
        optBudgetTaskCost.value = b.task_cost || "";
        optBudgetTaskIters.value = b.task_iters || "";
        optBudgetSessTokens.value = b.sess_tokens || "";
        optBudgetSessCost.value = b.sess_cost || "";
        optBudgetSessReqs.value = b.sess_reqs || "";
        optBudgetDayCost.value = b.day_cost || "";
        optBudgetMonthCost.value = b.month_cost || "";
      }
    }

async function caricaModelli(prov, preseleziona) {
  optModel.replaceChildren();
  if (!prov) { optModel.disabled = true; return; }
  optModel.disabled = true;
  optModel.appendChild(new Option("carico…", ""));
  try {
    const r = await fetch("/api/modelli?provider=" + encodeURIComponent(prov));
    const d = await r.json();
    optModel.replaceChildren();
    if (!r.ok) {
      optModel.appendChild(new Option(d.error || "errore", ""));
      optModel.disabled = true;
      return;
    }
    // i gratuiti per primi: sono quelli che si possono usare subito
    const lista = (d.modelli || []).slice().sort((a, b) =>
      (a.free === b.free) ? a.id.localeCompare(b.id) : (a.free ? -1 : 1));
    for (const m of lista) {
      const s = (m.scores || {})[scopeAttivo];
      const punteggio = typeof s === "number" ? "  " + s.toFixed(2) : "";
      const ctx = m.context ? " " + Math.round(m.context / 1000) + "k" : "";
      optModel.appendChild(new Option(
        m.short + punteggio + ctx + " · " + (m.free ? "free" : "a pagamento"), m.id));
    }
    optModel.disabled = false;
    if (preseleziona && lista.some((m) => m.id === preseleziona)) {
      optModel.value = preseleziona;
    } else if (d.modelli && d.modelli.length) {
      const primo = lista.find((m) => m.free) || lista[0];
      optModel.value = primo.id;
    }
  } catch (e) {
    optModel.replaceChildren();
    optModel.appendChild(new Option("connessione fallita", ""));
  }
}

// Il cambio di servizio e' una sola azione, richiamata dai due
// selettori. Prima era legato solo a quello delle Opzioni, e dalla chat
// si poteva cambiare il modello ma non il servizio: due modelli con lo
// stesso nome ("qwen3-8b" su OpenRouter e su Groq) non si distinguevano,
// e la richiesta andava a un servizio diverso da quello che credevi.
async function cambiaServizio(p) {
  if (!p) return;
  // invalida ogni caricaOpzioni() in volo: la sua risposta porta il
  // provider di quando e' partita e rimetterebbe il menu sul vecchio
  generazioneChiavi++;
  const nota = $("provider-note");
  if (nota) { nota.textContent = "cambio servizio…"; nota.className = "small dim"; }
  optMsg.textContent = "cambio servizio…";
  try {
    const r = await fetch("/api/provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: p }),
    });
    const d = await r.json();
    if (!r.ok) {
      const testo = d.error || ("errore " + r.status);
      optMsg.textContent = testo;
      optMsg.className = "small rosso";
      if (nota) { nota.textContent = testo; nota.className = "small rosso"; }
      // il selettore torna indietro: mostrare un servizio che non e'
      // quello in uso e' peggio che non mostrarlo
      disegnaProvider(d.stato ? d : { chiavi: [], provider: "", motori: [] });
      return;
    }
    const nome = NOME_PROVIDER[p] || p;
    // Se il server ha dovuto cambiare anche il modello — quello vecchio
    // non esiste su questo servizio — si dice, e si sceglie subito
    // quello nuovo. Senza, la select mostra il modello di un servizio
    // e l'agente chiama un altro: la divergenza si vede solo alla
    // prima risposta, e sembra un errore di rete.
    if (d.modello_cambiato && d.modello) {
      const msg = nome + " — modello " + d.modello;
      optMsg.textContent = msg;
      if (nota) { nota.textContent = msg; nota.className = "small giallo"; }
      await caricaModelli(p, d.modello);
      await loadModels();
      // stessa ragione del ramo sotto: Opzioni deve dire il servizio
      // vero, non quello che ricordava di prima
      await caricaOpzioni();
      return;
    }
    // Niente "ora: <nome>": il menu a tendina lo dice gia', e ripeterlo
    // in una riga sotto e' la stessa informazione due volte con un
    // diverso livello di affidabilita'. Resta solo il colore verde,
    // che distingue "cambiato" da "non e' successo niente".
    optMsg.textContent = "";
    optMsg.className = "small verde";
    if (nota) { nota.textContent = ""; nota.className = "small verde"; }
    // entrambi i selettori devono dire la stessa cosa dopo il cambio
    for (const s of [optProvider, $("provider-pick")]) {
      if (s) s.value = p;
    }
    // Si ricarica tutto, non solo il menu. /api/chiavi risponde con il
    // provider VERO, e quella e' l'unica lettura che non puo' essere
    // superata da una richiesta partita prima. Senza, il menu delle
    // Opzioni restava sul servizio precedente mentre la chat era gia'
    // su quello nuovo: misurato, non ipotizzato.
    await caricaModelli(p, d.modello || null);
    await loadModels();
    await caricaOpzioni();
  } catch (e) {
    // Il select torna a quello che il server sta usando davvero. Prima
    // restava sul valore nuovo: il menu diceva "Groq" e la chat
    // rispondeva con OpenRouter, e la divergenza si vedeva solo alla
    // prima risposta — sembrava un errore di rete.
    //
    // Il messaggio d'errore resta, perche' il select da solo non dice
    // PERCHE'. Dopo il ripristino il menu e' la verita' e il testo e'
    // la spiegazione: due cose diverse.
    await caricaOpzioni();
    const testo = "cambio fallito: " + e;
    optMsg.textContent = testo;
    optMsg.className = "small rosso";
    if (nota) { nota.textContent = testo; nota.className = "small rosso"; }
  }
}

// on() accetta gia' un elemento assente senza esplodere (vedi core.js),
// quindi qui basta passargli quello che c'e'.
on($("opt-provider"), "change", (e) => cambiaServizio(e.target.value));

on(optReasoning, "change", async () => {
  const r = optReasoning.value;
  optMsg.textContent = "cambio reasoning…";
  try {
    const resp = await fetch("/api/reasoning", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reasoning: r }),
    });
    const d = await resp.json();
    if (!resp.ok) {
      optMsg.textContent = d.error || ("errore " + resp.status);
      optMsg.className = "small rosso";
      // ripristina il valore precedente
      await caricaOpzioni();
      return;
    }
    optMsg.textContent = "";
    optMsg.className = "small verde";
  } catch (e) {
    optMsg.textContent = "cambio fallito: " + e;
    optMsg.className = "small rosso";
    await caricaOpzioni();
  }
});

on(optMaxIters, "change", async () => {
  const n = parseInt(optMaxIters.value, 10);
  if (!n || n < 1) {
    await caricaOpzioni();
    return;
  }
  optMsg.textContent = "cambio iterazioni…";
  try {
    const resp = await fetch("/api/iterazioni", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_iterations: n }),
    });
    const d = await resp.json();
    if (!resp.ok) {
      optMsg.textContent = d.error || ("errore " + resp.status);
      optMsg.className = "small rosso";
      await caricaOpzioni();
      return;
    }
    optMsg.textContent = "";
    optMsg.className = "small verde";
  } catch (e) {
    optMsg.textContent = "cambio fallito: " + e;
    optMsg.className = "small rosso";
    await caricaOpzioni();
  }
});

// Header reasoning pick
const hdrReasoning = $("reasoning-pick");
on(hdrReasoning, "change", async () => {
  const r = hdrReasoning.value;
  try {
    const resp = await fetch("/api/reasoning", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reasoning: r }),
    });
    const d = await resp.json();
    if (!resp.ok) {
      // ripristina
      await caricaOpzioni();
      return;
    }
  } catch (e) {
    await caricaOpzioni();
  }
});

// Budget save
on(optBudgetSalva, "click", async () => {
  const body = {
    task_tokens: optBudgetTaskTokens.value ? parseInt(optBudgetTaskTokens.value) : 0,
    task_cost: optBudgetTaskCost.value ? parseFloat(optBudgetTaskCost.value) : 0,
    task_iters: optBudgetTaskIters.value ? parseInt(optBudgetTaskIters.value) : 0,
    sess_tokens: optBudgetSessTokens.value ? parseInt(optBudgetSessTokens.value) : 0,
    sess_cost: optBudgetSessCost.value ? parseFloat(optBudgetSessCost.value) : 0,
    sess_reqs: optBudgetSessReqs.value ? parseInt(optBudgetSessReqs.value) : 0,
    day_cost: optBudgetDayCost.value ? parseFloat(optBudgetDayCost.value) : 0,
    month_cost: optBudgetMonthCost.value ? parseFloat(optBudgetMonthCost.value) : 0,
  };
  optBudgetMsg.textContent = "salvataggio...";
  try {
    const resp = await fetch("/api/budget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await resp.json();
    if (!resp.ok) {
      optBudgetMsg.textContent = d.error || ("errore " + resp.status);
      optBudgetMsg.className = "small rosso";
      return;
    }
    optBudgetMsg.textContent = "salvato";
    optBudgetMsg.className = "small verde";
  } catch (e) {
    optBudgetMsg.textContent = "salvataggio fallito: " + e;
    optBudgetMsg.className = "small rosso";
  }
});

// Budget reset
on(optBudgetReset, "click", async () => {
  optBudgetMsg.textContent = "reset...";
  try {
    const resp = await fetch("/api/budget/reset", { method: "POST" });
    const d = await resp.json();
    if (!resp.ok) {
      optBudgetMsg.textContent = d.error || ("errore " + resp.status);
      optBudgetMsg.className = "small rosso";
      return;
    }
    optBudgetMsg.textContent = "reset completato";
    optBudgetMsg.className = "small verde";
    await caricaOpzioni();
  } catch (e) {
    optBudgetMsg.textContent = "reset fallito: " + e;
    optBudgetMsg.className = "small rosso";
  }
});

// Lo stesso gesto, nella chat. Il modello segue il servizio: e' quello
// che ti aspetti, e senza questa sincronizzazione scegli un
// modello su un servizio e lo scambi su un altro.
on($("provider-pick"), "change", (e) => cambiaServizio(e.target.value));

on(optModel, "change", async () => {
  const m = optModel.value;
  if (!m) return;
  optMsg.textContent = "cambio modello…";
  try {
    const r = await fetch("/api/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: m }),
    });
    const d = await r.json();
    if (!r.ok) {
      // Il select torna al modello vero: dopo un rifiuto restava
      // quello nuovo, e il menu mentiva su quello che l'agente
      // avrebbe usato davvero. `caricaOpzioni` preseleziona il modello
      // del server, quindi è lei a rimettere quello giusto.
      await caricaOpzioni();
      optMsg.textContent = d.error || ("errore " + r.status);
      optMsg.className = "small rosso";
      return;
    }
    // Come sopra: il menu dice gia' quale modello e' attivo.
    optMsg.textContent = "";
    optMsg.className = "small verde";
    loadModels();
    // Stesso motivo di core.js: il limite segue il modello, e la nota
    // va riletta o mostra il valore di prima.
    await caricaOpzioni();
  } catch (e) {
    optMsg.textContent = "cambio fallito: " + e;
    optMsg.className = "small rosso";
  }
});


// ---- Permessi: stato e prova del canale
// Lo stato serve a non dare l'idea che "per questa sessione" voglia
// dire "per sempre": ogni concessione mostra quando scade, e si revoca
// con un clic. Un permesso che non si vede è un permesso che hai
// dimenticato di dare.
const permessiStato = $("permessi-stato");
const permessiMsg = $("permessi-msg");

function disegnaPermessi(st) {
  if (!permessiStato) return;
  permessiStato.replaceChildren();
  const aggiungi = (testo, classe) => {
    const d = el("div", "permesso-stato-riga " + (classe || ""));
    d.textContent = testo;
    permessiStato.appendChild(d);
    return d;
  };
  aggiungi("Cartella di lavoro: " + (st.root || "?"), "info");
  if (!st.in_attesa || !st.in_attesa.length) {
    aggiungi("Nessuna domanda in attesa", "ok");
  } else {
    aggiungi(st.in_attesa.length + " domande in attesa", "attesa");
  }
  for (const s of st.sessione || []) {
    const minuti = Math.max(1, Math.round(s.scade_tra / 60));
    const riga = aggiungi("Concesso: " + s.percorso + " — scade fra " + minuti + " min", "ok");
    const rev = el("button", "ghost piccolo", "Revoca");
    riga.appendChild(rev);
    on(rev, "click", async () => {
      try {
        const r = await fetch("/api/permessi", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revoca: s.percorso }),
        });
        const d = await r.json();
        disegnaPermessi(d.stato || st);
      } catch (e) { /* resta com'e' */ }
    });
  }
  for (const p of st.negati || []) {
    aggiungi("Negato: " + p, "ko");
  }
}

async function caricaPermessi() {
  try {
    const r = await fetch("/api/permessi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    disegnaPermessi(d);
  } catch (e) {
    permessiMsg.textContent = "stato non disponibile: " + e;
  }
}

on($("permessi-prova"), "click", async () => {
  permessiMsg.textContent = "genero una domanda…";
  try {
    const r = await fetch("/api/permesso/prova", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const d = await r.json();
    if (!r.ok) { permessiMsg.textContent = d.error || "errore"; return; }
    permessiMsg.textContent = d.in_attesa
      ? "domanda partita: dovrebbe comparire il riquadro"
      : "nessun riquadro: ricarica con Ctrl+F5, la pagina è vecchia";
    permessiMsg.className = "small " + (d.in_attesa ? "verde" : "rosso");
    caricaPermessi();
  } catch (e) {
    permessiMsg.textContent = "connessione fallita: " + e;
    permessiMsg.className = "small rosso";
  }
});

// lo stato dei permessi si ricarica insieme al resto del pannello:
// un permesso concesso durante un turno deve comparire qui, non al
// prossimo avvio


// riga di una chiave: etichetta, stato, campo vuoto, due pulsanti
function rigaChiave(k) {
  const riga = el("div", "chiave-riga");
  const testa = el("div", "chiave-testa");
  const nome = el("span", "chiave-nome");
  nome.textContent = k.etichetta;
  const statoEl = el("span", "chiave-stato " + (k.presente ? "ok" : "vuota"));
  // l'indizio sono 4 caratteri, mai di piu': serve a distinguere due
  // chiavi, non a usarne una
  statoEl.textContent = k.presente ? ("configurata " + k.indizio) : "non configurata";
  testa.appendChild(nome);
  testa.appendChild(statoEl);

  const campo = el("input", "chiave-input");
  campo.type = "password";
  campo.placeholder = k.presente ? "lascia vuoto per non cambiarla" : "incolla qui la chiave";
  campo.autocomplete = "off";
  campo.spellcheck = false;

  const azioni = el("div", "chiavi-azioni");
  const salva = el("button", "primary", "Salva");
  const togli = el("button", "ghost", "Rimuovi");
  const messaggio = el("span", "small dim");

  salva.onclick = async () => {
    salva.disabled = true;
    messaggio.textContent = "salvo…";
    const v = campo.value.trim();
    if (!v && k.presente) {
      messaggio.textContent = "campo vuoto: lascialo cosi' per non toccarla";
      salva.disabled = false;
      return;
    }
    try {
      const r = await fetch("/api/chiavi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chiave: k.chiave, valore: v }),
      });
      const d = await r.json();
      if (!r.ok) {
        messaggio.textContent = d.error || ("errore " + r.status);
        messaggio.className = "small rosso";
      } else {
        messaggio.textContent = d.messaggio;
        messaggio.className = "small verde";
        campo.value = "";  // non tenere la chiave in memoria del DOM
        caricaOpzioni();
      }
    } catch (e) {
      messaggio.textContent = "connessione fallita: " + e;
      messaggio.className = "small rosso";
    } finally {
      salva.disabled = false;
    }
  };

  togli.onclick = async () => {
    if (k.presente && !confirm("Rimuovere " + k.etichetta + " dal .env?")) return;
    togli.disabled = true;
    try {
      const r = await fetch("/api/chiavi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chiave: k.chiave, valore: "" }),
      });
      const d = await r.json();
      messaggio.textContent = r.ok ? d.messaggio : (d.error || "errore");
      messaggio.className = r.ok ? "small verde" : "small rosso";
      caricaOpzioni();
    } finally { togli.disabled = false; }
  };

  azioni.appendChild(salva);
  azioni.appendChild(togli);
  riga.appendChild(testa);
  riga.appendChild(campo);
  riga.appendChild(azioni);
  riga.appendChild(messaggio);
  return riga;
}

// scheda di un servizio gratis: cosa offre, cosa costa, come iniziare
function schedaGratis(s) {
  const d = el("div", "gratis-scheda" + (s.chiave ? "" : " senza-chiave"));
  const capo = el("div", "gratis-capo");
  const nome = el("span", "gratis-nome");
  nome.textContent = s.nome;
  const badge = el("span", "gratis-badge " + (s.chiave ? "con-chiave" : "senza-chiave"));
  badge.textContent = s.chiave ? "serve account" : "nessuna chiave";
  capo.appendChild(nome);
  capo.appendChild(badge);

  const costo = el("div", "gratis-costo");
  costo.textContent = s.costo;
  const cosa = el("div", "gratis-cosa");
  cosa.textContent = s.cosa;
  const req = el("div", "gratis-req dim small");
  req.textContent = s.requisiti;
  const come = el("code", "gratis-come");
  come.textContent = (s.come || "").trim();

  d.appendChild(capo);
  d.appendChild(costo);
  d.appendChild(cosa);
  d.appendChild(req);
  d.appendChild(come);
  if (s.avvertenza) {
    const w = el("div", "gratis-avv");
    w.textContent = s.avvertenza;
    d.appendChild(w);
  }
  return d;
}

// Una risposta in volo non deve poter sovrascrivere una scelta piu'
// recente. caricaOpzioni() parte all'avvio e arriva DOPO un cambio
// servizio: senza questo contatore, la sua risposta — che contiene il
// provider di quando e' partita — rimetteva il menu a openrouter
// mentre la chat era gia' su groq. Due menu che dicono cose diverse
// e' peggio di un menu che non si aggiorna: l'utente sceglie, crede
// di aver scelto, e non e' successo niente.
//
// Non e' una paranoia: e' successo, misurato, con i due selettori a
//perti su servizi diversi.
let generazioneChiavi = 0;

async function caricaOpzioni() {
  const mia = ++generazioneChiavi;
  chiaviLista.replaceChildren();
  gratisLista.replaceChildren();
  opzioniNota.textContent = "carico…";
  try {
    const r = await fetch("/api/chiavi");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    // una risposta vecchia non disegna niente: il provider e' cambiato
    // mentre questa era in volo, e ridisegnere rimetterebbe il valore
    // superato
    if (mia !== generazioneChiavi) return;
    opzioniNota.textContent = d.nota_gratis || "";

    caricaPermessi();
    // Le skill anche. Una chiamata in piu' a /api/skill durante
    // l'apertura del pannello, e su 103 file la costruzione dell'indice
    // richiede qualche decimo di secondo: per quello NON aspetta il
    // resto del pannello. Se il server non risponde, la sezione resta
    // muta e Opzioni funziona lo stesso.
    caricaSkill();

    // provider e modello: due menu in alto, non due righe di chiavi
    disegnaProvider(d);
    // Il modello vero preselezionato, non il primo free: senza, aprire
    // il pannello (o ricaricarlo dopo un cambio) rimette il menu sul
    // primo free e sembra che il cambio non abbia funzionato — mentre
    // il server ha già cambiato e risponde col modello nuovo.
    caricaModelli(d.provider || optProvider.value, d.model || null);

    // i motori locali arrivano in una richiesta separata: sono una
    // domanda di rete a localhost e possono costare un timeout. Se
    // aspettassimo, il pannello si aprirebbe dopo due secondi per
    // mostrare che non c'e' nessun motore locale.
    const bottoni = d.motori || [];
    if (bottoni.length) {
      fetch("/api/locali")
        .then((r) => (r.ok ? r.json() : null))
        .then((ld) => {
          const locali = (ld && ld.locali) || {};
          const nomi = Object.keys(locali);
          const avviso = $("locali-avviso");
          if (!avviso) return;
          avviso.style.display = "block";
          avviso.textContent = nomi.length
            ? "Motore locale attivo: " + nomi.join(", ") +
              " — questi modelli sono gia' disponibili, senza chiave e senza rete."
            : "Nessun motore locale in ascolto. Serve installarlo una volta: " +
              bottoni.join(" o ") + ".";
        })
        .catch(() => { /* se non risponde, resta silenzioso: e' un extra */ });
    }

    const cat = d.catalogo || {};
    if (cat.modelli) {
      const t = el("div", "opzioni-riepilogo");
      t.textContent = "Catalogo attuale: " + cat.modelli + " modelli, " +
        (cat.gratuiti || 0) + " gratuiti con tool-calling.";
      gratisLista.appendChild(t);
    }

    for (const k of d.chiavi || []) chiaviLista.appendChild(rigaChiave(k));
    for (const s of d.servizi_gratis || []) gratisLista.appendChild(schedaGratis(s));
  } catch (e) {
    opzioniNota.textContent = "caricamento fallito: " + e;
  }
}

// ------------------------------------------------- scegli per tipo di lavoro
// La domanda vera non e' "quale modello e' il migliore" ma "quale
// modello e' il migliore PER QUELLO CHE DEVO FARE". Un modello puo'
// essere ottimo in ragionamento e mediocre in React Native, e scegliere
// il migliore in assoluto e' scegliere quello sbagliato.
//
// Regola che non si negozia: si sceglie solo fra i modelli MISURATI in
// quella categoria. Se non ce ne sono, si dice che non ce ne sono. Un
// modello non misurato non e' il migliore, e' sconosciuto, e su un
// impianto dove si paga la differenza e' una decisione, non una
// arrotondatura.
const CAT_ETICHETTE = {
  code: "Codice in generale",
  js: "Coding JavaScript",
  web: "Coding web (HTML/CSS)",
  app: "Coding app (React Native)",
  reasoning: "Ragionamento",
  instruction: "Seguire istruzioni",
  tool_use: "Uso dei tool",
  writing: "Scrittura",
  extraction: "Estrazione",
};
const routingCat = $("routing-cat");
const routingOut = $("routing-out");
const routingTop = $("routing-top");

// Lo scope dell'header e il selettore del pannello sono lo stesso
// controllo in due posti. Se potessero divergere, la raccomandazione
// mostrerebbe una categoria e i punteggi nell'header un'altra — quindi
// qui si tiene il sincrone, non si duplica lo stato.
const scopePick = $("scope-pick");
const scopeNote = $("scope-note");

// ---- lo scope nell'header: scegli il lavoro, il modello si sceglie da solo
// Con quanti modelli misurati una raccomandazione e' credibile? Con uno
// solo non lo e': e' un'anomalia, non un primato. "web" e "app" hanno
// una misurazione ciascuna perche' una sola corsa su tutte le categorie
// le ha sfiorate, e consigliare quel modello con tanta sicurezza
// mentirebbe. Sopra due misurazioni si parla; sotto, si avverte.
const MIN_PER_CONSIGLIARE = 2;

function misuratiPer(scope) {
  return tuttiModelli
    .filter((m) => typeof (m.scores || {})[scope] === "number")
    .sort((a, b) => b.scores[scope] - a.scores[scope]);
}

function migliorePer(scope) {
  return misuratiPer(scope)[0] || null;
}

function applicaScope(scope) {
  scopeAttivo = scope || "";
  if (routingCat && scope) routingCat.value = scope;
  // i punteggi nelle opzioni cambiano con lo scope: senza rifare
  // loadModels, il selettore mostrerebbe i numeri della categoria vecchia
  loadModels();
  if (!scope) {
    scopeNote.textContent = "";
    scopeNote.className = "scope-note";
    return;
  }
  const candidati = misuratiPer(scope);
  const nome = CAT_ETICHETTE[scope] || scope;
  if (!candidati.length) {
    // non misurato: si dice, non si indovina
    scopeNote.textContent = nome + ": nessuno misurato";
    scopeNote.className = "scope-note avviso";
    return;
  }
  if (candidati.length < MIN_PER_CONSIGLIARE) {
    const unico = candidati[0];
    scopeNote.textContent = nome + ": pochi dati (" + candidati.length +
      " misurato). Migliore " + unico.short + " " +
      unico.scores[scope].toFixed(2) + ", ma conviene misurarne altri";
    scopeNote.className = "scope-note attesa";
    return;
  }
  const best = candidati[0];
  const attuale = modelPick.value;
  if (attuale === best.id) {
    scopeNote.textContent = "già il migliore per " + nome;
    scopeNote.className = "scope-note ok";
    return;
  }
  if (busy) {
    // durante un turno non si cambia modello sotto gli occhi di chi
    // sta guardando: si dice cosa serve e si applica dopo
    scopeNote.textContent = "dopo il turno: " + best.short;
    scopeNote.className = "scope-note attesa";
    return;
  }
  scopeNote.textContent = "→ " + best.short + " " + best.scores[scope].toFixed(2);
  scopeNote.className = "scope-note ok";
  const sw = $("scope-note");
  sw.style.cursor = "pointer";
  sw.onclick = async () => {
    try {
      const r = await fetch("/api/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: best.id }),
      });
      // Il menu si aggiorna da solo con loadModels(), quindi basta un
      // punto di sospeso: il cambio e' avvenuto e si vede.
      if (r.ok) { loadModels(); scopeNote.textContent = ""; }
    } catch (e) { scopeNote.textContent = "cambio fallito: " + e; }
  };
}

on(scopePick, "change", () => applicaScope(scopePick.value));

// Quante task ha ogni categoria lo SA il server: /api/categorie
// risponde dai task realmente registrati. La lista qui sotto e' solo
// l'ordine di visualizzazione.
//
// Prima la lista era anche l'unica fonte di verita', e cosi' due
// categorie senza nessun task comparivano come "non ancora misurato"
// — cioe' come se aspettassero solo qualcuno che le misurasse. Non
// e' vero: non esiste nulla da misurare. La differenza e' tutta qui,
// ed e' la differenza fra "non l'ho ancora fatto" e "non posso farlo".
let categorieServer = [];

async function caricaCategorie() {
  try {
    const r = await fetch("/api/categorie");
    if (!r.ok) return;
    const d = await r.json();
    categorieServer = d.categorie || [];
  } catch (e) {
    // resta la lista vuota: meglio mostrare meno che fingere
  }
}

// L'etichetta la sa il server: CAT_ETICHETTE e' un fallback per
// quando non ha ancora risposto. Se le due divergono, vince il
// server — e' lui che conta i task.
function etichettaCategoria(id, fallback) {
  const c = categorieServer.find((x) => x.id === id);
  return (c && (c.label || c.nome)) || CAT_ETICHETTE[id] || fallback || id;
}

function taskDi(categoria) {
  const c = categorieServer.find((x) => x.id === categoria);
  return c ? c.tasks : null;   // null = il server non ne parla
}

function disegnaCategorieRouting() {
  if (!routingCat) return;
  const misurate = new Set();
  for (const m of tuttiModelli) {
    for (const c of Object.keys(m.scores || {})) misurate.add(c);
  }
  // L'ordine viene dal server, non da una lista scritta qui. Prima
  // c'era un array con tutte e nove le categorie: se ne avessi
  // aggiunta una decima al backend, questo menu — e quello del
  // benchmark — avrebbero continuato a non mostrarla, e nessuno
  // avrebbe detto niente. Un elenco statico invecchia da solo e
  // mente quando succede.
  const ordine = categorieServer.map((c) => c.id);
  const utili = ordine.filter((c) => misurate.has(c));

  // Il menu del benchmark mostra TUTTE le categorie, misurate o no:
  // se ne manca una dal menu, non esiste un modo per misurarla. E
  // accanto al nome dice quanti task ha, perche' "estrazione" senza
  // quel numero sembra una categoria minore.
  if (benchCat) {
    const scelto = benchCat.value;
    benchCat.replaceChildren();
    benchCat.appendChild(new Option("tutte", "all"));
    for (const c of categorieServer) {
      const n = c.tasks;
      const etichetta = (CAT_ETICHETTE[c.id] || c.label || c.id)
        + (n ? " · " + n + " test" : " · senza test");
      benchCat.appendChild(new Option(etichetta, c.id));
    }
    benchCat.value = categorieServer.some((c) => c.id === scelto) ? scelto : "all";
  }

  routingCat.replaceChildren();
  for (const c of utili) {
    routingCat.appendChild(new Option(etichettaCategoria(c), c));
  }
  if (!routingCat.options.length) {
    routingCat.appendChild(new Option("nessuna categoria misurata", ""));
  }

  // l'header ha gli stessi valori, piu' "tutto": e' la vista di tutti
  // i giorni, e non ha senso costringerla a una categoria sola
  if (scopePick) {
    const valoreCorrente = scopeAttivo;
    scopePick.replaceChildren();
    scopePick.appendChild(new Option("tutto", ""));
    for (const c of utili) {
      scopePick.appendChild(new Option(etichettaCategoria(c), c));
    }
    scopePick.value = utili.includes(valoreCorrente) ? valoreCorrente : "";
    scopePick.disabled = !utili.length;
  }

  if (routingOut) {
    // Due cose diverse, e dirle insieme e' mentire.
    //
    // "non ancora misurato" = ci sono task, nessuno e' stato misurato.
    //   E' una promessa: basta lanciare il benchmark.
    // "nessun test" = non esiste task per questa categoria. Non e' una
    //   promessa, e' un buco: finche' non se ne scrive uno, quella
    //   categoria non e' confrontabile con nessuna altra, e il modello
    //   "migliore per scrittura" non esiste.
    const mancanti = ordine.filter((c) => !misurate.has(c));
    const vuote = mancanti.filter((c) => taskDi(c) === 0);
    const daMisurare = mancanti.filter((c) => taskDi(c) !== 0);
    const parti = [];
    if (daMisurare.length) {
      parti.push("non ancora misurato: " + daMisurare.join(", "));
    }
    if (vuote.length) {
      parti.push("senza test: " + vuote.join(", ")
        + " — non confrontabili finche' non si scrivono i task");
    }
    routingOut.textContent = parti.join(" · ");
    routingOut.className = vuote.length ? "avviso-grave" : "";
  }
}

function scegliModello() {
  const cat = routingCat.value;
  routingTop.replaceChildren();
  if (!cat) { routingTop.textContent = "prima misura qualcosa"; return; }
  const candidati = tuttiModelli
    .filter((m) => typeof (m.scores || {})[cat] === "number")
    .sort((a, b) => b.scores[cat] - a.scores[cat]);
  if (!candidati.length) {
    const p = el("div", "prova-err");
    p.textContent = "nessun modello misurato in \u201c" + (CAT_ETICHETTE[cat] || cat) +
      "\u201d: lancia il benchmark su questa categoria prima";
    routingTop.appendChild(p);
    return;
  }
  const migliore = candidati[0];
  const riga = el("div", "routing-vincitore");
  riga.textContent = migliore.short + " — " + migliore.scores[cat].toFixed(2) +
    (migliore.free ? " (free)" : "");
  routingTop.appendChild(riga);
  if (candidati.length > 1) {
    const resto = el("div", "routing-altri");
    resto.textContent = "altri: " + candidati.slice(1, 5)
      .map((m) => m.short + " " + m.scores[cat].toFixed(2)).join(" · ");
    routingTop.appendChild(resto);
  }
  const btn = el("button", "primary", "Usa questo modello");
  routingTop.appendChild(btn);
  on(btn, "click", async () => {
    btn.disabled = true;
    try {
      const r = await fetch("/api/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: migliore.id }),
      });
      if (r.ok) {
        loadModels();
        const p = el("div", "routing-ok");
        p.textContent = "ora stai usando " + migliore.short;
        routingTop.appendChild(p);
      } else {
        const d = await r.json();
        const p = el("div", "prova-err");
        p.textContent = d.error || ("errore " + r.status);
        routingTop.appendChild(p);
      }
    } finally { btn.disabled = false; }
  });
}

on($("routing-go"), "click", scegliModello);

// -------------------------------------------------------------- Prior
// L'API /api/prior esisteva da prima ma nessuno la chiamava: la
// chiave era nel .env, il bottone non c'era, e i 158 prior che
// Orchestra scaricava non arrivavano a schermo da nessuna parte.
//
// Un dato scaricato e non mostrato non e' un dato: e' lavoro sprecato
// e una promessa non mantenuta.
on($("prior-go"), "click", async () => {
  const out = $("prior-out"), cop = $("prior-copertura");
  if (!out) return;
  out.textContent = "scarico…";
  if (cop) cop.replaceChildren();
  try {
    const r = await fetch("/api/prior");
    const d = await r.json();
    out.textContent = d.messaggio || "";
    const c = d.copertura || {};
    if (!cop) return;
    const righe = [
      ["prior scaricati", c.prior],
      ["presenti in catalogo", c.nel_catalogo],
      ["di cui gratuiti", c.gratuiti],
      ["modelli in catalogo", c.catalogo],
    ];
    const t = el("table", "mini-table");
    for (const [k, v] of righe) {
      const tr = el("tr");
      tr.appendChild(el("td", "dim", k));
      tr.appendChild(el("td", "", String(v ?? "—")));
      t.appendChild(tr);
    }
    cop.replaceChildren(t);
  } catch (e) {
    out.textContent = "non raggiungibile: " + e;
  }
});

function aggiornaCatalogoUI(elenco, corrente) {
  tuttiModelli = elenco || [];
  disegnaModelli();
  // il routing si riempia qui: i punteggi arrivano con il catalogo, e
  // ricalcolarli qui evita che mostri categorie vecchie dopo un benchmark
  disegnaCategorieRouting();
  // il totale delle categorie viene dal server. Una costante nel
  // frontend invecchia in silenzio: un giorno "4/6" con nove categorie
  // e nessuno che se ne accorge.
  fetch("/api/categorie")
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      if (!d || !d.totale_categorie) return;
      CATEGORIE_TOTALE = d.totale_categorie;
      disegnaModelli();
    })
    .catch(() => { /* il totale resta quello noto: meglio che sparire */ });
  if (provaModel) {
    provaModel.replaceChildren();
    for (const m of tuttiModelli) {
      const o = new Option(m.short + " · " + (m.free ? "free" : price_label(m)), m.id);
      provaModel.appendChild(o);
    }
    // la prova parte dal modello in uso: e' quello che ti interessa
    // capire perche' non funziona
    if (corrente && tuttiModelli.some((m) => m.id === corrente)) {
      provaModel.value = corrente;
    }
  }
}

// ------------------------------------------------------------------ skill
//
// Il pannello skill in Opzioni.
//
// Tre sezioni: quante sono, da dove vengono, e le due liste. Le generate
// sono separate dalle scaricate perche' non hanno la stessa affidabilita' —
// una e' scritta da qualcun altro, l'altra e' un'affermazione dello stesso
// agente che la usa, e tu devi poter distinguere le due cose.
//
// Con 103 skill la lista non entra in una schermata. Il filtro c'e' per
// quello, e filtra mentre scrivi: attendere un tasto e poi scorrere
// cento righe e' piu' lento di quello che stai facendo.
//
// Il pulsante "Aggiorna" esiste perche' l'indice puo' cambiare fuori dal
// browser: l'agente genera una skill mentre tu stai guardando la pagina,
// e senza un ricaricamento la lista mente per trenta secondi.

let skillDati = { scaricate: [], generate: [], categorie: [], totale: 0,
                  scaricate_n: 0, generate_n: 0, nel_prompt_max: 0,
                  cestino: [] };

function skillPost(body) {
  return fetch("/api/skill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());
}

async function caricaSkill() {
  try {
    const d = await skillPost({ azione: "elenca" });
    if (d && !d.error) {
      skillDati = {
        scaricate: d.lista_scaricate || [],
        generate: d.lista_generate || [],
        categorie: d.categorie || [],
        totale: d.totale || 0,
        scaricate_n: d.scaricate || 0,
        generate_n: d.generate || 0,
        nel_prompt_max: d.nel_prompt_max || 0,
        cestino: d.cestino || [],
      };
      disegnaSkill();
    }
  } catch (e) {
    // Le skill non sono un requisito. Se questo fallisce, Opzioni si
    // apre lo stesso e la sezione resta vuota: meglio un pannello
    // muto che un pannello che impedisce di cambiare modello.
    const r = $("skill-riepilogo");
    if (r) r.textContent = "non raggiungibile: " + (e.message || e);
  }
}

function skillCorrisponde(s, testo) {
  if (!testo) return true;
  const t = testo.toLowerCase();
  return (s.nome || "").toLowerCase().includes(t)
      || (s.categoria || "").toLowerCase().includes(t)
      || (s.descrizione || "").toLowerCase().includes(t);
}

function skillCarta(s, generata) {
  // Una scheda, non una riga. Con cento skill in lista si scorreva per
  // metri; in griglia se ne vedono tre o quattro per riga e confrontare
  // i nomi diventa immediato — che e' la ragione per cui uno cerca
  // una skill: capire se quella che serve c'e' gia'.
  const carta = el("div", "skill-carta");
  if (generata) carta.classList.add("skill-carta-generata");

  const capo = el("div", "skill-carta-capo");
  // Il '+' e' lo stesso segno del prompt: due posti che parlano lo
  // stesso linguaggio, e uno sguardo basta per capire se una procedura
  // e' stata scritta da qualcun altro o dall'agente che la usa.
  if (generata) {
    const segno = el("span", "skill-segno");
    segno.textContent = "+";
    segno.title = s.con_prove
      ? "imparata dall'agente, con " + s.prove + " prove"
      : "imparata dall'agente, SENZA prove";
    capo.appendChild(segno);
  }
  const titolo = el("span", "skill-carta-nome");
  titolo.textContent = s.nome;
  capo.appendChild(titolo);
  carta.appendChild(capo);

  const desc = el("div", "skill-carta-desc");
  desc.textContent = s.descrizione || "(senza descrizione)";
  desc.title = s.descrizione || "";
  carta.appendChild(desc);

  const meta = el("div", "skill-carta-meta");
  const info = [];
  if (s.categoria) info.push(s.categoria);
  if (generata) {
    info.push(s.con_prove
      ? s.prove + (s.prove === 1 ? " prova" : " prove")
      : "senza prove");
  }
  if (s.usata) {
    info.push("usata " + s.usata + (s.usata === 1 ? " volta" : " volte"));
  }
  meta.textContent = info.join(" · ");
  carta.appendChild(meta);

  const pie = el("div", "skill-carta-pie");
  const apri = el("button", "ghost skill-pulsante");
  apri.textContent = "Apri";
  apri.title = "Leggi la procedura";
  apri.onclick = () => skillApri(s);
  pie.appendChild(apri);

  const via = el("button", "ghost skill-pulsante skill-bottone-cancella");
  via.textContent = "Cestino";
  via.title = "Metti nel cestino, da cui puoi rimetterla";
  via.onclick = () => skillCancella(s.nome);
  pie.appendChild(via);
  carta.appendChild(pie);

  return carta;
}

function skillCartaCestino(v) {
  const carta = el("div", "skill-carta skill-carta-cestino");
  const capo = el("div", "skill-carta-capo");
  const titolo = el("span", "skill-carta-nome");
  titolo.textContent = v.nome;
  capo.appendChild(titolo);
  carta.appendChild(capo);

  const meta = el("div", "skill-carta-meta");
  meta.textContent = v.data || "";
  carta.appendChild(meta);

  const pie = el("div", "skill-carta-pie");
  const rimetti = el("button", "ghost skill-pulsante");
  rimetti.textContent = "Rimetti";
  rimetti.onclick = () => skillRipristina(v.nome);
  pie.appendChild(rimetti);

  const distruggi = el("button", "ghost skill-pulsante skill-bottone-cancella");
  distruggi.textContent = "Cancella";
  distruggi.title = "Cancellazione definitiva: non si recupera";
  distruggi.onclick = () => skillDefinitiva(v.nome);
  pie.appendChild(distruggi);
  carta.appendChild(pie);
  return carta;
}

function skillCestinoNota(t) {
  const n = $("skill-cestino-nota");
  if (n) n.textContent = t;
}

function aggiornaDa(elenco, cestino) {
  skillDati.scaricate = elenco.lista_scaricate || [];
  skillDati.generate = elenco.lista_generate || [];
  skillDati.categorie = elenco.categorie || [];
  skillDati.totale = elenco.totale || 0;
  skillDati.scaricate_n = elenco.scaricate || 0;
  skillDati.generate_n = elenco.generate || 0;
  skillDati.nel_prompt_max = elenco.nel_prompt_max || 0;
  skillDati.cestino = cestino || [];
  disegnaSkill();
}

async function skillRipristina(nome) {
  try {
    const d = await skillPost({ azione: "ripristina", nome });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillCestinoNota(nome + " rimessa");
    } else {
      skillCestinoNota((d && d.error) || "ripristino rifiutato");
    }
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
  }
}

// Chiede una parola, non un si'/'no'. La cancellazione definitiva non ha
// ritorno, e un pulsante "Cancella" che cancella quello che si voleva
// tenere e' il modo migliore per perdere roba. Un prompt che chiede
// di scrivere CANCELLA costa due secondi e ferma i diti sbagliati.
function chiediConferma(nome) {
  const r = window.prompt(
    "Cancellare DEFINITIVAMENTE " + nome + "?\n\nNon si recupera.",
    "scrivi CANCELLA");
  return (r || "").trim().toUpperCase() === "CANCELLA";
}

async function skillDefinitiva(nome) {
  if (!chiediConferma(nome)) return;
  try {
    const d = await skillPost({ azione: "cancella_definitivo", nome });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillCestinoNota(nome + " cancellata per sempre");
    } else {
      skillCestinoNota((d && d.error) || "cancellazione rifiutata");
    }
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
  }
}

async function skillSvuotaTutto() {
  const n = (skillDati.cestino || []).length;
  if (!n) {
    skillCestinoNota("il cestino e' gia' vuoto");
    return;
  }
  const r = window.prompt(
    "Cancellare DEFINITIVAMENTE " + n + " skill?\n\nNon si recupera nulla.",
    "scrivi CANCELLA");
  if ((r || "").trim().toUpperCase() !== "CANCELLA") return;
  try {
    const d = await skillPost({ azione: "svuota_cestino" });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillCestinoNota(d.rimosse + " cancellate per sempre");
    } else {
      skillCestinoNota((d && d.error) || "rifiutato");
    }
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
  }
}

async function skillApri(s) {
  try {
    // Il nome, non il percorso: il percorso lo risolve il server dentro
    // la radice delle skill. Passargliero significherebbe accettare
    // un percorso qualunque, e questa rotta non ha autenticazione.
    const r = await fetch("/api/skill/file?nome=" + encodeURIComponent(s.nome));
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.error || ("HTTP " + r.status));
    }
    const d = await r.json();
    const v = $("skill-vista");
    if (!v) return;
    v.hidden = false;
    const parti = [];
    parti.push(el("div", "skill-vista-testa",
      el("b", null, d.nome || s.nome),
      el("span", "dim small", " · " + (s.categoria || ""))));
    parti.push(el("pre", "skill-testo", d.contenuto || "(vuota)"));
    if (d.allegati && d.allegati.length) {
      parti.push(el("div", "skill-vista-nota",
        d.allegati.length + " file che viaggiano con questa skill: "
        + d.allegati.map((a) => a.nome).join(", ")));
    }
    v.replaceChildren(...parti);
    v.scrollIntoView({ block: "nearest" });
  } catch (e) {
    skillMossa("non riesco ad aprire: " + (e.message || e));
  }
}

function skillMossa(testo) {
  const n = $("skill-generate-nota");
  if (n) n.textContent = testo;
}

async function skillCancella(nome) {
  try {
    const d = await skillPost({ azione: "cancella", nome });
    if (d && d.ok) {
      // La risposta porta il cestino aggiornato: senza, la lista a
      // schermo e quella vera divergono, e il pannello mente proprio
      // dove deve rassicurare che niente e' andato perso.
      aggiornaDa(d.elenco, d.cestino);
      skillMossa(nome + " nel cestino");
    } else {
      skillMossa((d && d.error) || "cancellazione rifiutata");
    }
  } catch (e) {
    skillMossa("errore: " + (e.message || e));
  }
}

function disegnaSkill() {
  const somma = $("skill-riepilogo");
  if (somma) {
    const n = skillDati.totale;
    somma.textContent = n
      ? (n + " procedure · " + skillDati.scaricate_n + " scaricate, "
         + skillDati.generate_n + " imparate dall'agente · nel prompt: fino a "
         + skillDati.nel_prompt_max + " alla volta")
      : "nessuna. Importane da una cartella.";
  }

  const cats = $("skill-categorie");
  if (cats) {
    cats.replaceChildren();
    for (const c of skillDati.categorie) {
      const b = el("span", "skill-cat-pill");
      b.textContent = c.nome + " " + c.skill;
      b.title = "Filtra per questa categoria";
      b.onclick = () => {
        const f = $("skill-filtro");
        if (f) { f.value = c.nome; disegnaSkill(); }
      };
      cats.appendChild(b);
    }
  }

  const gen = $("skill-generate");
  if (gen) {
    gen.replaceChildren();
    if (!skillDati.generate.length) {
      // Il vuoto e' un messaggio, non uno spazio. "L'agente non ha
      // ancora imparato niente" e' una cosa che ti dice dove guardare.
      gen.appendChild(el("div", "skill-vuota",
        "Nessuna ancora. L'agente ne scrive una quando un metodo gli " +
        "funziona: glielo chiedi, o semplicemente lavora con lui e " +
        "guarda qui dopo."));
    } else {
      for (const s of skillDati.generate) gen.appendChild(skillCarta(s, true));
    }
  }

  // Il cestino si disegna insieme al resto. Sta qui e non in una
  // funzione sua perche' l'elenco e il cestino cambiano insieme —
  // rimettere una skill modifica l'uno E l'altro, e due funzioni
  // chiamate separatamente possono mostrare uno il nuovo elenco e
  // l'altro il cestino vecchio.
  const cest = $("skill-cestino");
  if (cest) {
    cest.replaceChildren();
    const nel = skillDati.cestino || [];
    if (!nel.length) {
      cest.appendChild(el("div", "skill-vuota",
        "Vuoto. Le skill che cancelli finiscono qui, e puoi rimetterle."));
    } else {
      for (const v of nel) cest.appendChild(skillCartaCestino(v));
    }
  }
  const notaCest = $("skill-cestino-nota");
  if (notaCest) {
    const nel = (skillDati.cestino || []).length;
    notaCest.textContent = nel ? nel + " da recuperare" : "";
  }

  const testo = ($("skill-filtro") && $("skill-filtro").value) || "";
  const sc = $("skill-scaricate");
  if (sc) {
    sc.replaceChildren();
    const filtrate = skillDati.scaricate.filter((s) => skillCorrisponde(s, testo));
    if (!skillDati.scaricate.length) {
      sc.appendChild(el("div", "skill-vuota", "Nessuna scaricata."));
    } else if (!filtrate.length) {
      sc.appendChild(el("div", "skill-vuota",
        "Nessuna corrisponde a “" + testo + "”."));
    } else {
      for (const s of filtrate) sc.appendChild(skillCarta(s, false));
      if (filtrate.length !== skillDati.scaricate.length) {
        sc.appendChild(el("div", "skill-conto",
          filtrate.length + " su " + skillDati.scaricate.length));
      }
    }
  }
}

function collegaSkill() {
  // on() vuole l'ELEMENTO, non l'id: passargli la stringa faceva
  // fallire la riga di addEventListener — una stringa e' truthy, quindi
  // la guardia "elemento assente" passava, e il pulsante restava
  // scollegato senza che nulla lo dicesse. Con l'errore in pagina,
  // pero', si vedeva subito.
  on($("skill-ricarica"), "click", caricaSkill);
  on($("skill-svuota"), "click", skillSvuotaTutto);
  on($("skill-importa"), "click", async () => {
    const inp = $("skill-cartella");
    const cartella = inp ? inp.value.trim() : "";
    if (!cartella) {
      skillMossa("scrivi la cartella dello store");
      if (inp) inp.focus();
      return;
    }
    skillMossa("importo da " + cartella + "…");
    try {
      const d = await skillPost({ azione: "importa", cartella });
      if (d && d.ok) {
        skillDati.scaricate = d.elenco.lista_scaricate || [];
        skillDati.generate = d.elenco.lista_generate || [];
        skillDati.categorie = d.elenco.categorie || [];
        skillDati.totale = d.elenco.totale || 0;
        skillDati.scaricate_n = d.elenco.scaricate || 0;
        skillDati.generate_n = d.elenco.generate || 0;
        skillDati.nel_prompt_max = d.elenco.nel_prompt_max || 0;
        disegnaSkill();
        skillMossa(d.importate + " importate");
        if (inp) inp.value = "";
      } else {
        skillMossa((d && d.error) || "importazione rifiutata");
      }
    } catch (e) {
      skillMossa("errore: " + (e.message || e));
    }
  });
  const filtro = $("skill-filtro");
  if (filtro) {
    filtro.addEventListener("input", () => disegnaSkill());
  }
}

// Si collega qui, in fondo al file, e non da un bootstrap centrale:
// in questo file gli handler sono registrati in linea appena sono
// definiti. Una funzione che nessuno chiama e' la stessa cosa dei
// selettori disabilitati di due giorni fa — la funzione c'e', il
// lavoro no, e la pagina sembra rotta.
collegaSkill();

// ---------------------------------------------------------- sezioni Opzioni
//
// Cinque sezioni, una per volta. Il nome intero nella barra, perche' sono
// nomi che significano qualcosa e abbreviarli costerebbe una decodifica a
// ogni clic.
//
// Le sezioni restano tutte nel DOM e si nascondono: ricaricare il
// contenuto a ogni cambio e' la via per perdere lo stato, e il filtro
// sulle skill finirebbe svuotato a ogni passaggio.
//
// Il primo caricamento e' pigro. Aprire Opzioni non deve scaricare
// l'indice di cento skill se poi vai solo a cambiare modello: si chiede
// quando serve e si ricorda, cosi' la seconda volta e' gia' fatto.

let sezioneSkillCaricata = false;

function mostraSezione(nome) {
  const sezioni = document.querySelectorAll(".opz-sez");
  let trovata = false;
  for (const s of sezioni) {
    const mostra = s.dataset.sez === nome;
    if (mostra) trovata = true;
    // hidden e' l'attributo, non lo stile: e' quello che il DOM finto
    // dei test rispetta, ed e' lo stesso che il browser usa per
    // l'accessibilita' (un display:none a mano lascia la sezione
    // leggibile dagli screen reader senza motivo).
    if (mostra) s.removeAttribute("hidden");
    else s.setAttribute("hidden", "");
  }
  const tabs = document.querySelectorAll(".opzioni-tab");
  for (const t of tabs) {
    if (t.dataset.sez === nome) t.classList.add("attiva");
    else t.classList.remove("attiva");
  }
  if (!trovata) return;
  // pigro: la prima volta che si arriva alle skill, si chiedono
  if ((nome === "skill" || nome === "cestino") && !sezioneSkillCaricata) {
    sezioneSkillCaricata = true;
    caricaSkill();
  }
  // Storico e memoria idem: si caricano quando si aprono, non
  // all'avvio. Caricarli sempre aggiungerebbe due richieste a ogni
  // apertura del pannello Opzioni, anche quando si va a cambiare solo
  // il modello.
  if (nome === "storico") caricaStorico();
  if (nome === "memoria") caricaMemoria();
}

function collegaSezioni() {
  const tabs = document.querySelectorAll(".opzioni-tab");
  for (const t of tabs) {
    t.addEventListener("click", () => mostraSezione(t.dataset.sez));
  }
  // I tasti freccia passano da una sezione all'altra. Non e' un
  // vezzo da aggiungere: senza, con cinque sezioni e nessun tab
  // premuto, il passaggio costa cinque clic, e il modo normale in cui
  // ci si muove in un'interfaccia a sezioni e' la tastiera.
  const nav = document.querySelector(".opzioni-nav");
  if (nav) {
    nav.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const nomi = Array.from(document.querySelectorAll(".opzioni-tab"))
        .map((t) => t.dataset.sez);
      const i = nomi.indexOf(document.querySelector(".opzioni-tab.attiva").dataset.sez);
      const j = e.key === "ArrowDown" ? (i + 1) % nomi.length
                                         : (i - 1 + nomi.length) % nomi.length;
      mostraSezione(nomi[j]);
      const t = document.querySelector(".opzioni-tab[data-sez=\'" + nomi[j] + "\']");
      if (t) t.focus();
      e.preventDefault();
    });
  }
}

collegaSezioni();

// ------------------------------------------------------------------ storico
// Le conversazioni salvate su disco. Il pannello si ricarica da sé quando
// si apre, non ha un pulsante "applica": quello che c'è è già applicato.

const storicoElenco = $("storico-elenco");
const storicoMsg = $("storico-msg");
const storicoNuova = $("storico-nuova");
const storicoRicarica = $("storico-ricarica");

function _storico_data(d) {
  try {
    return new Date(d * 1000).toLocaleString("it-IT", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return ""; }
}

async function caricaStorico() {
  if (!storicoElenco) return;
  storicoMsg.textContent = "caricamento...";
  storicoMsg.className = "small dim";
  try {
    const resp = await fetch("/api/storico");
    const d = await resp.json();
    if (!resp.ok) {
      storicoMsg.textContent = d.error || ("errore " + resp.status);
      storicoMsg.className = "small rosso";
      return;
    }
    storicoElenco.replaceChildren();
    const sessioni = d.sessioni || [];
    if (!sessioni.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.textContent = "Nessuna conversazione salvata.";
      storicoElenco.appendChild(li);
      storicoMsg.textContent = "";
      return;
    }
    for (const s of sessioni) {
      const li = document.createElement("li");
      li.className = "storico-riga" + (s.id === d.attiva ? " attiva" : "");

      const info = document.createElement("div");
      info.className = "storico-info";
      const titolo = document.createElement("span");
      titolo.className = "storico-titolo";
      titolo.textContent = s.titolo || "(senza titolo)";
      const meta = document.createElement("span");
      meta.className = "small dim";
      meta.textContent = `${_storico_data(s.aggiornata)} · ${s.n_messaggi} msg · ${s.modello || "?"}`;
      info.appendChild(titolo);
      info.appendChild(meta);
      li.appendChild(info);

      const bottoni = document.createElement("div");
      bottoni.className = "storico-bottoni";

      const apri = document.createElement("button");
      apri.textContent = s.id === d.attiva ? "Aperta" : "Apri";
      apri.disabled = s.id === d.attiva;
      apri.className = s.id === d.attiva ? "" : "primary";
      apri.addEventListener("click", async () => {
        storicoMsg.textContent = "apertura...";
        try {
          const r = await fetch("/api/storico/apri", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: s.id }),
          });
          const rd = await r.json();
          if (!r.ok) {
            storicoMsg.textContent = rd.error || ("errore " + r.status);
            storicoMsg.className = "small rosso";
            return;
          }
          // La conversazione cambia in chat: si ricarica lo snapshot
          // dalla stessa risposta, così non si legge uno stato vecchio.
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          storicoMsg.textContent = "conversazione aperta";
          storicoMsg.className = "small verde";
          await caricaStorico();
        } catch (e) {
          storicoMsg.textContent = "apertura fallita: " + e;
          storicoMsg.className = "small rosso";
        }
      });
      bottoni.appendChild(apri);

      const elimina = document.createElement("button");
      elimina.textContent = "Elimina";
      elimina.addEventListener("click", async () => {
        if (!confirm("Eliminare questa conversazione? Non si recupera.")) return;
        try {
          const r = await fetch("/api/storico/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: s.id }),
          });
          const rd = await r.json();
          if (!r.ok) {
            storicoMsg.textContent = rd.error || ("errore " + r.status);
            storicoMsg.className = "small rosso";
            return;
          }
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          storicoMsg.textContent = "eliminata";
          storicoMsg.className = "small verde";
          await caricaStorico();
        } catch (e) {
          storicoMsg.textContent = "eliminazione fallita: " + e;
          storicoMsg.className = "small rosso";
        }
      });
      bottoni.appendChild(elimina);

      li.appendChild(bottoni);
      storicoElenco.appendChild(li);
    }
    storicoMsg.textContent = "";
  } catch (e) {
    storicoMsg.textContent = "caricamento fallito: " + e;
    storicoMsg.className = "small rosso";
  }
}

if (storicoNuova) {
  storicoNuova.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/storico/nuova", { method: "POST" });
      const d = await r.json();
      if (!r.ok) {
        storicoMsg.textContent = d.error || ("errore " + r.status);
        storicoMsg.className = "small rosso";
        return;
      }
      if (d.snapshot) handle("snapshot", d.snapshot);
      storicoMsg.textContent = "nuova conversazione";
      storicoMsg.className = "small verde";
      await caricaStorico();
    } catch (e) {
      storicoMsg.textContent = "non riesco: " + e;
      storicoMsg.className = "small rosso";
    }
  });
}

if (storicoRicarica) {
  storicoRicarica.addEventListener("click", caricaStorico);
}

// ------------------------------------------------------------------- memoria

const memoriaElenco = $("memoria-elenco");
const memoriaMsg = $("memoria-msg");
const memoriaNuovo = $("memoria-nuovo");
const memoriaAggiungi = $("memoria-aggiungi");
const memoriaPercorso = $("memoria-percorso");

async function caricaMemoria() {
  if (!memoriaElenco) return;
  try {
    const resp = await fetch("/api/memoria");
    const d = await resp.json();
    if (!resp.ok) {
      memoriaMsg.textContent = d.error || ("errore " + resp.status);
      memoriaMsg.className = "small rosso";
      return;
    }
    if (memoriaPercorso && d.percorso) {
      memoriaPercorso.textContent = d.percorso;
    }
    memoriaElenco.replaceChildren();
    const fatti = d.fatti || [];
    if (!fatti.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.textContent = "Nessun fatto ricordato.";
      memoriaElenco.appendChild(li);
      memoriaMsg.textContent = "";
      return;
    }
    for (const fatto of fatti) {
      const li = document.createElement("li");
      li.className = "memoria-riga";

      const testo = document.createElement("span");
      testo.className = "memoria-fatto";
      testo.textContent = fatto;
      li.appendChild(testo);

      const via = document.createElement("button");
      via.textContent = "Dimentica";
      via.addEventListener("click", async () => {
        try {
          const r = await fetch("/api/memoria/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fatto: fatto }),
          });
          const rd = await r.json();
          if (!r.ok) {
            memoriaMsg.textContent = rd.error || ("errore " + r.status);
            memoriaMsg.className = "small rosso";
            return;
          }
          memoriaMsg.textContent = rd.tolto ? "dimenticato" : "non era in memoria";
          memoriaMsg.className = rd.tolto ? "small verde" : "small dim";
          await caricaMemoria();
        } catch (e) {
          memoriaMsg.textContent = "non riesco: " + e;
          memoriaMsg.className = "small rosso";
        }
      });
      li.appendChild(via);
      memoriaElenco.appendChild(li);
    }
    memoriaMsg.textContent = "";
  } catch (e) {
    memoriaMsg.textContent = "caricamento fallito: " + e;
    memoriaMsg.className = "small rosso";
  }
}

if (memoriaAggiungi) {
  memoriaAggiungi.addEventListener("click", async () => {
    const fatto = (memoriaNuovo.value || "").trim();
    if (!fatto) {
      memoriaMsg.textContent = "scrivi qualcosa da ricordare";
      memoriaMsg.className = "small dim";
      return;
    }
    try {
      const r = await fetch("/api/memoria/aggiungi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fatto: fatto }),
      });
      const d = await r.json();
      if (!r.ok) {
        memoriaMsg.textContent = d.error || ("errore " + r.status);
        memoriaMsg.className = "small rosso";
        return;
      }
      memoriaNuovo.value = "";
      memoriaMsg.textContent = d.nuovo ? "ricordato" : "era gi\u00e0 in memoria";
      memoriaMsg.className = "small verde";
      await caricaMemoria();
    } catch (e) {
      memoriaMsg.textContent = "non riesco: " + e;
      memoriaMsg.className = "small rosso";
    }
  });
}

if (memoriaNuovo) {
  memoriaNuovo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && memoriaAggiungi) memoriaAggiungi.click();
  });
}

// --------------------------------------------------------- pannello laterale
//
// Flex-item del body, non overlay: la chat si restringe e resta leggibile.
// Un modale coprirebbe la conversazione proprio mentre la si sfoglia.

const sidebar = $("sidebar");
const sideElenco = $("side-elenco");
const sideSkill = $("side-skill");
const sideMsg = $("side-msg");
const sideBtn = $("btn-side");

function sideAperta() {
  return !!sidebar && !sidebar.hasAttribute("hidden");
}

function apriSide(aperta) {
  if (!sidebar) return;
  if (aperta === undefined) aperta = !sideAperta();
  if (aperta) {
    sidebar.removeAttribute("hidden");
    caricaSide();
    caricaSideMemoria();
  } else {
    sidebar.setAttribute("hidden", "");
  }
}

// All'avvio si carica, sempre: la sidebar è aperta di default, e senza
// questa chiamata la cronologia restava vuota fino al primo Ctrl+B.
// Il bottone dell'header chiama riduciSide(), che non carica — solo
// Ctrl+B passava da qui, ed è per questo che "la prima volta non c'è".
// La X non c'è più: il bottone RIDUCE a una striscia invece di chiudere.
// La cronologia serve troppo spesso per costare due clic.
const sideRiduci = $("side-riduci");
if (sideRiduci) sideRiduci.addEventListener("click", riduciSide);

// Ctrl+B, come gli editor: è il gesto che le persone già hanno in mano.
document.addEventListener("keydown", (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "b") {
    ev.preventDefault();
    apriSide();
  }
});

function _sideData(ts) {
  try {
    const d = new Date(ts * 1000);
    const oggi = new Date();
    const stessoGiorno = d.toDateString() === oggi.toDateString();
    return d.toLocaleString("it-IT", stessoGiorno
      ? { hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "2-digit" });
  } catch (e) { return ""; }
}

async function caricaSide() {
  if (!sideElenco) return;
  if (sideMsg) { sideMsg.textContent = "caricamento..."; sideMsg.className = "small dim side-msg"; }
  await Promise.all([caricaSideSessioni(), caricaSideSkill()]);
  if (sideMsg) { sideMsg.textContent = ""; sideMsg.className = "small dim side-msg"; }
}

async function caricaSideSessioni() {
  try {
    const resp = await fetch("/api/storico");
    const d = await resp.json();
    if (!resp.ok) {
      if (sideMsg) { sideMsg.textContent = d.error || ("errore " + resp.status); sideMsg.className = "small rosso side-msg"; }
      return;
    }
    const sessioni = d.sessioni || [];
    const pinnate = new Set(JSON.parse(localStorage.getItem("orchestra.pin") || "[]"));
    // Le pinnate in cima: sono quelle che servono tutti i giorni, e
    // cercarsele in fondo a quaranta righe è il modo per non usarle.
    const ordinate = [...sessioni].sort((a, b) => {
      const pa = pinnate.has(String(a.id)) ? 0 : 1;
      const pb = pinnate.has(String(b.id)) ? 0 : 1;
      if (pa !== pb) return pa - pb;
      return (b.aggiornata || 0) - (a.aggiornata || 0);
    });

    sideElenco.replaceChildren();
    if (!sessioni.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.style.padding = "6px";
      li.textContent = "Nessuna conversazione salvata.";
      sideElenco.appendChild(li);
      return;
    }

    for (const s of ordinate) {
      const li = document.createElement("li");
      li.className = "side-riga" + (s.id === d.attiva ? " attiva" : "");

      const apri = document.createElement("button");
      apri.className = "side-apri";
      apri.title = s.titolo || "(senza titolo)";
      const testo = document.createElement("span");
      testo.className = "side-testo";
      testo.textContent = s.titolo || "(senza titolo)";
      const meta = document.createElement("span");
      meta.className = "side-meta";
      meta.textContent = `${_sideData(s.aggiornata)} · ${s.n_messaggi} msg`;
      apri.appendChild(testo);
      apri.appendChild(meta);
      apri.addEventListener("click", async () => {
        try {
          const r = await fetch("/api/storico/apri", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: s.id }),
          });
          const rd = await r.json();
          if (!r.ok) {
            if (sideMsg) { sideMsg.textContent = rd.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
            return;
          }
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          await caricaSideSessioni();
        } catch (e) {
          if (sideMsg) { sideMsg.textContent = "apertura fallita: " + e; sideMsg.className = "small rosso side-msg"; }
        }
      });
      li.appendChild(apri);

      const pin = document.createElement("button");
      const ePinnata = pinnate.has(String(s.id));
      pin.className = "side-pin" + (ePinnata ? " pinnato" : "");
      pin.textContent = ePinnata ? "\u2605" : "\u2606";
      pin.title = ePinnata ? "Togli dai preferiti" : "Metti nei preferiti";
      pin.addEventListener("click", () => {
        const attuali = new Set(JSON.parse(localStorage.getItem("orchestra.pin") || "[]"));
        const chiave = String(s.id);
        if (attuali.has(chiave)) attuali.delete(chiave); else attuali.add(chiave);
        localStorage.setItem("orchestra.pin", JSON.stringify([...attuali]));
        caricaSideSessioni();
      });
      li.appendChild(pin);

      // Elimina: mancava in sidebar, c'era solo nelle Opzioni. Chi vive
      // nella sidebar (ed è il pannello che si tiene aperto) non aveva
      // modo di cancellare una conversazione senza aprire le Opzioni.
      const del = document.createElement("button");
      del.className = "side-del";
      del.textContent = "\u2715";
      del.title = "Elimina questa conversazione";
      del.addEventListener("click", async () => {
        if (!confirm(`Eliminare "${(s.titolo || "(senza titolo)").slice(0, 40)}"? Non si recupera.`)) return;
        try {
          const r = await fetch("/api/storico/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: s.id }),
          });
          const rd = await r.json();
          if (!r.ok) {
            if (sideMsg) { sideMsg.textContent = rd.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
            return;
          }
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          await caricaSideSessioni();
        } catch (e) {
          if (sideMsg) { sideMsg.textContent = "eliminazione fallita: " + e; sideMsg.className = "small rosso side-msg"; }
        }
      });
      li.appendChild(del);

      sideElenco.appendChild(li);
    }
  } catch (e) {
    if (sideMsg) { sideMsg.textContent = "caricamento fallito: " + e; sideMsg.className = "small rosso side-msg"; }
  }
}

async function caricaSideSkill() {
  if (!sideSkill) return;
  try {
    const d = await skillPost({ azione: "elenca" });
    if (!d || d.error) return;
    const lista = [...(d.lista_scaricate || []), ...(d.lista_generate || [])]
      .filter(s => s && s.nome)
      .slice(0, 24);
    sideSkill.replaceChildren();
    if (!lista.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.style.padding = "4px 6px";
      li.textContent = "Nessuna skill installata.";
      sideSkill.appendChild(li);
      return;
    }
    for (const s of lista) {
      const li = document.createElement("li");
      li.className = "side-skill-riga";
      const nome = document.createElement("span");
      nome.className = "side-skill-nome";
      nome.textContent = s.nome;
      nome.title = s.descrizione || "";
      const apri = document.createElement("button");
      apri.className = "side-apri-pagina";
      apri.textContent = "apri";
      apri.title = "Apri la pagina della skill";
      apri.addEventListener("click", () => apriPaginaSkill(s.nome));
      li.appendChild(nome);
      li.appendChild(apri);
      sideSkill.appendChild(li);
    }
  } catch (e) {
    // Le skill non sono un requisito: la cronologia resta il pezzo
    // principale, e un errore qui non deve svuotarla.
  }
}

function apriPaginaSkill(nome) {
  // Pagina dedicata costruita col DOM. Il testo di una skill arriva da un
  // file: scriverlo dentro una stringa concatenata lo farebbe interpretare
  // come markup, mentre textContent lo mostra e basta.
  fetch("/api/skill/file?nome=" + encodeURIComponent(nome))
    .then(r => r.text())
    .then(testo => {
      const w = window.open("", "_blank", "width=820,height=640");
      if (!w) {
        if (sideMsg) { sideMsg.textContent = "il browser ha bloccato la finestra"; sideMsg.className = "small rosso side-msg"; }
        return;
      }
      w.document.title = nome;
      const h = w.document.createElement("h1");
      h.textContent = nome;
      const pre = w.document.createElement("pre");
      pre.textContent = testo;
      pre.style.whiteSpace = "pre-wrap";
      w.document.body.replaceChildren(h, pre);
    })
    .catch(e => {
      if (sideMsg) { sideMsg.textContent = "non riesco ad aprire la skill: " + e; sideMsg.className = "small rosso side-msg"; }
    });
}

const sideNuova = $("side-nuova");
if (sideNuova) {
  sideNuova.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/storico/nuova", { method: "POST" });
      const d = await r.json();
      if (!r.ok) {
        if (sideMsg) { sideMsg.textContent = d.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
        return;
      }
      if (d.snapshot) handle("snapshot", d.snapshot);
      await caricaSideSessioni();
    } catch (e) {
      if (sideMsg) { sideMsg.textContent = "non riesco: " + e; sideMsg.className = "small rosso side-msg"; }
    }
  });
}

const sideRicarica = $("side-ricarica");
if (sideRicarica) sideRicarica.addEventListener("click", caricaSide);

// ------------------------------------------------- memoria, dentro la sidebar
//
// Stessa logica del vecchio pannello in Opzioni, altri elementi. Opzioni
// è un posto da CONFIGURAZIONE; la memoria è contenuto, e stare accanto
// alla cronologia è dove si guarda.

const sideMemElenco = $("side-mem-elenco");
const sideMemInput = $("side-mem-input");
const sideMemAggiungi = $("side-mem-aggiungi");
const sideMemPercorso = $("side-mem-percorso");
const sideMemCerca = $("side-mem-cerca");
const sideMemStat = $("side-mem-stat");

function _memStatTesto(d) {
  // I fatti mai usati sono il numero che conta: dopo un mese a zero
  // vuol dire che non servono. Mostrarli e' il motivo per cui l'indice
  // esiste.
  const ind = d.indice;
  if (!ind || ind.errore) return "";
  const kb = Math.round((ind.byte_file || 0) / 1024);
  let s = `${ind.totale} fatti indicizzati`;
  if (kb) s += ` · ${kb} KB`;
  if (ind.mai_usati) s += ` · ${ind.mai_usati} mai cercati`;
  return s;
}

async function caricaSideMemoria() {
  if (!sideMemElenco) return;
  try {
    const resp = await fetch("/api/memoria");
    const d = await resp.json();
    if (!resp.ok) {
      if (sideMsg) { sideMsg.textContent = d.error || ("errore " + resp.status); sideMsg.className = "small rosso side-msg"; }
      return;
    }
    if (sideMemPercorso && d.percorso) sideMemPercorso.textContent = d.percorso;
    if (sideMemStat) sideMemStat.textContent = _memStatTesto(d);
    sideMemElenco.replaceChildren();
    const fatti = d.fatti || [];
    if (!fatti.length) {
      const li = document.createElement("li");
      li.className = "small dim side-mem-vuoto";
      li.textContent = "Nessun fatto ricordato.";
      sideMemElenco.appendChild(li);
      return;
    }
    for (const fatto of fatti) {
      const li = document.createElement("li");
      li.className = "side-mem-riga";

      const testo = document.createElement("span");
      testo.className = "side-mem-fatto";
      testo.textContent = fatto;
      li.appendChild(testo);

      const via = document.createElement("button");
      via.className = "side-mem-via";
      via.textContent = "\u00d7";
      via.title = "Dimentica";
      via.addEventListener("click", async () => {
        try {
          const r = await fetch("/api/memoria/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fatto: fatto }),
          });
          const rd = await r.json();
          if (!r.ok) {
            if (sideMsg) { sideMsg.textContent = rd.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
            return;
          }
          if (sideMsg) { sideMsg.textContent = rd.tolto ? "dimenticato" : "non era in memoria"; sideMsg.className = "small dim side-msg"; }
          await caricaSideMemoria();
        } catch (e) {
          if (sideMsg) { sideMsg.textContent = "non riesco: " + e; sideMsg.className = "small rosso side-msg"; }
        }
      });
      li.appendChild(via);
      sideMemElenco.appendChild(li);
    }
  } catch (e) {
    if (sideMsg) { sideMsg.textContent = "memoria non raggiungibile: " + e; sideMsg.className = "small rosso side-msg"; }
  }
}

async function sideMemRicorda() {
  const fatto = (sideMemInput.value || "").trim();
  if (!fatto) return;
  try {
    const r = await fetch("/api/memoria/aggiungi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fatto: fatto }),
    });
    const d = await r.json();
    if (!r.ok) {
      if (sideMsg) { sideMsg.textContent = d.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
      return;
    }
    sideMemInput.value = "";
    if (sideMsg) { sideMsg.textContent = d.nuovo ? "ricordato" : "era gi\u00e0 in memoria"; sideMsg.className = "small dim side-msg"; }
    await caricaSideMemoria();
  } catch (e) {
    if (sideMsg) { sideMsg.textContent = "non riesco: " + e; sideMsg.className = "small rosso side-msg"; }
  }
}

if (sideMemAggiungi) sideMemAggiungi.addEventListener("click", sideMemRicorda);
if (sideMemInput) {
  sideMemInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") sideMemRicorda();
  });
}

// La ricerca nella memoria. FTS5 dal server, con debounce: senza, una
// ricerca a ogni tasto su 5000 fatti e' una richiesta per carattere.
let _memTimer = null;
async function sideMemRicerca() {
  if (!sideMemElenco) return;
  const q = (sideMemCerca.value || "").trim();
  if (!q) { await caricaSideMemoria(); return; }
  try {
    const r = await fetch("/api/memoria/cerca", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, limite: 30 }),
    });
    const d = await r.json();
    if (!r.ok) {
      if (sideMsg) { sideMsg.textContent = d.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
      return;
    }
    if (sideMemStat) sideMemStat.textContent = _memStatTesto(d);
    sideMemElenco.replaceChildren();
    const trovati = d.risultati || [];
    if (!trovati.length) {
      const li = document.createElement("li");
      li.className = "small dim side-mem-vuoto";
      li.textContent = "Nessun fatto trovato.";
      sideMemElenco.appendChild(li);
      return;
    }
    for (const x of trovati) {
      const li = document.createElement("li");
      li.className = "side-mem-riga";
      const testo = document.createElement("span");
      testo.className = "side-mem-fatto";
      testo.textContent = x.testo;
      if (x.importante) {
        const segno = document.createElement("span");
        segno.className = "side-mem-imp";
        segno.textContent = "★";
        segno.title = "nel prompt di ogni conversazione";
        li.appendChild(segno);
      }
      li.appendChild(testo);
      const via = document.createElement("button");
      via.className = "side-mem-via";
      via.textContent = "×";
      via.title = "Dimentica";
      via.addEventListener("click", async () => {
        try {
          const rr = await fetch("/api/memoria/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fatto: x.testo }),
          });
          if (!rr.ok) return;
          await sideMemRicerca();
        } catch (e) { /* la ricerca resta com'è */ }
      });
      li.appendChild(via);
      sideMemElenco.appendChild(li);
    }
  } catch (e) {
    if (sideMsg) { sideMsg.textContent = "ricerca fallita: " + e; sideMsg.className = "small rosso side-msg"; }
  }
}

if (sideMemCerca) {
  sideMemCerca.addEventListener("input", () => {
    if (_memTimer) clearTimeout(_memTimer);
    _memTimer = setTimeout(sideMemRicerca, 250);
  });
  sideMemCerca.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); sideMemRicerca(); }
    if (ev.key === "Escape") {
      sideMemCerca.value = "";
      caricaSideMemoria();
    }
  });
}

// ------------------------------------------------------ pagina Capacità
//
// Modale, non pannello laterale: è un posto dove si VA a guardare e da
// cui si esce. Due tab, skill e strumenti, dallo stesso endpoint.

const capacita = $("capacita");
const capLista = $("cap-lista");
const capFiltro = $("cap-filtro");
const capMsg = $("cap-msg");
let capTab = "skill";
let capDati = { skill: [], tool: [] };

function apriCapacita() {
  if (!capacita) return;
  capacita.classList.remove("hidden");
  if (!capDati.skill.length && !capDati.tool.length) caricaCapacita();
}

function chiudiCapacita() {
  if (capacita) capacita.classList.add("hidden");
}

const btnCapacita = $("btn-capacita");
if (btnCapacita) btnCapacita.addEventListener("click", apriCapacita);

const capClose = $("capacita-close");
if (capClose) capClose.addEventListener("click", chiudiCapacita);

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && capacita && !capacita.classList.contains("hidden")) {
    chiudiCapacita();
  }
});

// Click sullo sfondo chiude: è il gesto che ci si aspetta da un modale.
if (capacita) {
  capacita.addEventListener("click", (ev) => {
    if (ev.target === capacita) chiudiCapacita();
  });
}

for (const t of document.querySelectorAll(".cap-tab")) {
  t.addEventListener("click", () => {
    capTab = t.dataset.tab;
    for (const o of document.querySelectorAll(".cap-tab")) {
      o.classList.toggle("attiva", o.dataset.tab === capTab);
    }
    disegnaCapacita();
  });
}

if (capFiltro) capFiltro.addEventListener("input", disegnaCapacita);

async function caricaCapacita() {
  if (capMsg) { capMsg.textContent = "caricamento..."; capMsg.className = "small dim"; }
  try {
    const r = await fetch("/api/capacita");
    const d = await r.json();
    if (!r.ok) {
      if (capMsg) { capMsg.textContent = d.error || ("errore " + r.status); capMsg.className = "small rosso"; }
      return;
    }
    capDati = { skill: d.skill || [], tool: d.tool || [] };
    disegnaCapacita();
    if (capMsg) {
      capMsg.textContent = `${capDati.skill.length} skill, ${capDati.tool.length} strumenti`;
      capMsg.className = "small dim";
    }
  } catch (e) {
    if (capMsg) { capMsg.textContent = "non raggiungibile: " + e; capMsg.className = "small rosso"; }
  }
}

function disegnaCapacita() {
  if (!capLista) return;
  const q = ((capFiltro && capFiltro.value) || "").toLowerCase().trim();
  const tutti = capDati[capTab] || [];
  const visti = q
    ? tutti.filter(x => (x.nome || "").toLowerCase().includes(q)
                   || (x.descrizione || "").toLowerCase().includes(q))
    : tutti;

  capLista.replaceChildren();
  if (!visti.length) {
    const p = document.createElement("p");
    p.className = "cap-vuoto";
    p.textContent = q ? "Nessun risultato per questo filtro." : "Non c'è niente da mostrare.";
    capLista.appendChild(p);
    return;
  }

  for (const x of visti) {
    const riga = document.createElement("div");
    riga.className = "cap-riga";

    const corpo = document.createElement("div");
    corpo.className = "cap-corpo";
    const nome = document.createElement("div");
    nome.className = "cap-nome";
    nome.textContent = x.nome || "(senza nome)";
    if (x.categoria) {
      const cat = document.createElement("span");
      cat.className = "cap-cat";
      cat.textContent = x.categoria;
      nome.appendChild(cat);
    }
    corpo.appendChild(nome);
    if (x.descrizione) {
      const desc = document.createElement("div");
      desc.className = "cap-desc";
      desc.textContent = x.descrizione;
      corpo.appendChild(desc);
    }
    riga.appendChild(corpo);

    // Solo le skill hanno una pagina da aprire: un tool è una funzione
    // che chiama l'agente, non un documento da leggere.
    if (capTab === "skill") {
      const apri = document.createElement("button");
      apri.className = "cap-apri";
      apri.textContent = "apri";
      apri.addEventListener("click", () => apriPaginaSkill(x.nome));
      riga.appendChild(apri);
    }

    capLista.appendChild(riga);
  }
}

// Dalla sidebar si apre la stessa pagina, non una seconda finestra.
const sideCap = $("side-cap");
if (sideCap) sideCap.addEventListener("click", () => apriCapacita());

// ------------------------------------------- sidebar: riduci, non chiudere
//
// La X chiudeva del tutto e si perdeva la larghezza scelta. Adesso si
// riduce a una striscia: riaprirla è un clic e la larghezza resta.

const MIN_LARGHEZZA = 180;
const MAX_LARGHEZZA = 520;
const LARGHEZZA_RIDOTTA = 60;

function larghezzaSide() {
  const w = parseInt(localStorage.getItem("orchestra.side.w") || "", 10);
  return (w >= MIN_LARGHEZZA && w <= MAX_LARGHEZZA) ? w : 268;
}

function riduciSide() {
  if (!sidebar) return;
  sidebar.style.width = LARGHEZZA_RIDOTTA + "px";
  sidebar.style.flexBasis = LARGHEZZA_RIDOTTA + "px";
  sidebar.classList.add("ridotta");
  localStorage.setItem("orchestra.side.ridotta", "1");
}

function allargaSide() {
  if (!sidebar) return;
  const w = larghezzaSide();
  sidebar.style.width = w + "px";
  sidebar.style.flexBasis = w + "px";
  sidebar.classList.remove("ridotta");
  localStorage.removeItem("orchestra.side.ridotta");
}

// Aperta all'avvio, sempre. La cronologia è il pezzo che dà senso a una
// conversazione che sopravvive al riavvio: nasconderla di default vuol
// dire aver costruito la persistenza e non farla vedere.
sidebar.removeAttribute("hidden");

// Il bottone alterna aperta/ridotta. Non chiude: la cronologia serve
// troppo spesso per costare due clic.
if (sideBtn) {
  sideBtn.addEventListener("click", () => {
    if (sidebar && sidebar.classList.contains("ridotta")) allargaSide();
    else riduciSide();
  });
}

// Trascinamento del bordo. La larghezza si salva: sceglierla a ogni
// avvio è il modo per non sceglierla mai.
(function attivaResize() {
  if (!sidebar) return;
  const maniglia = document.createElement("div");
  maniglia.className = "side-maniglia";
  maniglia.title = "Trascina per ridimensionare";
  sidebar.appendChild(maniglia);

  let partenza = 0, larghezzaPartenza = 0;

  maniglia.addEventListener("mousedown", (ev) => {
    partenza = ev.clientX;
    larghezzaPartenza = sidebar.getBoundingClientRect().width;
    document.body.classList.add("side-trascina");
    ev.preventDefault();
  });

  document.addEventListener("mousemove", (ev) => {
    if (!document.body.classList.contains("side-trascina")) return;
    const nuova = larghezzaPartenza + (ev.clientX - partenza);
    const limitata = Math.max(MIN_LARGHEZZA, Math.min(MAX_LARGHEZZA, nuova));
    sidebar.style.width = limitata + "px";
    sidebar.style.flexBasis = limitata + "px";
    sidebar.classList.remove("ridotta");
  });

  document.addEventListener("mouseup", () => {
    if (!document.body.classList.contains("side-trascina")) return;
    document.body.classList.remove("side-trascina");
    const w = Math.round(sidebar.getBoundingClientRect().width);
    localStorage.setItem("orchestra.side.w", String(w));
    localStorage.removeItem("orchestra.side.ridotta");
  });
})();

// All'avvio: la larghezza di prima, e ridotta se lo era.
(function ripristinaSide() {
  if (!sidebar) return;
  if (localStorage.getItem("orchestra.side.ridotta")) riduciSide();
  else allargaSide();
})();

// Caricamento all'avvio, in FONDO di proposito. Stava subito dopo la
// dichiarazione di `sidebar`, ma `caricaSide` tocca `sideSkill`,
// `sideElenco` e `sideMemElenco`, che sono `const` dichiarate più sotto:
// in temporal dead zone il riferimento lancia e le liste restano vuote
// — senza errori in console, perché la funzione è hoisted e sembra
// chiamabile.
if (sidebar && !sidebar.hasAttribute("hidden")) {
  caricaSide();
  caricaSideMemoria();
}

// --------------------------------------------- cercare nelle conversazioni
//
// Il campo sta SOTTO la lista: cercare sostituisce quello che c'era, e
// svuotandolo si torna alla lista. Non è una seconda lista.

const sideCerca = $("side-cerca");
let _cercaTimer = null;

async function sideRicerca() {
  if (!sideElenco) return;
  const q = (sideCerca.value || "").trim();
  try {
    const r = await fetch("/api/storico/cerca", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, limite: 30 }),
    });
    const d = await r.json();
    if (!r.ok) {
      if (sideMsg) { sideMsg.textContent = d.error || ("errore " + r.status); sideMsg.className = "small rosso side-msg"; }
      return;
    }
    sideElenco.replaceChildren();

    if (!q) {
      // lista normale
      caricaSideSessioni();
      return;
    }

    const trovati = d.risultati || [];
    if (!trovati.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.style.padding = "6px";
      li.textContent = "Nessuna conversazione trovata.";
      sideElenco.appendChild(li);
      return;
    }

    for (const x of trovati) {
      const li = document.createElement("li");
      li.className = "side-riga";

      const apri = document.createElement("button");
      apri.className = "side-apri";
      apri.title = x.titolo || "(senza titolo)";
      const testo = document.createElement("span");
      testo.className = "side-testo";
      testo.textContent = x.titolo || "(senza titolo)";
      const meta = document.createElement("span");
      meta.className = "side-meta";
      meta.textContent = x.ruolo;
      const framm = document.createElement("span");
      framm.className = "side-frammento";
      framm.textContent = x.frammento || "";
      apri.appendChild(testo);
      apri.appendChild(meta);
      apri.appendChild(framm);
      apri.addEventListener("click", async () => {
        // si apre la conversazione da cui viene il pezzo
        try {
          const rr = await fetch("/api/storico/apri", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: x.sessione_id }),
          });
          const rd = await rr.json();
          if (!rr.ok) {
            if (sideMsg) { sideMsg.textContent = rd.error || ("errore " + rr.status); sideMsg.className = "small rosso side-msg"; }
            return;
          }
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          if (sideCerca) { sideCerca.value = ""; }
          await caricaSideSessioni();
        } catch (e) {
          if (sideMsg) { sideMsg.textContent = "apertura fallita: " + e; sideMsg.className = "small rosso side-msg"; }
        }
      });
      li.appendChild(apri);
      sideElenco.appendChild(li);
    }
  } catch (e) {
    if (sideMsg) { sideMsg.textContent = "ricerca fallita: " + e; sideMsg.className = "small rosso side-msg"; }
  }
}

if (sideCerca) {
  sideCerca.addEventListener("input", () => {
    if (_cercaTimer) clearTimeout(_cercaTimer);
    _cercaTimer = setTimeout(sideRicerca, 250);
  });
  sideCerca.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      sideCerca.value = "";
      caricaSideSessioni();
    }
  });
}

// ------------------------------------------------- streaming del ragionamento

// Il nodo del ragionamento "vivo", cioè quello che sta accumulando adesso.
// Un nodo per ciclo di thinking: quando l'agente chiama un tool e poi
// ragiona ancora, NON deve riempire il blocco di prima (che resterebbe
// ancorato in cima, sotto il ragionamento iniziale), ma aprirne uno nuovo
// in fondo. Così il ragionamento segue la conversazione invece di
// accumularsi tutto in un punto fisso che i tool spingono su.
let ragionamentoCorrente = null;

function ragionamentoNodo() {
  let n = document.getElementById("ragionamento");
  if (!n) {
    n = document.createElement("div");
    n.id = "ragionamento";
    n.className = "ragionamento";
    n.setAttribute("hidden", "");
    log.appendChild(n);
  }
  return n;
}

function ragionamentoApri() {
  // Nodo nuovo, in fondo, a ogni ciclo: il precedente resta dov'è (e se
  // era aperto si chiude da sé perché non è più quello "corrente").
  // Così il ragionamento dopo un tool non si accoda a quello prima del
  // tool — che ormai è salito in cima — ma parte pulito sotto i tool.
  const n = document.createElement("div");
  n.className = "ragionamento";
  n.textContent = "";
  log.appendChild(n);
  ragionamentoCorrente = n;
  n.removeAttribute("hidden");
  scrollDown();
}

function ragionamentoAggiungi(testo) {
  const n = ragionamentoCorrente || ragionamentoApri();
  n.textContent += testo;
  scrollDown();
}

function ragionamentoChiudi() {
  // Non si cancella niente: il blocco resta visibile come storia. Si
  // stacca solo il puntatore, così il prossimo ragionamento apre un nodo
  // nuovo invece di riempire questo.
  ragionamentoCorrente = null;
  const n = document.getElementById("ragionamento");
  if (n) n.setAttribute("hidden", "");
}

;
(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("modelpick")<0)window.__diagFiles.push("modelpick");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"modelpick");}})();
// ------------------------------------------------ il selettore dei modelli
//
// Il <select> nativo non si vede e non si tocca: porta solo il value
// al server. Quello che si vede è un bottone che sembra un select, e il
// pannello che si apre sotto è questo.
//
// PERCHE' IL SELECT E' NASCOSTO, e non "coperto"
//
// La prima versione lo lasciava VISIBILE e apriva il pannello sopra.
// Non si vedeva niente, e non per un motivo di cache: al click il
// browser apre il SUO menu, disegnato dal sistema, e quel popup sta
// sempre sopra qualsiasi elemento della pagina. Il pannello era sotto,
// funzionante, e invisibile. Ctrl+F5 non lo avrebbe cambiato: non era
// un problema di caricamento.
//
// Nascosto con visually-hidden, non con display:none: display:none
// toglie l'elemento anche dal percorso di tabulazione, e il value che
// porta al server verrebbe da un campo che nessuno puo' raggiungere.

const mpWrap = document.querySelector(".mp-wrap");
const mpBtn = document.getElementById("model-btn");
const mpEtichetta = document.getElementById("model-label");
let mpPop = null;
let mpVoci = [];
let mpCursore = -1;
let mpAperto = false;

// L'etichetta segue il value. Va chiamata OVUNQUE il value cambia:
// senza, il bottone direbbe un modello mentre il select ne porta un
// altro, e la divergenza si vedrebbe solo alla prima risposta.
function mpSincronizzaEtichetta() {
  if (!mpEtichetta || !mpBtn) return;
  const id = modelPick.value;
  const op = id ? Array.from(modelPick.options).find((o) => o.value === id) : null;
  mpEtichetta.textContent = op ? (op.text || id) : "modello…";
  mpBtn.disabled = !!modelPick.disabled;
}

function mpChiudi() {
  if (mpPop) { mpPop.remove(); mpPop = null; }
  mpVoci = [];
  mpCursore = -1;
  mpAperto = false;
  if (mpBtn) mpBtn.setAttribute("aria-expanded", "false");
}

// `servizioTaceArrivato` dice se il servizio non dichiara il supporto
// tool. Va PASSATO, non letto da un altro file: il popup non ha un
// catalogo suo, e andare a prenderlo da core.js funziona solo finche'
// i file restano concatenati in quest'ordine. Il default e' false
// perche' il silenzio e' il caso normale: un servizio che non dice
// niente non deve interrompere il menu con un avviso che non serve.
function mpApri(servizioTaceArrivato) {
  const servizioNonDichiaraTool = servizioTaceArrivato === true;
  if (mpAperto || modelPick.disabled) return;
  mpAperto = true;
  if (mpBtn) mpBtn.setAttribute("aria-expanded", "true");

  mpPop = el("div", "mp-pop");
  const cerca = el("input", "mp-cerca");
  cerca.type = "search";
  cerca.placeholder = "cerca fra i modelli…";
  cerca.setAttribute("aria-label", "Cerca un modello");
  cerca.value = "";

  const lista = el("div", "mp-lista");
  mpVoci = [];
  const opzioni = Array.from(modelPick.options).filter((o) => o.value);
  const corrente = modelPick.value;

  for (const o of opzioni) {
    const nodo = el("div", "mp-voce");
    nodo.dataset.id = o.value;
    nodo.dataset.testo = (o.textContent || o.value).toLowerCase();
    if (o.value === corrente) nodo.classList.add("corrente");
    // Il badge dice DA DOVE viene il numero. Un numero senza
    // etichetta sembra parte del nome del modello, e su 400 righe
    // nessuno saprebbe di che cosa sia.
    const p = punteggioDiOpzione(o.value);
    const b = el("span", "mp-bench" + (p !== null ? " " + fasciaPunteggio(p) : ""),
                 p !== null ? String(p) : "—");
    b.title = (p !== null)
      ? "punteggio di benchmark: " + p + " su 100, misurato sui task di Orchestra"
      : "non misurato: nessun benchmark su questo modello";
    nodo.appendChild(b);
    nodo.appendChild(el("div", "mp-nome", o.text));
    nodo.appendChild(el("span", "mp-meta", metaDiOpzione(o.textContent || "")));
    lista.appendChild(nodo);
    mpVoci.push({ id: o.value, nodo });
  }

  const piede = el("div", "mp-piede");
    piede.textContent = opzioni.length +
      " modelli · il numero è il punteggio di benchmark (su 100) · «—» = non misurato";
    // Se il servizio non dichiara il supporto tool, si dice QUI, una
    // volta sola. Lo stesso ragionamento del menu: se il dubbio è
    // identico su ogni riga, non è un'informazione per riga — è
    // un'informazione sul servizio, e va detta una volta.
    if (servizioNonDichiaraTool) {
      piede.textContent += " · questo servizio non dichiara il supporto tool: "
        + "non lo sappiamo, e lo scopriamo dal benchmark";
    }

  mpPop.appendChild(cerca);
  mpPop.appendChild(lista);
  mpPop.appendChild(piede);
  mpWrap.appendChild(mpPop);

  // mp-wrap ha position:relative, quindi top:100% è il bordo
  // inferiore del bottone. Senza quella riga di CSS il riferimento
  // sarebbe la pagina, e il pannello comparirebbe nell'angolo in alto
  // a sinistra invece che sotto il bottone.
  mpPop.style.top = "100%";
  mpPop.style.left = "0";

  cerca.addEventListener("input", () => {
    const q = cerca.value.trim().toLowerCase();
    let visibili = 0;
    for (const v of mpVoci) {
      const ok = !q || v.nodo.dataset.testo.includes(q);
      v.nodo.style.display = ok ? "" : "none";
      if (ok) visibili++;
    }
    // La riga "nessun risultato" si crea e si toglie: tenerla sempre
    // nel DOM e spegnerla con display:none lascia un nodo morto nel
    // mezzo della lista, e un nodo morto in una lista filtrata e'
    // quello che rende strano il conteggio.
    let vuota = lista.querySelector(".mp-vuoto");
    if (visibili === 0) {
      if (!vuota) lista.appendChild(el("div", "mp-vuoto", "nessun modello con questo nome"));
    } else if (vuota) {
      vuota.remove();
    }
    mpCursore = -1;
  });

  cerca.addEventListener("keydown", (ev) => {
    const visibili = mpVisibili();
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      mpMuovi(1, visibili);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      mpMuovi(-1, visibili);
    } else if (ev.key === "Home") {
      ev.preventDefault();
      mpCursore = 0;
      mpEvidenzia(visibili);
    } else if (ev.key === "End") {
      ev.preventDefault();
      mpCursore = Math.max(0, visibili.length - 1);
      mpEvidenzia(visibili);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      const scelta = mpCursore >= 0 ? visibili[mpCursore] : null;
      if (scelta) mpScegli(scelta.id);
      else if (visibili.length) mpScegli(visibili[0].id);
    } else if (ev.key === "Escape") {
      // ESC chiude SENZA cambiare niente. Un menu che al primo
      // refuso cambia il modello in uso costa un turno di lavoro.
      ev.preventDefault();
      ev.stopPropagation();
      mpChiudi();
      if (mpBtn) mpBtn.focus();
    } else if (ev.key === "Tab") {
      mpChiudi();
    }
  });

  cerca.addEventListener("click", (ev) => ev.stopPropagation());
  lista.addEventListener("click", (ev) => {
    const voce = ev.target.closest(".mp-voce");
    if (voce) mpScegli(voce.dataset.id);
  });

  cerca.focus();
}

function mpVisibili() {
  return mpVoci.filter((v) => v.nodo.style.display !== "none");
}

function mpEvidenzia(visibili) {
  mpVoci.forEach((v) => v.nodo.classList.remove("cursore"));
  const n = visibili[mpCursore];
  if (n) {
    n.nodo.classList.add("cursore");
    n.nodo.scrollIntoView({ block: "nearest" });
  }
}

function mpMuovi(d, visibili) {
  if (!visibili.length) return;
  if (mpCursore < 0) mpCursore = d > 0 ? -1 : visibili.length;
  mpCursore = (mpCursore + d + visibili.length) % visibili.length;
  mpEvidenzia(visibili);
}

function mpScegli(id) {
  if (!id) return;
  // Il value E il change. Scrivere il value da solo non basterebbe:
  // nessuno riceverebbe la notifica, il select mostrerebbe un modello
  // e il backend continuerebbe a chiamarne un altro — la chat
  // risponderebbe col vecchio senza che nulla lo dica.
  modelPick.value = id;
  modelPick.dispatchEvent(new Event("change", { bubbles: true }));
  mpChiudi();
}

function punteggioDiOpzione(id) {
  const m = modelliPerId && modelliPerId[id];
  const t = m && m.punteggio_unico;
  if (t && typeof t.punteggio === "number") return Math.round(t.punteggio);
  return null;
}

function fasciaPunteggio(p) {
  if (p >= 80) return "buono";
  if (p >= 55) return "medio";
  return "";
}

function metaDiOpzione(testo) {
  const parti = String(testo).split("·").map((s) => s.trim()).filter(Boolean);
  return parti.slice(-1)[0] || "";
}

// Il bottone al posto del select.
on(mpBtn, "click", (ev) => {
  ev.stopPropagation();
  // `typeof servizioTace === "undefined"` invece di leggerlo e basta:
  // il bundle mette questo file DOPO core.js, ma un test puo' caricare
  // solo questo, e un ReferenceError qui significa che il menu non si
  // apre piu' — il difetto peggiore possibile per un selettore.
  const sa = (typeof servizioTace !== "undefined") ? servizioTace : false;
  if (mpAperto) mpChiudi(); else mpApri(sa);
});

// La tastiera sul bottone chiuso: giu'/Invio apre. Sul select nativo e'
// gratis; qui va rifatto, ed e' la ragione per cui il pannello non e'
// una scorciatoia.
on(mpBtn, "keydown", (ev) => {
  if (mpAperto) return;
  if (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    const sa = (typeof servizioTace !== "undefined") ? servizioTace : false;
    mpApri(sa);
  }
});

on(document, "click", (ev) => {
  if (mpAperto && mpPop && !mpPop.contains(ev.target)) mpChiudi();
});

on(document, "keydown", (ev) => {
  if (mpAperto && ev.key === "Escape") { mpChiudi(); if (mpBtn) mpBtn.focus(); }
});
;
(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("main")<0)window.__diagFiles.push("main");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"main");}})();
// ------------------------------------------------------------- azioni
async function send() {
  const text = input.value.trim();
  // Solo gli allegati caricati: uno rimasto "carico..." o con un
  // errore non ha un id, e mandarlo cosi' fa fallire l'invio con un
  // messaggio che parla di registro — che a te non dice niente.
  const daMando = allegatiInAttesa.filter((a) => !a.errore && a.id && !a.in_caricamento);
  const nonPronti = allegatiInAttesa.filter((a) => a.in_caricamento && !a.errore);
  if (nonPronti.length) {
    addText("error", "aspetta che l'allegato finisca di caricare");
    return;
  }
  // Solo allegati, senza testo: si manda lo stesso. Un file da solo e'
  // una domanda ("che c'e' in questa foto?") e non merita un blocco.
  if ((!text && !daMando.length) || busy || !ready) return;
  input.value = "";
  autoGrow();
  setBusy(true);
  try {
    const r = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // Gli allegati viaggiano con il messaggio, non da soli: li
      // manda chi preme Invio, e vengono svuotati solo se la richiesta
      // e' andata a buon fine. Se fallisce restano attaccati al
      // campo, perche' altrimenti perdi un file da 40.000 token
      // premendo due volte per errore.
      body: JSON.stringify({
              text,
              // Solo gli id: il file e' gia' al server, che lo ha validato
              // quando e' stato caricato.
              allegati: daMando.map((a) => a.id).filter(Boolean),
              scope: scopeAttivo || null,
              // Self-correzione: se il toggle ✓ e' attivo e c'e' un file da
              // controllare, si chiede al server di verificare il lavoro prima
              // di accettarlo. Lista vuota = nessuna verifica, come prima.
              verifica: verificaPayload(),
            }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      addText("error", err.error || `errore ${r.status}`);
      setBusy(false);
      // riattacca: il file non e' partito, e perderlo qui significa
      // doverlo cercare di nuovo
      return;
    }
    // il conto in token torna dal server, non e' stimato qui: il
    // server conosce le pagine del PDF e quante immagini sono, e una
    // stima fatta dal browser sarebbe una stima diversa dalla verita'
    try {
      const esito = await r.json();
      if (esito.allegati && esito.allegati.length) {
        const totale = esito.allegati.reduce((s, a) => s + (a.token || 0), 0);
        addText("info", `allegati: ${esito.allegati.length} · ~${totale.toLocaleString()} token`);
      }
    } catch (e) { /* la risposta non conta: il messaggio e' partito */ }
    allegatiInAttesa = [];
    disegnaAllegati();
  } catch (e) {
    addText("error", String(e));
    setBusy(false);
  }
}

async function cancel() {
  btnCancel.disabled = true;
  try { await fetch("/api/cancel", { method: "POST" }); } catch {}
}

async function reset() {
  try {
    const r = await fetch("/api/reset", { method: "POST" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      addText("error", err.error || `errore ${r.status}`);
    }
  } catch (e) { addText("error", String(e)); }
}

function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
}

// ---- Allegati: foto, PDF, testo
//
// I file si scelgono con la graffetta o con l'incolla (Ctrl+V), e si
// mandano INSIEME al messaggio successivo, non da soli.
//
// Il conto in token e' accanto al nome perche' e' la cosa che decide:
// 40.000 token e' una richiesta da trenta centesimi, 1.100 e' un
// centesimo. Vederlo solo dopo averlo gia' speso non serve.
//
// Il file non viene scritto su disco: va al server come data URL e
// basta. Un allegato da 12 MB in un file sul disco sopravvive alla
// sessione, occupa spazio per sempre, e finisce in qualche backup.
// Sul server non finisce niente: vive finche' la richiesta dura.
const btnAllega = $("btn-allega");
const fileInput = $("file-input");
const listaAllegati = $("allegati-lista");

let allegatiInAttesa = [];

// 12 MB, uguale al tetto del server. Qui si ferma PRIMA di leggere il
// file: un file da 40 MB letto in memoria e poi rifiutato e' una
// pagina bianca per un secondo, e il rifiuto non arriva.
const LIMITE_MB = 12;

function _leggiFile(file) {
  return new Promise((ok, ko) => {
    const lettore = new FileReader();
    lettore.onload = () => ok(lettore.result);
    lettore.onerror = () => ko(new Error("lettura fallita"));
    lettore.readAsDataURL(file);
  });
}

async function aggiungiFile( listaFile ) {
  if (!allegatiInAttesa.length && !busy) allegatiInAttesa = [];
  for (const file of listaFile) {
    if (file.size > LIMITE_MB * 1024 * 1024) {
      allegatiInAttesa.push({
        errore: file.name + ": " + Math.round(file.size / 1048576) +
                " MB, il limite e' " + LIMITE_MB,
      });
      disegnaAllegati();
      continue;
    }
    // La riga appare SUBITO, anche prima della risposta: unattesa
    // senza nulla che spieghi il perche' sembra una pagina rotta, e
    // l'utente prova a cliccare il pulsante che non c'e' ancora.
    const voce = { nome: file.name, in_caricamento: true, data_url: null };
    allegatiInAttesa.push(voce);
    disegnaAllegati();
    try {
      const data_url = await _leggiFile(file);
      voce.data_url = data_url;
      // Il file va al server QUI, una volta sola. Prima lo mandavo due
      // volte — una per il conto, una per l'invio — e un file da 12 MB
      // viaggiava 32: il secondo passaggio moriva e il browser
      // diceva "Failed to fetch", che sembra un problema di rete.
      const esito = await _manda_allega(file.name, data_url);
      if (!esito.ok) {
        voce.errore = file.name + ": " + esito.errore;
        disegnaAllegati();
        continue;
      }
      // id: quello che andra' a /api/send. Senza questo la riga
      // restava "carico..." per sempre: il flag non lo toglieva
      // nessuno, perche' non c'era nessuno a farlo.
      //
      // La risposta porta gli id come lista. Un file ne ha uno solo,
      // e mettere la lista intera nella voce faceva arrivare a
      // /api/send [["al-..."]] invece di ["al-..."]: una lista dentro
      // la lista, che il server respinge come "allegato non valido".
      // Sembrava funzionasse — la riga si riempiva, il conto c'era —
      // e falliva solo all'invio.
      const idArr = Array.isArray(esito.id) ? esito.id : [esito.id];
      voce.id = idArr[0] || null;
      voce.token_stimati = esito.token;
      voce.in_caricamento = false;
    } catch (e) {
      voce.errore = file.name + ": " + (e && e.message ? e.message : e);
      voce.in_caricamento = false;
    }
    disegnaAllegati();
  }
}

// Manda un file e ne restituisce id e costo. Gli errori arrivano come
// testo: qui il fallimento e' sempre leggibile, e un "Failed to
// fetch" qui significherebbe che la connessione e' caduta davvero.
async function _manda_allega(nome, data_url) {
  const r = await fetch("/api/allega", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: [{ nome, data_url }] }),
  });
  let d = {};
  try { d = await r.json(); } catch (e) { /* risposta non JSON */ }
  if (!r.ok) return { ok: false, errore: d.error || ("errore " + r.status) };
  return { ok: true, id: d.id, token: d.token, allegati: d.allegati };
}

function disegnaAllegati() {
  if (!listaAllegati) return;
  const utili = allegatiInAttesa.filter((a) => !a.errore);
  listaAllegati.replaceChildren();
  listaAllegati.hidden = !allegatiInAttesa.length;

  for (const [i, a] of allegatiInAttesa.entries()) {
    if (a.errore) {
      const e = el("div", "allegato-errore");
      e.textContent = a.errore;
      listaAllegati.appendChild(e);
      continue;
    }
    const riga = el("div", "allegato-riga");

    const icona = el("span", "allegato-icona");
    icona.textContent = a.in_caricamento ? "⏳"
      : (a.data_url || "").startsWith("data:image") ? "🖼"
      : (a.data_url || "").startsWith("data:application/pdf") ? "📄" : "📝";
    riga.appendChild(icona);

    // Il nome e' modificabile: il file che si chiama IMG_4821.jpg
    // finisce in contesto come "IMG_4821.jpg", e un modello risponde
    // meglio a "listino-prezzi-giugno.pdf" che a un nome di telefono.
    const nome = el("span", "allegato-nome");
    const campo = el("input");
    campo.type = "text";
    campo.value = a.nome;
    campo.title = "Cambia il nome che vedra' l'agente";
    on(campo, "input", (e) => { a.nome = e.target.value || "allegato"; });
    nome.appendChild(campo);
    riga.appendChild(nome);

    const costo = el("span", "allegato-costo");
    if (a.in_caricamento) {
      costo.textContent = "carico…";
    } else if (typeof a.token_stimati === "number") {
      costo.textContent = "~" + a.token_stimati.toLocaleString() + " token";
      // sopra 20.000 token la richiesta costa decine di centesimi:
      // si avvisa, non si vieta. Vietare sarebbe corretto e
      // inutile — il utente puo' sapere che costa e decidere.
      if (a.token_stimati > 20000) costo.className = "allegato-costo alto";
    }
    riga.appendChild(costo);

    const togli = el("button", "allegato-tomba", "×");
    togli.title = "Togli questo allegato";
    on(togli, "click", () => {
      allegatiInAttesa.splice(i, 1);
      disegnaAllegati();
    });
    riga.appendChild(togli);

    listaAllegati.appendChild(riga);
  }
  if (!utili.length && !allegatiInAttesa.some((a) => a.errore)) {
    listaAllegati.hidden = true;
  }
}

on(btnAllega, "click", () => { if (fileInput) fileInput.click(); });

on(fileInput, "change", async () => {
  const files = Array.from(fileInput.files || []);
  if (files.length) await aggiungiFile(files);
  fileInput.value = "";   // cosi' scegliere lo stesso file due volte funziona
});

// Incollare un'immagine dagli appunti e' il modo piu' naturale di
// darne una, molto piu' del "vai a cercarla". E' anche quello che
// su Windows e' gratis: il file e' gia' in memoria.
on(document, "paste", async (e) => {
  if (busy) return;
  const dt = e.clipboardData;
  if (!dt || !dt.files || !dt.files.length) return;
  const file = dt.files[0];
  // Solo immagini incollate: un file di testo incollato lo mette
  // gia' l'utente nel campo, e metterlo due volte e' peggio che
  // lasciarglielo scrivere.
  if (!file.type.startsWith("image/")) return;
  e.preventDefault();
  await aggiungiFile([file]);
});

on(input, "input", autoGrow);

// ------------------------------------------------- verifica del lavoro
// Toggle ✓ accanto alla graffetta. Quando è attivo, il prossimo invio
// chiede al server di verificare OGGETTIVAMENTE il risultato e, se non
// torna, rimandare il modello indietro col motivo. Mai un modello che
// giudica un modello: si controlla il file, il JSON, la somma.
let verificaAttiva = false;

function verificaPayload() {
  // Attivo solo con un file indicato: senza file non c'è niente da
  // controllare, e mandare una verifica vuota sarebbe rumore.
  if (!verificaAttiva) return [];
  const file = ($("verifica-file").value || "").trim();
  if (!file) return [];
  const tipo = $("verifica-tipo").value;
  const spec = { tipo, file };
  // I parametri extra dipendono dal tipo: senza, il server li ignora e
  // usa default ragionevoli, ma per "somma" e "contiene" servono.
  if (tipo === "testo_lungo") spec.minimo = 1;
  if (tipo === "testo_contiene") spec.frammenti = [];
  return [spec];
}

const btnVerifica = $("btn-verifica");
const verificaPop = $("verifica-pop");

function apriChiudiVerifica() {
  verificaPop.hidden = !verificaPop.hidden;
}

if (btnVerifica && verificaPop) {
  // Il toggle riflette SUBITO lo stato: il ✓ acceso dice "la prossima
  // verifica", spento dice "gira normale". Se non si accendesse, non si
  // saprebbe se è attivo finché non parte il turno.
  btnVerifica.addEventListener("click", () => {
    verificaAttiva = !verificaAttiva;
    btnVerifica.classList.toggle("acceso", verificaAttiva);
    apriChiudiVerifica();
    if (verificaAttiva && !($("verifica-file").value || "").trim()) {
      $("verifica-file").focus();
    }
  });
  // Cambiare tipo o file chiude il popover: la scelta è fatta, e
  // lasciarlo aperto copre il campo di scrittura.
  $("verifica-tipo").addEventListener("change", apriChiudiVerifica);
  $("verifica-file").addEventListener("change", apriChiudiVerifica);
}
on(input, "keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
btnSend.onclick = send;
if (btnAllega) btnAllega.disabled = !ready;
btnCancel.onclick = cancel;
btnReset.onclick = reset;

connect();
// Opzioni si caricano QUI, non solo quando apri il pannello. I
// selettori di servizio e di scopo vivono nell'header, e senza questa
// chiamata restano disabilitati fino a quando non apri Opzioni: si
// vedono, sembrano cliccabili, e non lo sono. Il pannello e' una vista
// degli stessi dati, non il posto dove vengono costruiti.
// Le categorie si chiedono al server, che le conta dai task veri.
// Prima le categorie, poi il resto: cosi' il riepilogo sotto i
// selettori sappia cosa e' misurabile prima di dire "non ancora
// misurato" — o "senza test".
caricaCategorie();
caricaOpzioni().catch(() => {
  // un errore qui non deve fermare il bootstrap: la chat resta viva,
  // e i selettori semplicemente restano disabilitati
});
fetch("/api/state").then(r => r.json()).then(s => {
  if (s.ready === false) { showBanner(s.error); return; }
  ready = true;
  showVersion(s.version);
  // setBusy applica `ready` ai controlli. Senza questa chiamata il
  // flag e' impostato ma nessuno lo guarda: il campo resta disabilitato
  // e la pagina sembra rotta. E' lo stesso buco dei selettori di
  // servizio e scopo — una variabile che cambia non abilita niente da
  // sola, serve qualcuno che la legga e agisca.
  setBusy(false);
  if (!log.children.length) handle("snapshot", s);
}).catch(() => { conn.textContent = "server non raggiungibile"; });

// La versione è il modo più economico per capire se stai guardando la
// pagina giusta. Senza, una UI in cache vecchia si manifesta come
// "funziona tutto tranne una cosa" e sembra un bug.
function showVersion(v) {
  $("ver").textContent = v || "?";
  $("ver").title = `interfaccia ${v || "?"} — se non corrisponde al server, ricarica`;
}

const OUT = { errori: [] };
(async function () {
  try {
    // 1) il pannello Opzioni viene riempito come all'avvio
    await disegnaProvider({ provider: "openrouter", chiavi: CHIAVI, motori: [] });
  } catch (e) { OUT.errori.push("disegnaProvider: " + e.message); }
})();

setTimeout(() => {
  const h = document.getElementById("provider-pick");
  const o = document.getElementById("opt-provider");
  OUT.header = { voci: h.options.map((x) => x.text), val: h.value, off: h.disabled };
  OUT.opzioni = { voci: o.options.map((x) => x.text), val: o.value, off: o.disabled };

  // 2) cambio servizio DAL MENU DELLA CHAT
  h.value = "groq";
  h.fire("change");
  setTimeout(() => {
    OUT.dopo = {
      header: h.value,
      opzioni: o.value,
      servizioBackend: globalThis.__servizioVisto || "",
      modelliChat: document.getElementById("model-pick").options.map((x) => x.text),
      nota: document.getElementById("provider-note").textContent,
    };
    console.log(JSON.stringify(OUT, null, 1));
  }, 300);
}, 300);

/* il fetch provider annota il servizio richiesto */
(function () {
  const f = globalThis.fetch;
  globalThis.fetch = async function (u, o) {
    if (String(u).startsWith("/api/provider") && o && o.body) {
      globalThis.__servizioVisto = JSON.parse(o.body).provider;
    }
    return f(u, o);
  };
})();
