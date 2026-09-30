(window.__diagFiles = window.__diagFiles || []); window.__diagFiles.push('core');

"use strict";

const $ = (id) => document.getElementById(id);
const log = $("log"), main = $("main"), input = $("input");
const btnSend = $("btn-send"), btnCancel = $("btn-cancel"), btnReset = $("btn-reset");
const dot = $("dot"), stats = $("stats"), conn = $("conn");
const modelPick = $("model-pick");

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
      const o = new Option(m.short + ctx_label(m.context) + " · " + price_label(m), m.id);
      modelPick.appendChild(o);
    }
    // il modello corrente: se non c'è tra le opzioni, aggiungilo, altrimenti
    // il <select> si apre su "modello…" e sembra non funzionare
    if (d.current && !sorted.some((m) => m.id === d.current)) {
      modelPick.appendChild(new Option(d.current, d.current));
    }
    modelPick.value = d.current || modelPick.options[0]?.value || "";
    modelPick.disabled = false;
  } catch (e) {
    modelPick.replaceChildren();
    modelPick.appendChild(new Option("modelli non disponibili", ""));
    modelPick.disabled = true;
  }
}

function ctx_label(context) {
  return context ? " " + Math.round(context / 1000) + "k" : "";
}
function price_label(m) {
  const p = Number(m.prompt_price);
  if (m.free || !isFinite(p) || p === 0) return "free";
  // i prezzi OpenRouter sono stringhe come "8e-07": senza Number diventano
  // NaN e toFixed() produce "NaN" nell'etichetta
  return "$" + p.toFixed(p < 0.01 ? 4 : 2) + "/1M";
}

modelPick.addEventListener("change", async () => {
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
