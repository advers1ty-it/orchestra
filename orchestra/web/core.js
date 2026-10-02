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
  if (!scope) return "";
  const s = m.scores || {};
  const v = s[scope];
  return (typeof v === "number") ? v.toFixed(2) : "—";
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

function scrollDown() {
  // solo se l'utente è già in fondo: scrollare mentre legge sopra è irritante
  const near = main.scrollHeight - main.scrollTop - main.clientHeight < 140;
  if (near) main.scrollTop = main.scrollHeight;
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
function addText(role, text) {
  const m = el("div", "msg " + role);
  m.appendChild(el("div", "role", role));
  m.appendChild(el("div", "body", text));
  log.appendChild(m);
  scrollDown();
  return m;
}

function addNote(text) {
  log.appendChild(el("div", "sysnote", text));
  scrollDown();
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
  scrollDown();
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
      (d.messages || []).forEach((m) => {
        // `m.content` puo' essere null o mancante: `.trim()` su undefined
        // solleva e blocca TUTTO il rendering della snapshot, lasciando la
        // chat vuota senza alcun errore in console. Difesa esplicita.
        const text = (m && m.content != null) ? String(m.content) : "";
        if (m.role === "user") addText("user", text);
        else if (m.role === "assistant" && text.trim()) addText("assistant", text);
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
      break;
    case "user_message":
      addText("user", d.text);
      break;
    case "assistant": {
      if (d.content) {
        addText("assistant", d.content);
      }
      (d.tool_calls || []).forEach((tc) => {
        // chiave basata sull'id del tool call: `tool_end` lo cerca cosi' e
        // abbinano anche due tool identici emessi nello stesso turno.
        addTool(tc.name, JSON.stringify(tc.args), tc.id || (tc.name + "|" + JSON.stringify(tc.args)));
      });
      break;
    }
    case "tool_end": {
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
      }
      break;
    }
    case "tool_error":
      addNote(`errore tool ${d.tool}: ${d.error}`);
      break;
    case "compaction":
      addNote(`contesto compattato: ${d.tokens_before} → ${d.tokens_after} token ` +
              `(potati ${d.tools_pruned} tool, fusi ${d.history_merged} turni)`);
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
    const sorted = (d.models || []).slice().sort((a, b) =>
      (a.free === b.free) ? a.id.localeCompare(b.id) : (a.free ? -1 : 1));
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
      const tc = m.tool_calling;
      const tool = tc === true ? "" : (tc === false ? "  [niente tool]" : "  [tool?]");
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
  if (!id || busy) return;
  modelPick.disabled = true;
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
  } catch (e) {
    addText("error", String(e));
  } finally {
    modelPick.disabled = false;
  }
});
