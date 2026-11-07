(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-opzioni")<0)window.__diagFiles.push("panels-opzioni");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-opzioni");}})();
// ------------------------------------------------------------- Opzioni
// Il pannello piu' sensibile dell'app: qui si scrivono le credenziali.
//
// Regola che governa tutto il file: il valore di una chiave gia'
// salvata non viene mai letto, e non viene neanche rimesso nel campo.
// Il campo parte vuoto ogni volta, e se lasci vuoto e salvi, la chiave
// viene cancellata. E' l'unico modo per essere onesto su cosa succede
// al file .env: se il campo e' vuoto, sparisce anche la chiave.
const opzioniPanel = $("opzioni");

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
const optToolProfile = $("opt-tool-profile");
const optMaxIters = $("opt-max-iters");
const optMaxMinuti = $("opt-max-minuti");
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
      // Il server tiene i secondi (e' quello che conta il loop), il
      // pannello ragiona in minuti: quindici minuti si leggono, 900
      // secondi si calcolano. Zero resta zero: "nessun limite".
      if (optMaxMinuti && typeof d.max_secondi_turno === "number") {
        const m = Math.round(d.max_secondi_turno / 60);
        optMaxMinuti.value = d.max_secondi_turno > 0 ? (m || 1) : 0;
        optMaxMinuti.disabled = false;
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
      // Lo stato VERO si rilegge dal server, non si indovina. Prima qui
      // si ridisegnava con `{ chiavi: [], provider: "" }` quando la
      // risposta non aveva `stato` — e il server non lo manda mai:
      // quel ramo era codice morto. Il risultato era due menu fermi su
      // valori vecchi e diversi fra loro (uno sul servizio fallito,
      // l'altro su quello di prima), piu' il messaggio d'errore
      // sovrascritto da "nessuna chiave API configurata" — che faceva
      // sembrare le chiavi sparite.
      await caricaOpzioni();
      // Dopo caricaOpzioni, che riscrive anche il messaggio: l'errore
      // va detto per ultimo, o non si vede.
      optMsg.textContent = testo;
      optMsg.className = "small rosso";
      if (nota) { nota.textContent = testo; nota.className = "small rosso"; }
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
      if (d.ready && (typeof ready !== "undefined" && !ready)) location.reload();
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
    if (d.ready && (typeof ready !== "undefined" && !ready)) location.reload();
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

on(optMaxMinuti, "change", async () => {
  const m = parseInt(optMaxMinuti.value, 10);
  if (!Number.isFinite(m) || m < 0) {
    await caricaOpzioni();
    return;
  }
  optMsg.textContent = "cambio tempo massimo…";
  try {
    const resp = await fetch("/api/tempo-turno", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_secondi_turno: m * 60 }),
    });
    const d = await resp.json();
    if (!resp.ok) {
      optMsg.textContent = d.error || ("errore " + resp.status);
      optMsg.className = "small rosso";
      await caricaOpzioni();
      return;
    }
    optMsg.textContent = m > 0
      ? `turno fermato dopo ${m} min`
      : "nessun limite di tempo";
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


// ------------------------------------------------------------------- memoria: modale
// La sidebar tiene solo "Tutti i fatti" + aggiunta rapida: sfoglia,
// cerca e correggi vivono qui dentro.
const memModal = $("mem-modal"), memLista = $("mem-lista"),
  memStat = $("mem-stat"), memMsg = $("mem-msg"),
  memCerca = $("mem-cerca"), memAnnullaCerca = $("mem-annulla-cerca");

function rigaMemoria(testo) {
  const r = el("div", "mem-item");
  const t = el("span", "txt");
  t.textContent = testo;
  const btns = el("span", "btns");
  const mod = el("button", "ghost piccolo", "✎");
  mod.title = "Correggi";
  const del = el("button", "ghost piccolo", "×");
  del.title = "Dimentica";
  on(mod, "click", () => {
    const inp = document.createElement("input");
    inp.value = testo;
    inp.style.flex = "1";
    inp.style.minWidth = "0";
    const ok = el("button", "ghost piccolo", "Salva");
    r.replaceChildren(inp, ok);
    inp.focus();
    inp.select();
    on(ok, "click", async () => {
      const nt = inp.value.trim();
      if (!nt || nt === testo) { ricaricaMemoria(); return; }
      await fetch("/api/memoria/modifica", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vecchio: testo, nuovo: nt }),
      });
      ricaricaMemoria();
    });
    on(inp, "keydown", (e) => { if (e.key === "Enter") ok.click(); });
  });
  on(del, "click", async () => {
    await fetch("/api/memoria/elimina", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fatto: testo }),
    });
    ricaricaMemoria();
  });
  btns.appendChild(mod);
  btns.appendChild(del);
  r.appendChild(t);
  r.appendChild(btns);
  return r;
}

function disegnaMemoria(fatti) {
  if (!memLista) return;
  memLista.replaceChildren();
  if (!fatti.length) {
    const p = el("div", "small dim");
    p.textContent = "Nessun fatto.";
    memLista.appendChild(p);
    return;
  }
  for (const f of fatti) memLista.appendChild(rigaMemoria(typeof f === "string" ? f : f.testo));
}

async function ricaricaMemoria() {
  if (memMsg) memMsg.textContent = "";
  try {
    const d = await (await fetch("/api/memoria")).json();
    if (d.errore) throw new Error(d.errore);
    disegnaMemoria(d.fatti || []);
    if (memStat) memStat.textContent = (d.n_fatti || 0) + " fatti";
  } catch (e) {
    if (memMsg) memMsg.textContent = "non raggiungibile: " + e;
  }
}

function apriMemoria() {
  if (!memModal) return;
  memModal.hidden = false;
  memModal.classList.add("show");
  if (memCerca) { memCerca.value = ""; memAnnullaCerca.hidden = true; }
  ricaricaMemoria();
}

function chiudiMemoria() {
  if (!memModal) return;
  memModal.hidden = true;
  memModal.classList.remove("show");
}

async function cercaMemoria() {
  if (!memCerca) return;
  const q = memCerca.value.trim();
  if (memAnnullaCerca) memAnnullaCerca.hidden = !q;
  if (!q) { ricaricaMemoria(); return; }
  try {
    const r = await fetch("/api/memoria/cerca", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, limite: 50 }),
    });
    const d = await r.json();
    disegnaMemoria((d.risultati || []).map((x) => x.testo));
    if (memStat) memStat.textContent = (d.risultati || []).length + " risultati";
  } catch (e) {
    if (memMsg) memMsg.textContent = "ricerca fallita: " + e;
  }
}

let memTimer = null;
on(memCerca, "input", () => {
  clearTimeout(memTimer);
  memTimer = setTimeout(cercaMemoria, 250);
});
on(memAnnullaCerca, "click", () => {
  if (memCerca) memCerca.value = "";
  if (memAnnullaCerca) memAnnullaCerca.hidden = true;
  ricaricaMemoria();
  if (memCerca) memCerca.focus();
});
on($("mem-trova"), "click", () => { if (memCerca) memCerca.focus(); });
on($("mem-chiudi"), "click", chiudiMemoria);
on($("side-mem-tutti"), "click", apriMemoria);
on($("side-mem-aggiungi"), "click", async () => {
  const inp = $("side-mem-input");
  const v = inp ? inp.value.trim() : "";
  if (!v) return;
  await fetch("/api/memoria/aggiungi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fatto: v }),
  });
  inp.value = "";
  if (memModal && !memModal.hidden) ricaricaMemoria();
});
on($("side-mem-input"), "keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); $("side-mem-aggiungi").click(); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && memModal && !memModal.hidden) chiudiMemoria();
});
