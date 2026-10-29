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
const btnSend = $("btn-send");
const steerBar = $("steer-bar"), steerInput = $("steer-input"), steerSend = $("steer-send"), steerStop = $("steer-stop");
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

// Legge una risposta come JSON, ma se il server manda HTML o testo
// (proxy, errore grezzo, porta occupata da altro) l'errore dice lo
// stato HTTP e l'inizio del corpo invece di un SyntaxError muto.
async function leggiJson(r) {
  const testo = await r.text();
  try { return JSON.parse(testo); }
  catch (e) {
    throw new Error("risposta non JSON (HTTP " + r.status + "): " + testo.slice(0, 120));
  }
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
let primoSnapshot = true;
let ultimaFirmaSnapshot = "";

function scrollDown() {
  // Non scrollare se l'utente sta selezionando testo nella chat: lo
  // scroll forzato annulla la selezione e rende impossibile copiare.
  try {
    const sel = window.getSelection && window.getSelection();
    if (sel && sel.toString().trim() && main.contains(sel.anchorNode)) return;
  } catch (e) { /* ignora */ }
  // solo se l'utente è già in fondo: scrollare mentre legge sopra è irritante
  if (seiInFondo()) main.scrollTop = main.scrollHeight;
}

function setBusy(v) {
  busy = v;
  dot.className = "dot" + (v ? " busy" : " ok");
  input.disabled = !ready || v;
  btnSend.disabled = !ready || v;
  const micFloatEl = document.getElementById("mic-float");
  if (micFloatEl) micFloatEl.disabled = !ready || v;
  // Il pallino e' sempre li': verde a riposo, giallo mentre lavora.
  // Durante il lavoro il form chat viene sostituito dalla steer bar:
  // la stessa larghezza, la stessa posizione, niente scroll che
  // sposta il layout.
  const chatForm = document.getElementById("chat-form");
  if (chatForm) chatForm.hidden = v;
  if (steerBar) steerBar.hidden = !v;
  if (steerStop) steerStop.disabled = !v;
  if (steerInput && v) steerInput.focus();
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
  // Barra di riempimento del contesto: mostra quanto manca alla
  // compattazione. Il limite arriva dal server (non si calcola qui),
  // e il colore dice se siamo vicini al limite. Senza questa barra,
  // l'unica informazione è il numero di token — che si legge male
  // quando il contesto è quasi pieno.
  // La barra misura la FINESTRA (messaggi attuali), non il cumulato
  // del turno: il totale cresce per sempre e la resterebbe rossa e
  // piena anche a contesto vuoto. Se il server vecchio non manda
  // context_tokens, si ripiega sul totale come prima.
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

// chiudere il pannello Opzioni mentre c'e' una domanda: la domanda
// resta, non e' un avviso che si nasconde


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
  if (seguiva) { scrollDown(); }
  return { root: t, status: st, out };
}

// ---------------------------------------------------------------- SSE
let es = null;

// Polling di fallback: se il SSE non riceve eventi per 12s (tunnel
// lento, mobile sospeso, Cloudflare che bufferizza), il client ricarica
// lo snapshot da /api/state. Cosi' il telefono si sincronizza anche
// quando il flusso live e' morto — e' il caso del tunnel remoto.
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
        // Mentre il turno e' in corso non ricostruire il DOM: evita
        // flicker e salti di scroll. Si aggiorna solo busy/stats; il sync
        // completo avviene a fine turno (busy=false).
        if (snap.busy) {
          setBusy(true);
          renderStats(snap);
          return;
        }
        const firma = String(snap.messages.length) + "::" +
          String(snap.messages.length ? (snap.messages[snap.messages.length-1].content || "") : "");
        // Confronto grezzo: numero di messaggi (e firma).
        if (firma !== ultimaFirmaSnapshot) {
          const eraInFondoPrima = seiInFondo();
          const scrollTopPrima = main.scrollTop;
          // Ricostruisci la chat come fa lo snapshot del SSE.
          const nodiClient = Array.from(log.children).filter((n) => {
            if (!n.classList) return false;
            // Il ragionamento viene dallo snapshot (campo `reasoning`), non va
// preservato come nodo cliente: altrimenti la ricostruzione lo spinge
// sotto i messaggi e rompe l'ordine.
if (n.classList.contains("ragionamento")) return false;
            if (n.classList.contains("msg")) {
              return n.classList.contains("system") ||
                     n.classList.contains("error") ||
                     n.classList.contains("info");
            }
            return false;
          });
          log.innerHTML = "";
          const risultatiTool = {};
          (snap.messages || []).forEach((m) => {
            if (m && m.role === "tool" && m.tool_call_id) risultatiTool[m.tool_call_id] = m;
          });
          (snap.messages || []).forEach((m) => {
            const text = (m && m.content != null) ? String(m.content) : "";
            if (m.role === "user") addText("user", text);
            else if (m.role === "assistant") {
              if (m.reasoning) {
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
                  creato.root.querySelector(".tool-out").textContent = ris.content || "";
                }
              });
            }
          });
          nodiClient.forEach((n) => log.appendChild(n));
          ultimaFirmaSnapshot = firma;
          setBusy(!!snap.busy);
          // Conserva la posizione di lettura: se era in fondo, segui; altrimenti
          // ripristina lo scroll precedente (evita il salto in cima).
          if (eraInFondoPrima) scrollDown();
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
    // Se il SSE ha aperto la connessione ma non ha consegnato alcun
    // evento (tipico del tunnel Cloudflare che bufferizza/blocca lo
    // stream), passiamo al polling di fallback su /api/state.
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
      // Durante un turno attivo non ricostruire il DOM: evita flicker e
      // spostamenti del ragionamento. Il sync completo avviene a fine turno.
      const eraPrimoSnapshot = primoSnapshot;
      if (primoSnapshot) {
        primoSnapshot = false;
      } else if (d.busy) {
        setBusy(true);
        return;
      }
      const firma = String((d.messages || []).length) + "::" +
        String((d.messages && d.messages.length)
          ? (d.messages[d.messages.length - 1].content || "") : "");
      // Se lo snapshot non e' cambiato, non ricostruire: evita il refresh
      // forzato che cancella la selezione del testo e fa sparire i
      // messaggi lato client (gateway, ragionamento).
      if (!primoSnapshot && firma === ultimaFirmaSnapshot) {
        setBusy(!!d.busy);
        return;
      }
      ultimaFirmaSnapshot = firma;
      primoSnapshot = false;
      const eraInFondoPrima = seiInFondo();
      const scrollTopPrima = main.scrollTop;
      // Preserva i nodi lato client che non fanno parte dello snapshot.
      const nodiClient = Array.from(log.children).filter((n) => {
        if (!n.classList) return false;
        // Il ragionamento viene dallo snapshot (campo `reasoning`), non va
// preservato come nodo cliente: altrimenti la ricostruzione lo spinge
// sotto i messaggi e rompe l'ordine.
if (n.classList.contains("ragionamento")) return false;
        if (n.classList.contains("msg")) {
          return n.classList.contains("system") ||
                 n.classList.contains("error") ||
                 n.classList.contains("info");
        }
        return false;
      });
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
          // Il ragionamento appartiene a questa risposta e va prima di essa.
          if (m.reasoning) {
            const r = el("div", "ragionamento");
            r.textContent = m.reasoning;
            log.appendChild(r);
          }
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
      // Reinserisci i nodi lato client preservati (ragionamento, gateway).
      nodiClient.forEach((n) => log.appendChild(n));
      setBusy(!!d.busy);
      // Conserva la posizione di lettura: se era in fondo, segui; altrimenti
      // ripristina lo scroll precedente (evita il salto in cima).
      if (eraInFondoPrima) scrollDown();
      else main.scrollTop = Math.min(scrollTopPrima, main.scrollHeight);
      break;
    }
    case "permission_request":
      // l'agente si e' fermo e aspetta. Va mostrato subito e per
      // primo: e' l'unico evento che blocca tutto il resto.
      mostraPermesso(d);
      break;
    case "model_changed":
      // Il modello e' cambiato da solo (router o fallback): il bottone
      // in alto deve dirlo, altrimenti mostra il vecchio mentre il
      // nuovo sta gia' lavorando.
      loadModels();
      addText("system", `modello → ${d.model || "?"} (automatico)`);
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
        if (seguiTurno) { seguiTurno = false; scrollDown(); }
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
        if (node._segui) scrollDown();
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
    // Niente nota quando non c'e' nulla da potare: era rumore a ogni
    // turno ("sotto soglia... sta lavorando") e si confondeva con un
    // vero avanzamento. Solo la compattazione vera merita una riga.

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
    case "tool_cache":
      addNote(`cache: \`${d.name}\` già calcolato, restituisco senza rifarlo`);
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
    case "progetto_cambiato": {
      // Il progetto non e' un'etichetta: e' la cartella in cui si
      // scrive. Se cambia senza dirlo, l'utente crede di stare
      // lavorando da una parte e i file finiscono dall'altra — e il
      // danno e' nel suo progetto.
      //
      // Per questo il messaggio dice DOVE, non solo quale progetto:
      // la cartella e' la cosa che l'utente deve poter controllare.
      const dove = d.percorso ? ` — ${d.percorso}` : "";
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
    case "error":
      addText("error", d.message);
      break;
    case "cancel_requested":
      addNote("annullamento richiesto, il turno in corso finirà");
      break;
    case "steer": {
      // Conferma che la guida e' stata ricevuta e verra' letta al
      // prossimo tool. Senza questa riga il messaggio restava in coda
      // in silenzio e l'utente non sapeva se fosse arrivato.
      const _t = String(d.testo || "");
      const _anteprima = _t.length > 80 ? _t.slice(0, 80) + "…" : _t;
      addNote(`guida ricevuta (#${d.count || "?"}): «${_anteprima}» — letta al prossimo tool`);
      break;
    }
    case "reset":
      log.innerHTML = "";
      stats.textContent = "—";
      break;
    case "idle":
      setBusy(false);
      // A fine turno arrivano i totali: la barra del contesto si
      // aggiorna qui, non solo al reload della pagina.
      if (typeof d.total_tokens === "number") renderStats(d);
      // Congela anche qui: se il turno finisce senza turn_end (es.
      // cancellazione o errore gestito), il reasoning non deve restare
      // "corrente" e inseguire il fondo.
      ragionamentoCorrente = null;
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
    // si sa che metà della chat l'ha scritta un modello diverso.
    // La scelta manuale spegne l'automatico (vedi /api/model): lo si
    // scrive, o sembra che il menu non faccia niente al turno dopo.
    addText("system", d.routing === false ? `modello → ${id} (automatico spento)` : `modello → ${id}`);
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
