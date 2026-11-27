(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("core")<0)window.__diagFiles.push("core");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"core");}})();

"use strict";

const $ = (id) => document.getElementById(id);

// L'etichetta del progetto nella cronologia: prima di aprire una chat
// bisogna sapere in che cartella si continuera' a scrivere. "senza
// progetto" e' un'informazione, non un vuoto da nascondere.
function etichettaProgetto(nome) {
  const pulito = String(nome == null ? "" : nome).trim();
  return pulito ? "progetto: " + pulito : "senza progetto";
}

// Aggancio un handler senza mai esplodere.
const on = (el, evento, fn) => {
  // Se arriva una stringa, e' un id: si risolve.
  const bersaglio = typeof el === "string" ? $(el) : el;
  if (!bersaglio) {
    console.warn("elemento assente, handler '" + evento + "' non agganciato");
    return false;
  }
  if (typeof bersaglio.addEventListener !== "function") {
    console.warn("non e' un elemento, handler '" + evento + "' non agganciato:",
                 bersaglio);
    return false;
  }
  bersaglio.addEventListener(evento, fn);
  return true;
};

// Focus dei modali: entra all'apertura, torna al pulsante, Tab resta dentro.
const modaliFocus = [];
const FOCUSABILI_MODALE = [
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])", "textarea:not([disabled])",
  "[contenteditable=true]", "[tabindex]:not([tabindex='-1'])",
].join(",");

function elementoVisibile(el) {
  if (!el || el === document.body || el.disabled) return false;
  // Un elemento in una sezione chiusa non deve entrare nel giro del Tab.
  if (typeof el.getClientRects === "function" && el.getClientRects().length === 0) return false;
  for (let p = el; p; p = p.parentElement) {
    if (p.hidden) return false;
    if (typeof p.hasAttribute === "function" && p.hasAttribute("hidden")) return false;
    if (typeof p.getAttribute === "function" && p.getAttribute("aria-hidden") === "true") return false;
  }
  return true;
}

function focusabiliIn(root) {
  if (!root || typeof root.querySelectorAll !== "function") return [];
  return Array.from(root.querySelectorAll(FOCUSABILI_MODALE)).filter(elementoVisibile);
}

function apriFocusModale(root, opener) {
  if (!root) return;
  const attivo = opener && typeof opener.focus === "function" ? opener : document.activeElement;
  let voce = modaliFocus.find((v) => v.root === root);
  if (!voce) {
    voce = { root, opener: attivo && attivo !== document.body ? attivo : null };
    modaliFocus.push(voce);
  }
  if (typeof root.setAttribute === "function" &&
      !(typeof root.hasAttribute === "function" && root.hasAttribute("tabindex"))) {
    root.setAttribute("tabindex", "-1");
  }
  const primo = focusabiliIn(root)[0] || root;
  if (typeof primo.focus === "function") primo.focus();
}

function chiudiFocusModale(root) {
  const i = modaliFocus.map((v) => v.root).lastIndexOf(root);
  if (i < 0) return;
  const inCima = i === modaliFocus.length - 1;
  const voce = modaliFocus.splice(i, 1)[0];
  if (!inCima) return;
  const opener = voce.opener;
  const sotto = modaliFocus[modaliFocus.length - 1];
  const openerValido = elementoVisibile(opener) && typeof opener.focus === "function";
  // Se sotto c'e' un altro modale, il focus non torna fuori: torna dentro quello.
  if (sotto) {
    const dentroSotto = typeof sotto.root.contains === "function"
      ? sotto.root.contains(opener) : false;
    if (openerValido && dentroSotto) {
      opener.focus();
      return;
    }
    const primo = focusabiliIn(sotto.root)[0] || sotto.root;
    if (typeof primo.focus === "function") primo.focus();
    return;
  }
  if (openerValido) {
    opener.focus();
    return;
  }
  const fallback = ["input", "btn-opzioni", "btn-send"]
    .map((id) => $(id)).find(elementoVisibile);
  if (fallback && typeof fallback.focus === "function") fallback.focus();
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Tab" || !modaliFocus.length) return;
  const root = modaliFocus[modaliFocus.length - 1].root;
  if (!root || root.hidden || (root.classList && root.classList.contains("hidden"))) return;
  const focusabili = focusabiliIn(root);
  if (!focusabili.length) {
    e.preventDefault();
    if (typeof root.focus === "function") root.focus();
    return;
  }
  const attivo = document.activeElement;
  const i = focusabili.indexOf(attivo);
  if (i < 0) {
    e.preventDefault();
    focusabili[e.shiftKey ? focusabili.length - 1 : 0].focus();
    return;
  }
  if (e.shiftKey && i === 0) {
    e.preventDefault();
    focusabili[focusabili.length - 1].focus();
  } else if (!e.shiftKey && i === focusabili.length - 1) {
    e.preventDefault();
    focusabili[0].focus();
  }
});

// Anche un focus programmatico non deve finire dietro al modale aperto.
document.addEventListener("focusin", (e) => {
  if (!modaliFocus.length) return;
  const root = modaliFocus[modaliFocus.length - 1].root;
  if (!root || root.hidden || (root.classList && root.classList.contains("hidden"))) return;
  if (typeof root.contains === "function" && root.contains(e.target)) return;
  const primo = focusabiliIn(root)[0] || root;
  if (typeof primo.focus === "function") primo.focus();
});

const log = $("log"), main = $("main"), input = $("input");
const btnSend = $("btn-send");
const steerBar = $("steer-bar"), steerInput = $("steer-input"), steerSend = $("steer-send"), steerStop = $("steer-stop");
const dot = $("dot"), stats = $("stats"), conn = $("conn");
const modelPick = $("model-pick");
const reasoningPick = $("reasoning-pick");
// id -> modello.
let modelliPerId = {};
// Il servizio dichiara il tool-calling? Li' calcolato in
// loadModels, letto anche dal popup del selettore.
let servizioDichiaraTool = true;
let servizioTace = false;

// Lo scope attivo e' la categoria di lavoro scelta nell'header.
let scopeAttivo = "";

// Il punteggio che va mostrato nell'opzione.
function punteggioPerScope(m, scope) {
  const s = m.scores || {};
  // Con uno scope scelto: il numero vero di QUELLA categoria, e "—"
  // quando quel modello non e' stato misurato li'.
  if (scope) {
    const v = s[scope];
    return (typeof v === "number") ? v.toFixed(2) : "n/d";
  }
  // Senza scope: il numero unico, che confronta tutto il benchmark.
  const t = m.punteggio_unico;
  return (t && typeof t.punteggio === "number")
    ? String(Math.round(t.punteggio)) : "";
}

let busy = false;
let ready = false;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Legge una risposta come JSON, ma se il server manda HTML o testo (proxy, errore grezzo, porta occupata da altro)
// l'errore dice lo stato HTTP e l'inizio del corpo invece di un SyntaxError muto.
async function leggiJson(r) {
  const testo = await r.text();
  try { return JSON.parse(testo); }
  catch (e) {
    throw new Error("risposta non JSON (HTTP " + r.status + "): " + testo.slice(0, 120));
  }
}

function seiInFondo() {
  // Il predicato da solo, perché a `tool_end` serve sapere DOVE era l'utente quando il tool è partito, non dove sta
  // adesso che il risultato ha allungato il log di trecento righe.
  return main.scrollHeight - main.scrollTop - main.clientHeight < 140;
}

// Ultimo scroll impostato dal codice: distingue il nostro salto dal gesto utente.
let scrollVoluto = null;

// Salto in fondo che non passa da `seiInFondo()`: serve quando il log è stato
// appena svuotato o è cresciuto, e "sei in fondo adesso" direbbe no.
function vaiInFondo() {
  // Non scrollare se l'utente sta selezionando testo nella chat: lo
  // scroll forzato annulla la selezione e rende impossibile copiare.
  try {
    const sel = window.getSelection && window.getSelection();
    if (sel && sel.toString().trim() && main.contains(sel.anchorNode)) return;
  } catch (e) { /* ignora */ }
  main.scrollTop = main.scrollHeight;
  scrollVoluto = main.scrollTop;
}

// L'utente stava seguendo quando il turno è partito. Un tool da 200 righe fa
// scendere "in fondo" per qualche secondo: il flag ricorda l'intento.
let seguiTurno = false;
let primoSnapshot = true;
let ultimaFirmaSnapshot = "";
// La conversazione mostrata. La firma dei messaggi non basta: due chat possono
// avere stesso numero e stesso ultimo testo, quindi conta `sessione_id`.
let sessioneSnapshot = null;

function scrollDown() {
  // solo se l'utente è già in fondo: scrollare mentre legge sopra è irritante
  if (seiInFondo()) vaiInFondo();
}

// Segue lo sguardo: chi risale a leggere non viene riportato giu', chi torna in fondo riprende a seguire.
function intentoSegui(attivo) {
  seguiTurno = attivo;
  Array.from(log.children).forEach((n) => {
    if ("_segui" in n) n._segui = attivo;
  });
}

on(main, "scroll", () => {
  // Il salto fatto da noi non e' un gesto dell'utente: l'evento va consumato una volta sola.
  const nostro = main.scrollTop === scrollVoluto;
  scrollVoluto = null;
  if (nostro) return;
  intentoSegui(seiInFondo());
});

// Gli snapshot contengono solo la conversazione server-side: gli avvisi lato
// client restano dove sono, ricostruire la chat non li sposta in coda.
function raccogliNodiClient() {
  const nodi = [];
  let indice = 0;
  Array.from(log.children).forEach((n) => {
    const locale = n.classList && (
      n.classList.contains("sysnote") ||
      (n.classList.contains("msg") && (
        n.classList.contains("system") ||
        n.classList.contains("error") ||
        n.classList.contains("info")
      ))
    );
    if (locale) nodi.push({ nodo: n, indice });
    else indice += 1;
  });
  return nodi;
}

function ripristinaNodiClient(nodi) {
  const nodiSnapshot = Array.from(log.children);
  nodi.forEach(({ nodo, indice }) => {
    const riferimento = nodiSnapshot[Math.min(indice, nodiSnapshot.length)] || null;
    log.insertBefore(nodo, riferimento);
  });
}

// A turno finito il server propone mosse con il prompt gia' scritto.
let suggerimentiFatto = false;
let suggerimentiInCorso = false;
// Il modello scrive i consigli su misura DOPO la fine del turno: se non ha ancora finito il server risponde `in_corso`
// e si riprova fra poco.
let suggerimentiTimer = null;
let suggerimentiTentativi = 0;
const SUGGERIMENTI_RIPROVE = 10;
const SUGGERIMENTI_ATTESA = 3000;

function suggerimentiNascondi() {
  const box = $("suggerimenti");
  if (!box) return;
  box.innerHTML = "";
  box.hidden = true;
}

function suggerimentiMostra(lista) {
  const box = $("suggerimenti");
  if (!box) return;
  box.innerHTML = "";
  if (!Array.isArray(lista) || !lista.length) { box.hidden = true; return; }
  lista.forEach((p) => {
    if (!p || !p.prompt) return;
    const b = el("button", "suggerimento", p.titolo || "…");
    b.type = "button";
    // Il prompt intero nel tooltip: si vede cosa stai per mettere nel campo
    // prima di premerlo, senza doverlo prima premere.
    b.title = p.prompt;
    b.onclick = () => {
      // Se il campo ha gia' del testo non lo si butta: si accoda dopo una riga vuota.
      const gia = input.value.trim();
      input.value = gia ? gia + "\n\n" + p.prompt : p.prompt;
      if (typeof autoGrow === "function") autoGrow();
      input.focus();
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) {}
      // Premuto: non si torna a chiedere, e un aggiornamento in arrivo non
      // deve far riapparire i pulsanti sotto le dita.
      suggerimentiFatto = true;
      clearTimeout(suggerimentiTimer);
      suggerimentiNascondi();
    };
    box.appendChild(b);
  });
  box.hidden = false;
}

async function suggerimentiCarica() {
  // `suggerimentiFatto` e' la parte che evita la richiesta DOPPIA: se la
  // fine di questo turno e' gia' stata servita, non si torna al server.
  if (!ready || busy || suggerimentiFatto || suggerimentiInCorso) return;
  suggerimentiInCorso = true;
  try {
    const r = await fetch("/api/suggerimenti");
    if (!r.ok) { suggerimentiNascondi(); return; }
    const j = await r.json();
    // Nel frattempo puo' essere ripartito un turno: in quel caso i
    // pulsanti non servono piu' e coprirebbero la steer bar.
    if (busy) return;
    suggerimentiMostra(j.proposte || []);
    if (j.in_corso && suggerimentiTentativi < SUGGERIMENTI_RIPROVE) {
      // Il modello sta ancora scrivendo i consigli su misura: si riprova fra poco e si sostituiscono appena pronti.
      suggerimentiTentativi += 1;
      clearTimeout(suggerimentiTimer);
      suggerimentiTimer = setTimeout(suggerimentiCarica, SUGGERIMENTI_ATTESA);
    } else {
      suggerimentiFatto = true;
    }
  } catch (e) {
    suggerimentiNascondi();
  } finally {
    suggerimentiInCorso = false;
  }
}

function setBusy(v) {
  const eraOccupato = busy;
  busy = v;
  // Mentre l'agente lavora i pulsanti di fine turno non c'entrano niente:
  // sono la risposta al turno PRECEDENTE, e il turno nuovo avra' i suoi.
  if (v) {
    suggerimentiNascondi();
    suggerimentiFatto = false;
    suggerimentiTentativi = 0;
    clearTimeout(suggerimentiTimer);
  }
  // La fine del turno non arriva solo da `idle`: se il SSE è morto e la UI legge
  // /api/state, l'unico segnale è busy falso. Col SSE vivo lo fa `idle`, senza doppie richieste.
  if (!v && eraOccupato && pollingTimer) suggerimentiCarica();
  dot.className = "dot" + (v ? " busy" : " ok");
  input.disabled = !ready || v;
  btnSend.disabled = !ready || v;
  const micFloatEl = document.getElementById("mic-float");
  if (micFloatEl) micFloatEl.disabled = !ready || v;
  // Il pallino e' sempre li': verde a riposo, giallo mentre lavora.
  const chatForm = document.getElementById("chat-form");
  if (chatForm) chatForm.hidden = v;
  if (steerBar) steerBar.hidden = !v;
  if (steerStop) steerStop.disabled = !v;
  if (steerInput && v) steerInput.focus();
  // Il bottone del modello segue il select: senza, durante un turno resterebbe cliccabile mentre il select e'
  // disabilitato, e si potrebbe aprire un pannello su un catalogo che il server sta ricaricando.
  const mpB = document.getElementById("model-btn");
  if (mpB) mpB.disabled = v || modelPick.disabled;
  if (typeof mpSincronizzaEtichetta === "function") {
    mpSincronizzaEtichetta();
  }
}

function renderStats(s) {
  // Costruito col DOM, non con innerHTML: i valori vengono dal nostro server ma restare strutturalmente immuni evita di
  // doverlo ricordare ogni volta che qui compare un numero.
  const parts = [];
  if (s.iterations) parts.push([s.iterations, "iter"]);
  if (s.tool_calls) parts.push([s.tool_calls, "tool"]);
  if (s.tool_errors) parts.push([s.tool_errors, "err", true]);
  if (s.total_tokens) parts.push([s.total_tokens.toLocaleString(), "tok"]);
  if (s.compactions) parts.push([s.compactions, "comp"]);

  stats.textContent = "";
  if (!parts.length) { stats.textContent = "n/d"; return; }
  // Barra di riempimento del contesto: mostra quanto manca alla compattazione.
  const finestra = (typeof s.context_tokens === "number")
    ? s.context_tokens : (s.total_tokens || 0);
  if (s.context_limit && finestra) {
    const pct = Math.min(1, finestra / s.context_limit);
    const bar = el("span", "ctx-bar");
    const fill = el("i");
    fill.style.width = Math.round(pct * 100) + "%";
    fill.style.background = pct > 0.85 ? "var(--err)" :
                           pct > 0.70 ? "var(--warn)" : "var(--ok)";
    bar.appendChild(fill);
    stats.appendChild(bar);
  }
  // `sep`, non `dot`: `dot` e' il nome della variabile globale che setBusy usa per lo stato di occupazione.
  const sep = document.createTextNode(" · ");
  parts.forEach(([v, label, isErr], i) => {
    if (i) stats.appendChild(sep.cloneNode());
    const b = el("b", null, String(v));
    if (isErr) b.style.color = "var(--err)";
    stats.appendChild(b);
    stats.appendChild(document.createTextNode(" " + label));
  });
}

// Non esiste un "blocco turno": tutto appende direttamente a `log`, in ordine di arrivo.
function tieniRagionamentoInFondo() {
  if (typeof ragionamentoCorrente !== "undefined" && ragionamentoCorrente) {
    if (ragionamentoCorrente.parentNode === log) log.appendChild(ragionamentoCorrente);
  }
  scrollDown();
}

function addText(role, text, markdown) {
  const m = el("div", "msg " + role);
  m.setAttribute("data-role", role);
  // L'etichetta e' in italiano: "user" e "assistant" erano parole del
  // protocollo mostrate all'utente, non della sua lingua.
  const etichetta = role === "user" ? "tu"
    : role === "assistant" ? "orchestra" : role;
  m.appendChild(el("div", "role", etichetta));
  const corpo = el("div", "body");
  if (markdown) {
    // Il modello parla markdown: senza rendering si vedono gli asterischi crudi.
    // Solo i messaggi assistant: user e output dei tool restano testo, i loro `**` non diventano HTML.
    corpo.classList.add("md");
    corpo.innerHTML = renderMarkdown(text);
  } else {
    corpo.textContent = text;
  }
  m.appendChild(corpo);
  log.appendChild(m);
  scrollDown();
  return m;
}

// Markdown minimo per i messaggi del modello. Prima si scappa l'HTML (l'output
// non è fidato), poi si applica il markdown; il codice si estrae prima degli asterischi.
function renderMarkdown(text) {
  let h = String(text == null ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const pezzi = [];
  const accantona = (html) => "\u0000" + (pezzi.push(html) - 1) + "\u0000";
  h = h.replace(/```(\w*)\n?([\s\S]*?)(?:```|$)/g,
    (_, lang, cod) => accantona("blocco:" + "<pre><code>" + cod.replace(/\n$/, "") + "</code></pre>"));
  h = h.replace(/`[^`\n]+`/g,
    (m) => accantona("inline:" + "<code>" + m.slice(1, -1) + "</code>"));
  // I link prima, così http://... non diventa corsivo sugli slash. L'URL esclude
  // le virgolette: senza, un `"` chiuderebbe l'href e il resto diventerebbe un attributo.
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
  // Le tabelle: riga di intestazione con le pipe, riga di trattini, righe di
  // corpo. Senza questo ramo ogni riga finiva in un <p> e si vedevano i `|---|`
  // crudi: il CSS della tabella c'era gia', mancava chi la costruiva.
  // Una pipe vera dentro una cella si scrive `\|`: va protetta prima dello
  // split, altrimenti `x \| y` diventa due celle e la riga guadagna una colonna.
  // Il segnaposto e' un carattere di controllo che nel testo non compare.
  const celle = (r) => {
    const protetto = r.trim().replace(/\\\|/g, "\u0001");
    return protetto.replace(/^\|/, "").replace(/\|$/, "").split("|")
      .map((c) => c.trim().replace(/\u0001/g, "|"));
  };
  const eSeparatore = (r) => /\|/.test(r) && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(r);
  const allinea = (c) => /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : "";
  for (let i = 0; i < righe.length; i++) {
    const r = righe[i];
    let m;
    if (/\|/.test(r) && i + 1 < righe.length && eSeparatore(righe[i + 1])) {
      chiudiLista();
      const testa = celle(r);
      const posizioni = celle(righe[i + 1]).map(allinea);
      const att = (k) => posizioni[k] ? ' style="text-align:' + posizioni[k] + '"' : "";
      let html = "<table><thead><tr>";
      testa.forEach((c, k) => { html += "<th" + att(k) + ">" + c + "</th>"; });
      html += "</tr></thead><tbody>";
      i += 2;
      // Una riga di corpo deve somigliare all'intestazione: con i bordi
      // (`| a | b |`) si pretende il bordo, senza bordi (`a | b`) lo
      // stesso numero di celle. Senza questo, un paragrafo con una pipe
      // dopo la tabella veniva mangiato come riga di tabella.
      const conBordi = /^\s*\|/.test(r);
      const rigaDiTabella = (x) => {
        if (/^\s*$/.test(x)) return false;
        if (conBordi) return /^\s*\|/.test(x);
        return /\|/.test(x) && celle(x).length === testa.length;
      };
      while (i < righe.length && rigaDiTabella(righe[i])) {
        html += "<tr>";
        celle(righe[i]).forEach((c, k) => { html += "<td" + att(k) + ">" + c + "</td>"; });
        html += "</tr>";
        i += 1;
      }
      fuori.push(html + "</tbody></table>");
      i -= 1;
    } else if (/^\u0000\d+\u0000$/.test(r.trim()) && pezzi[+r.trim().slice(1, -1)].startsWith("blocco:")) {
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
  scrollDown();
}

// L'attesa: una riga sola che pulsa e sparisce quando arriva qualcosa.
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
  attesaGiro += 1;
  const i = Math.min(attesaGiro - 1, FRASI_ATTESA.length - 1);
  attesaNodo.textContent = FRASI_ATTESA[i];
  // Una sola riga che pulsa: un segnaposto per iterazione coprirebbe il lavoro.
  // Dopo 4 secondi il testo diventa esplicito, perché l'attesa non è più breve.
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

// Permessi: l'agente si è fermo e aspetta. Senza risposta il server nega
// dopo cinque minuti; chiudere la scheda non è un no.
const permessoBox = $("permesso");
let permessoAttivo = null;

function mostraPermesso(d) {
  permessoAttivo = d.id;
  $("permesso-percorso").textContent = d.percorso || "";
  $("permesso-dettaglio").textContent =
    "azione: " + (d.azione || "") + (d.dettaglio ? ", " + d.dettaglio : "");
  permessoBox.classList.remove("hidden");
  apriFocusModale(permessoBox);
  $("permesso-una").focus();
}

function nascondiPermesso() {
  permessoBox.classList.add("hidden");
  chiudiFocusModale(permessoBox);
  permessoAttivo = null;
}

async function rispondiPermesso(scelta) {
  if (!permessoAttivo) return;
  const id = permessoAttivo;
  // blocc subito: due clic non devono mandare due risposte, e la
  // seconda arriverebbe su una domanda gia' chiusa
  permessoAttivo = null;
  for (const b of ["permesso-una", "permesso-ses", "permesso-sempre", "permesso-mai"]) {
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
    for (const b of ["permesso-una", "permesso-ses", "permesso-sempre", "permesso-mai"]) {
      $(b).disabled = false;
    }
  }
}

on($("permesso-una"), "click", () => rispondiPermesso("una_volta"));
on($("permesso-ses"), "click", () => rispondiPermesso("sessione"));
  on($("permesso-sempre"), "click", () => rispondiPermesso("sempre"));
on($("permesso-mai"), "click", () => rispondiPermesso("mai"));

// Domande libere dell'agente (tool ask_user): Il tool e' fermo in un thread: la modale e' l'unico modo di farlo
// ripartire, quindi non si chiude con Escape e non si ignora.
let domandaAttiva = null;

function mostraDomanda(d) {
  domandaAttiva = d.id;
  // Un piano non e' una domanda: ha dei passi da leggere e una decisione da prendere.
  const ePiano = d.tipo === "piano";
  const titolo = $("domanda-titolo");
  if (titolo) titolo.textContent = ePiano ? "Piano proposto" : "L'agente chiede";
  const testo = $("domanda-testo");
  testo.textContent = d.testo || "";
  testo.classList.toggle("piano", ePiano);
  const opzioni = $("domanda-opzioni");
  opzioni.innerHTML = "";
  for (const o of d.opzioni || []) {
    const b = document.createElement("button");
    b.className = "ghost";
    b.textContent = o;
    b.addEventListener("click", () => {
      $("domanda-input").value = o;
      // Su un piano il clic E' la decisione: riempire il campo e aspettare un secondo clic trasforma "Approva" in due
      // passaggi, e il secondo si dimentica.
      if (ePiano) inviaRisposta();
      else $("domanda-input").focus();
    });
    opzioni.appendChild(b);
  }
  $("domanda-input").value = "";
  $("domanda").classList.remove("hidden");
  apriFocusModale($("domanda"));
  $("domanda-input").focus();
}

function nascondiDomanda() {
  $("domanda").classList.add("hidden");
  chiudiFocusModale($("domanda"));
  domandaAttiva = null;
}

async function inviaRisposta() {
  if (!domandaAttiva) return;
  const testo = $("domanda-input").value.trim();
  if (!testo) { $("domanda-input").focus(); return; }
  const id = domandaAttiva;
  // blocc subito: due Invio non devono mandare due risposte, e la
  // seconda troverebbe la domanda gia' chiusa
  domandaAttiva = null;
  $("domanda-invia").disabled = true;
  nascondiDomanda();
  try {
    const r = await fetch("/api/risposta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, testo }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      addText("error", err.error || `risposta non accettata (${r.status})`);
    } else {
      addNote(`risposta inviata: ${testo}`);
    }
  } catch (e) {
    addText("error", "risposta non arrivata: " + e);
  } finally {
    $("domanda-invia").disabled = false;
  }
}

on($("domanda-invia"), "click", inviaRisposta);
on($("domanda-input"), "keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); inviaRisposta(); }
});

// chiudere il pannello Opzioni mentre c'e' una domanda: la domanda
// resta, non e' un avviso che si nasconde


// Anteprime di un tool: immagini prodotte (per esempio immagine). Solo data URL:
// un URL esterno dentro un evento SSE non va caricato di nascosto.
function mostraAnteprime(out, immagini) {
  (immagini || []).forEach((src) => {
    if (typeof src !== "string" || !src.startsWith("data:image/")) return;
    const img = el("img", "tool-img");
    img.src = src;
    img.alt = "immagine generata";
    img.loading = "lazy";
    out.appendChild(img);
  });
}

function testoLogTool(valore) {
  return String(valore == null ? "" : valore).replace(/^errore:\s*/, "errore, ");
}

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
  // Salva la posizione attuale: dopo il tool il log e' cresciuto e "sei in fondo" direbbe no.
  const seguiva = seiInFondo();
  t._segui = seguiva;
  // Coerente col flag: se l'utente seguiva, il tool nuovo va in fondo; se era risalito a leggere, NON si scrolla —
  // chiamare `scrollDown` qui ignorava proprio l'intento appena registrato e strattonava chi stava leggendo sopra.
  if (seguiva) { scrollDown(); }
  return { root: t, status: st, out };
}

// SSE
let es = null;

// Polling di fallback: se il SSE non riceve eventi per 12s (tunnel lento, mobile sospeso, Cloudflare che bufferizza),
// il client ricarica lo snapshot da /api/state.
let ultimoEventoTs = Date.now();
let pollingTimer = null;

function avviaPollingFallback() {
  if (pollingTimer) return;
  pollingTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/state");
      if (!r.ok) return;
      const j = await r.json();
      // Applica lo snapshot solo se e' cambiato (evita flicker).
      const snap = j.snapshot || j;
      if (snap && snap.messages) {
        // Mentre il turno è in corso non ricostruire il DOM: evita flicker e salti.
        // Si aggiornano solo busy e stats; il sync completo arriva a fine turno.
        if (snap.busy) {
          setBusy(true);
          renderStats(snap);
          return;
        }
        const firma = String(snap.messages.length) + "::" +
          String(snap.messages.length ? (snap.messages[snap.messages.length-1].content || "") : "");
        // Anche qui il cambio conversazione va riconosciuto: due chat con la stessa firma hanno lo stesso numero di
        // messaggi, e senza questo confronto il polling (tunnel lento) restava sulla vecchia.
        const cambiaSessione = ("sessione_id" in snap) &&
          snap.sessione_id !== sessioneSnapshot;
        if ("sessione_id" in snap) sessioneSnapshot = snap.sessione_id;
        // Confronto grezzo: numero di messaggi (e firma).
        if (cambiaSessione || firma !== ultimaFirmaSnapshot) {
          const eraInFondoPrima = seiInFondo();
          const scrollTopPrima = main.scrollTop;
          // Ricostruisci la chat come fa lo snapshot del SSE.
          const nodiClient = raccogliNodiClient();
          log.innerHTML = "";
          if (typeof ragionamentoDimentica === "function") ragionamentoDimentica();
          const risultatiTool = {};
          (snap.messages || []).forEach((m) => {
            if (m && m.role === "tool" && m.tool_call_id) risultatiTool[m.tool_call_id] = m;
          });
          (snap.messages || []).forEach((m) => {
            const text = (m && m.content != null) ? String(m.content) : "";
            if (m.role === "user") addText("user", text);
            else if (m.role === "assistant") {
              // `if (m.reasoning)` lasciava passare i ragionamenti fatti di soli a capo: un blocco vuoto, identico a
              // una riga bianca.
              if ((m.reasoning || "").trim()) {
                const r = el("div", "ragionamento");
                r.textContent = m.reasoning;
                log.appendChild(r);
              }
              if (text.trim()) addText("assistant", text, true);
              (m.tool_calls || []).forEach((tc) => {
                const creato = addTool(tc.name, tc.arguments, tc.id);
                const ris = risultatiTool[tc.id];
                if (ris) {
                  const male = String(ris.content || "").startsWith("ERRORE");
                  const st = creato.root.querySelector(".tool-status");
                  st.className = "tool-status " + (male ? "err" : "ok");
                  st.textContent = male ? "errore" : "ok";
                  creato.root.querySelector(".tool-out").textContent = testoLogTool(ris.content);
                }
              });
            }
          });
          ripristinaNodiClient(nodiClient);
          ultimaFirmaSnapshot = firma;
          setBusy(!!snap.busy);
          // Conserva la posizione: se era in fondo segui, altrimenti ripristina lo scroll.
          // Su un'altra conversazione la posizione precedente non vale.
          if (cambiaSessione || eraInFondoPrima) vaiInFondo();
          else main.scrollTop = Math.min(scrollTopPrima, main.scrollHeight);
        }
      }
    } catch (e) { /* rete giu': riprova al prossimo giro */ }
  }, 5000);
}

function fermaPollingFallback() {
  if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null; }
}

let watchdogTimer = null;
function fermaWatchdog() {
  if (watchdogTimer) { clearTimeout(watchdogTimer); watchdogTimer = null; }
}
function avviaWatchdog() {
  fermaWatchdog();
  watchdogTimer = setTimeout(() => {
    // Se il SSE ha aperto la connessione ma non ha consegnato alcun evento (tipico del tunnel Cloudflare che
    // bufferizza/blocca lo stream), passiamo al polling di fallback su /api/state.
    if (Date.now() - ultimoEventoTs > 7000) avviaPollingFallback();
    else avviaWatchdog(); // riprova: magari sta solo tardando
  }, 8000);
}

function connect() {
  if (es) es.close();
  fermaPollingFallback();
  fermaWatchdog();
  ultimoEventoTs = Date.now();
  es = new EventSource("/api/stream");

  es.onopen = () => {
    conn.textContent = "connesso"; conn.style.color = "var(--ok)";
    fermaPollingFallback();
    // Avvia il watchdog: se in 8s non arriva nessun evento (tunnel
    // che bufferizza), cade sul polling.
    avviaWatchdog();
  };

  es.onerror = () => {
    conn.textContent = "riconnessione…";
    conn.style.color = "var(--warn)";
    fermaWatchdog();
    // Se il SSE non si riprende in 12s, avvia il polling di fallback.
    setTimeout(() => {
      if (es && es.readyState !== EventSource.OPEN) avviaPollingFallback();
    }, 12000);
  };

  es.onmessage = (e) => {
    ultimoEventoTs = Date.now();
    fermaPollingFallback();
    fermaWatchdog();
    avviaWatchdog(); // ri-arma il watchdog per il prossimo silenzio
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
      // Snapshot di un'altra chat: va ricostruito subito, o il clic cambia solo la riga.
      const cambiaSessione = ("sessione_id" in d) &&
        d.sessione_id !== sessioneSnapshot;
      if ("sessione_id" in d) sessioneSnapshot = d.sessione_id;
      // Durante un turno attivo non ricostruire il DOM: evita flicker e spostamenti del ragionamento.
      const eraPrimoSnapshot = primoSnapshot;
      if (primoSnapshot) {
        primoSnapshot = false;
      } else if (d.busy && !cambiaSessione) {
        setBusy(true);
        return;
      }
      const firma = String((d.messages || []).length) + "::" +
        String((d.messages && d.messages.length)
          ? (d.messages[d.messages.length - 1].content || "") : "");
      // Se lo snapshot non e' cambiato, non ricostruire: evita il refresh forzato che cancella la selezione del testo e
      // fa sparire i messaggi lato client (gateway, ragionamento).
      if (!cambiaSessione && firma === ultimaFirmaSnapshot) {
        setBusy(!!d.busy);
        // Il piano non entra nella firma (non e' un messaggio), quindi puo' cambiare mentre lo snapshot e' "identico":
        // senza questo, il toggle resterebbe indietro finche' non arriva un messaggio.
        if ("piano" in d && typeof aggiornaPiano === "function") {
          aggiornaPiano(!!d.piano);
        }
        return;
      }
      ultimaFirmaSnapshot = firma;
      primoSnapshot = false;
      const eraInFondoPrima = seiInFondo();
      const scrollTopPrima = main.scrollTop;
      // Se la chat ha già contenuto (turno in corso o finito), non ricostruisco il DOM dallo snapshot: i nodi di
      // sistema (errori, warning, steer, note) restano dove sono, non finiscono in fondo.
      if (log.children.length > 0 && !cambiaSessione) {
        setBusy(!!d.busy);
        if (eraInFondoPrima) scrollDown();
        else main.scrollTop = Math.min(scrollTopPrima, main.scrollHeight);
        break;
      }
      // Preserva i nodi lato client che non fanno parte dello snapshot.
      const nodiClient = raccogliNodiClient();
      // ricostruisci la conversazione
      log.innerHTML = "";
      if (typeof ragionamentoDimentica === "function") ragionamentoDimentica();
      // I risultati dei tool, indicizzati per id: le chiamate (dentro i messaggi assistant) arrivano prima dei
      // risultati (messaggi role="tool"), ma raccoglierli prima rende il rendering immune all'ordine.
      const risultatiTool = {};
      (d.messages || []).forEach((m) => {
        if (m && m.role === "tool" && m.tool_call_id) {
          risultatiTool[m.tool_call_id] = m;
        }
      });
      (d.messages || []).forEach((m) => {
        // `m.content` puo' essere null o mancante: `.trim()` su undefined solleva e blocca TUTTO il rendering della
        // snapshot, lasciando la chat vuota senza alcun errore in console.
        const text = (m && m.content != null) ? String(m.content) : "";
        if (m.role === "user") addText("user", text);
        else if (m.role === "assistant") {
          // Il ragionamento appartiene a questa risposta e va prima di essa.
          if ((m.reasoning || "").trim()) {
            const r = el("div", "ragionamento");
            r.textContent = m.reasoning;
            log.appendChild(r);
          }
          // Solo testo, niente riga bianca: un assistant con sole tool call non ha niente da dire, e il suo contenuto
          // sono i tool sotto.
          if (text.trim()) addText("assistant", text, true);
          (m.tool_calls || []).forEach((tc) => {
            const creato = addTool(tc.name, tc.arguments, tc.id);
            const ris = risultatiTool[tc.id];
            if (ris) {
              const male = String(ris.content || "").startsWith("ERRORE");
              const st = creato.root.querySelector(".tool-status");
              st.className = "tool-status " + (male ? "err" : "ok");
              st.textContent = male ? "errore" : "ok";
              creato.root.querySelector(".tool-out").textContent = testoLogTool(ris.content);
            }
          });
        }
      });
      // Ripristina gli avvisi locali vicino ai messaggi accanto a cui erano.
      ripristinaNodiClient(nodiClient);
      setBusy(!!d.busy);
      // Lo stato della modalita' piano vive sul server: se il toggle non lo segue, dopo un refresh dice il contrario di
      // quello che l'agente sta facendo.
      if ("piano" in d && typeof aggiornaPiano === "function") {
        aggiornaPiano(!!d.piano);
      }
      // Il primo snapshot inizializza la chat: mostra subito gli ultimi messaggi.
      if (eraPrimoSnapshot || cambiaSessione || eraInFondoPrima) vaiInFondo();
      else main.scrollTop = Math.min(scrollTopPrima, main.scrollHeight);
      break;
    }
    case "permission_request":
      // l'agente si e' fermo e aspetta. Va mostrato subito e per
      // primo: e' l'unico evento che blocca tutto il resto.
      mostraPermesso(d);
      break;
    case "domanda_utente":
      // anche questa ferma il turno, ma la risposta e' testo: modale
      // diversa, stesso blocco.
      mostraDomanda(d);
      break;
    case "piano":
      // Acceso o spento da un'altra scheda (o dalla CLI): il bottone
      // deve dirlo senza aspettare il prossimo snapshot.
      if (typeof aggiornaPiano === "function") aggiornaPiano(!!d.attivo);
      break;
    case "model_changed":
      // Il modello e' cambiato da solo (router o fallback): il bottone in alto deve dirlo, altrimenti mostra il vecchio
      // mentre il nuovo sta gia' lavorando.
      loadModels();
      addText("system", `modello → ${d.model || "?"} (automatico)`);
      break;
    case "turn_start":
      // Non crea nodi: il blocco finirebbe sopra il messaggio utente. Registra se
      // l'utente seguiva all'inizio, perché dopo un tool lungo "sei in fondo" direbbe no.
      seguiTurno = seiInFondo();
      suggerimentiNascondi();
      break;
    case "user_message":
      addText("user", d.text);
      break;
    case "thinking": {
      // Il tempo piu' lungo e piu' vuoto dello schermo era quello fra "invio" e "prima risposta": 40 secondi per un
      // modello che ragiona, e a schermo non succedeva niente.
      mostraAttesa();
      // Nuovo ciclo di thinking = il ragionamento di prima è finito.
      ragionamentoVisibile = false;
      ragionamentoChiudi();
      break;
    }
    case "ragionamento": {
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
      // `d.content` puo' essere fatto di soli spazi: con `if (d.content)` bastava quello per creare una bolla vuota.
      if ((d.content || "").trim()) {
        addText("assistant", d.content, true);
        // La risposta vera va in fondo SE l'utente stava seguendo il turno — non "se è in fondo adesso".
        if (seguiTurno) { seguiTurno = false; vaiInFondo(); }
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
      // abbiniamo per id, non "l'ultimo tool".
      const node = d.id ? log.querySelector('[data-key="' + CSS.escape(d.id) + '"]') : null;
      if (node) {
        const st = node.querySelector(".tool-status");
        st.className = "tool-status " + (d.ok ? "ok" : "err");
        st.textContent = d.ok ? "ok" : "errore";
        const out = node.querySelector(".tool-out");
        out.textContent = testoLogTool(d.result);
        mostraAnteprime(out, d.images);
        // Un'immagine dentro un riquadro chiuso non si vede: il tool card nasce chiuso, quindi un risultato visivo lo
        // apre da solo.
        if ((d.images || []).length) {
          node.classList.add("open");
          if (d.id) openTools.add(d.id);
        }
        // Il risultato ha allungato il log anche di centinaia di righe.
        if (node._segui) vaiInFondo();
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
    // La risposta e' stata tagliata dal tetto di output.
    case "troncato":
      if ((d.tentativo || 0) <= 2) {
        addNote(`risposta troncata dal limite di token (${d.motivo || "length"}): ` +
                `continuo dal punto in cui si era fermata.`);
      } else {
        addNote(`risposta ancora troncata dopo due riprese: chiudo col ` +
                `testo che c'e'. Alza il tetto di output o chiedi un ` +
                `lavoro piu' piccolo.`);
      }
      break;
    // Niente nota quando non c'e' nulla da potare: era rumore a ogni turno ("sotto soglia... sta lavorando") e si
    // confondeva con un vero avanzamento.

    case "gira_a_vuoto":
      addNote(`fermato: ripeteva \`${d.tool}\` con gli stessi argomenti, sempre lo stesso errore. ` +
              `Chiudo col lavoro fatto invece di girare a vuoto.`);
      break;
    case "tool_cache":
      addNote(`cache: \`${d.name}\` già calcolato, restituisco senza rifarlo`);
      break;

    // Instradamento e delega: le due cose che Orchestra fa da sola.
    case "routing": {
      const chi = d.modello ? `${d.categoria || "?"} → ${d.modello}` : "routing";
      const p = (d.punteggio !== null && d.punteggio !== undefined)
        ? ` (${Math.round(d.punteggio)}% su ${Math.round(d.prove || 0)} prove)` : "";
      addNote(`instradamento: ${chi}${p}, ${d.motivo || ""}`);
      break;
    }
    case "figlio": {
      // Il sub-agente lavora: mostro i suoi passi, annotati come "figlio".
      const t = d.tipo || "";
      if (t === "tool_start") {
        addNote(`figlio → ${d.name}`);
      } else if (t === "assistant" && d.content && d.content.trim()) {
        addNote(`figlio: ${d.content.trim().slice(0, 120)}`);
      }
      break;
    }
    case "delega": {
      // "scaduto" non è "errore": nella chat la differenza si vede,
      // perché il padre deve poter capire se rifare il compito o no.
      const esito = {risposto: "fatto", esaurito: "senza risposta",
                     scaduto: "tempo scaduto",
                     errore: "errore"}[d.esito] || d.esito;
      const quale = d.indice ? ` [${d.indice}/${d.totale || "?"}]` : "";
      addNote(`delega${quale} a un sub-agente (${d.modello || "senza modello"}, ` +
              `${d.passi || 0} passi): ${esito}: "${String(d.obiettivo || "").slice(0, 70)}"`);
      break;
    }
    case "progetto_cambiato": {
      // Il progetto non e' un'etichetta: e' la cartella in cui si scrive.
      const dove = d.percorso ? `, ${d.percorso}` : "";
      addNote(`progetto: ${d.progetto || "?"}${dove}`);
      // Il campo della sidebar mostra il progetto attivo: se non
      // viene aggiornato qui, resta quello vecchio e la UI mente.
      try {
        if (typeof caricaProgetto === "function") caricaProgetto();
        if (typeof caricaProgetti === "function") caricaProgetti();
      } catch (e) { /* la sidebar si aggiorna al prossimo giro */ }
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
      // Il reasoning, se ancora aperto, viene congelato: resta visibile
      // dove si trova, ma non insegue più il fondo ad ogni nuovo messaggio.
      ragionamentoCorrente = null;
      break;
    case "riepilogo":
      // La riga di fine turno: esito, durata, file, token, costo.
      addNote("fine turno · " + (d.riga || d.esito_testo || "fatto"));
      notificaTurno(d);
      break;
    // La risposta e' arrivata senza una parola di testo.
    case "risposta_vuota":
      addNote(d.chiuso
        ? "il modello ha chiuso senza scrivere niente: nessuna risposta da mostrare."
        : "risposta vuota: ho chiesto al modello di scriverla davvero.");
      break;
    case "error":
      addText("error", d.message);
      break;
    case "cancel_requested":
      addNote("annullamento richiesto, il turno in corso finirà");
      break;
    case "steer": {
      // Conferma che la guida e' stata ricevuta e verra' letta al prossimo tool.
      const _t = String(d.testo || "");
      const _anteprima = _t.length > 80 ? _t.slice(0, 80) + "…" : _t;
      addNote(`guida ricevuta (#${d.count || "?"}): «${_anteprima}»: letta al prossimo tool`);
      break;
    }
    case "reset":
      log.innerHTML = "";
      if (typeof ragionamentoDimentica === "function") ragionamentoDimentica();
      stats.textContent = "n/d";
      break;
    case "idle":
      setBusy(false);
      // E' qui e non su `riepilogo` perche' `idle` arriva sempre, anche quando il riepilogo non si e' potuto costruire:
      // un turno finito senza pulsanti lascerebbe l'utente senza la cosa piu' utile.
      suggerimentiCarica();
      // A fine turno arrivano i totali: la barra del contesto si
      // aggiorna qui, non solo al reload della pagina.
      if (typeof d.total_tokens === "number") renderStats(d);
      // Congela anche qui: se il turno finisce senza turn_end (es. cancellazione o errore gestito), il reasoning non
      // deve restare "corrente" e inseguire il fondo.
      ragionamentoCorrente = null;
      break;
  }
}

function notificaTurno(d) {
  // Solo se la scheda non e' visibile: una notifica di sistema mentre l'utente sta guardando la risposta e' un doppione
  // fastidioso, e il browser la mostra sopra la finestra che sta gia' mostrando la stessa cosa.
  try {
    if (!document.hidden) return;
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const n = new Notification("Orchestra: " + (d.esito_testo || "turno finito"), {
      body: d.riga || "",
      tag: "orchestra-turno",
      silent: false,
    });
    n.onclick = () => { try { window.focus(); n.close(); } catch (e) {} };
    setTimeout(() => { try { n.close(); } catch (e) {} }, 10000);
  } catch (e) { /* le notifiche sono un extra */ }
}

// Il permesso si chiede su un gesto dell'utente (l'invio), non a fine turno: un prompt di permesso che compare da solo
// dopo dieci minuti di lavoro viene negato per riflesso, e poi non si puo' piu' chiedere.
function chiediPermessoNotifiche() {
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") Notification.requestPermission();
  } catch (e) { /* niente notifiche, il resto funziona */ }
}

function showBanner(msg) {
  const b = el("div", "banner", msg);
  log.innerHTML = "";
  if (typeof ragionamentoDimentica === "function") ragionamentoDimentica();
  log.appendChild(b);
}

// selettore modello: si cambia senza riavviare il server; a metà turno il
// server risponde 409, perché la conversazione avrebbe due modelli.

async function loadModels() {
  try {
    const r = await fetch("/api/models");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    // svuota con replaceChildren, non textContent: su un <select> alcuni browser trattano textContent="" come "nessuna
    // opzione valida" e rifiutano di accettarne altre. replaceChildren è esplicito.
    modelPick.replaceChildren();
    // I gratuiti per primi: si provano senza pensarci. Il servizio dichiara il
    // tool-calling se almeno un modello lo dichiara.
    const _tutti = d.models || [];
    const _dichiarati = _tutti.filter(
      (m) => m.tool_calling !== null && m.tool_calling !== undefined).length;
    servizioDichiaraTool = _dichiarati > 0;
    // Se il servizio NON dichiara niente, il piede del menu lo dice una volta sola.
    servizioTace = _tutti.length > 0 && _dichiarati === 0;
    const sorted = _tutti.slice().sort((a, b) =>
      (a.free === b.free) ? a.id.localeCompare(b.id) : (a.free ? -1 : 1));
    // Indicizzati per id: il popup del selettore cerca il punteggio di una riga, e rileggere il testo dell'option per
    // ognuna significa cercare fra 400 elementi 400 volte.
    modelliPerId = {};
    for (const m of sorted) modelliPerId[m.id] = m;

    for (const m of sorted) {
      // new Option(...) invece di createElement("option"): costruisce un <option> vero, con value e testo impostati nel
      // modo giusto.
      const tc = m.tool_calling;
      const tool = tc === true ? ""
        : (tc === false ? "  [niente tool]" : (servizioDichiaraTool ? "  [tool?]" : ""));
      const punteggio = punteggioPerScope(m, scopeAttivo);
      // Il costo per 10k token va nell'opzione insieme al prezzo per milione.
      const o = new Option(
        m.short + tool + (punteggio ? "  " + punteggio : "") +
        ctx_label(m.context) + " · " + price_label(m) +
        costo_breve(m, 10000), m.id);
      modelPick.appendChild(o);
    }
    // il modello corrente: si mette in mezzo solo se esiste davvero nella lista.
    if (d.current && sorted.some((m) => m.id === d.current)) {
      modelPick.value = d.current;
    } else {
      const primo = sorted.find((m) => m.free) || sorted[0];
      modelPick.value = primo ? primo.id : "";
      if (d.current && primo && primo.id !== d.current) {
        // il modello in uso non esiste piu' su questo servizio: lo diciamo.
        const nota = $("provider-note");
        if (nota) {
          nota.textContent = "modello non disponibile su questo servizio, uso " + primo.id;
          nota.className = "provider-note rosso";
        }
      }
    }
    modelPick.disabled = false;
    mpSincronizzaEtichetta();
    // Con un bot attivo servizio e modello sono SUOI: i menu globali non devono poterli cambiare di nascosto.
    if (typeof aggiornaSelettoriBot === "function") aggiornaSelettoriBot();
    // le liste del pannello benchmark e della prova manuale usano lo stesso catalogo.
    if (typeof aggiornaCatalogoUI === "function") {
      // in un try separato: se il pannello benchmark non c'esso' — una pagina vecchia, un elemento rimosso, un test con
      // un DOM ridotto — la lista modelli deve restare comunque piena.
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
// I prezzi OpenRouter sono per TOKEN, non per milione. 5e-07 non e' "gratis con qualche cifra": e' $0.50 per un milione
// di token.
function price_label(m) {
  const p = Number(m.prompt_price);
  if (m.free || !isFinite(p) || p === 0) return "free";
  // -1 e' il prezzo di OpenRouter per "variabile": non e' gratis, e non e' nemmeno un numero.
  if (p < 0) return "prezzo variabile";
  const per_milione = p * 1_000_000;
  const cifre = per_milione < 0.01 ? 4 : (per_milione < 1 ? 3 : 2);
  return "$" + per_milione.toFixed(cifre) + "/1M";
}

// Quanto costa UNA richiesta, non quanto costa il milione.
function costo_stimato(m, token) {
  const p = Number(m.prompt_price);
  if (m.free || !isFinite(p) || p <= 0) return null;
  // p e' $/TOKEN.
  return p * (token || 0);
}

function costo_breve(m, token) {
  const c = costo_stimato(m, token);
  if (c === null) return "";
  // Le cifre seguono il numero, e non basta fermarsi a 4.
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
    // la conversazione continua, ma annotiamo il cambio: senza, domani non si sa che metà della chat l'ha scritta un
    // modello diverso.
    addText("system", d.routing === false ? `modello → ${id} (automatico spento)` : `modello → ${id}`);
    // Il limite di compattazione segue il modello (75% della sua finestra): senza ricaricare, la nota nelle Opzioni
    // mostra il valore vecchio e sembra che il cambio non faccia niente.
    if (typeof caricaOpzioni === "function") caricaOpzioni();
  } catch (e) {
    addText("error", String(e));
  } finally {
    modelPick.disabled = false;
    mpSincronizzaEtichetta();
  }
});
