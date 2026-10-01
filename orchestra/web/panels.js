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
    return n ? { testo: n + "/" + CATEGORIE_TOTALE, cls: "quante",
                 titolo: "categorie misurate su " + CATEGORIE_TOTALE
                         + " — su Tutte non c'e' un punteggio unico" } : null;
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

function contaAvanzamento(log) {
  // una riga per run finito: "== modello ==" segna l'inizio, "  task:"
  // segna un risultato. Contiamo i risultati.
  const finiti = (log || []).filter((l) => /^\s{2}\S+:\s/.test(l)).length;
  const modelli = new Set((log || [])
    .filter((l) => /^== /.test(l))
    .map((l) => l.slice(3, -3)));
  if (attesaTotale) {
    const pct = Math.min(100, Math.round((finiti / attesaTotale) * 100));
    statoBench("in corso — " + modelli.size + " modelli · " +
               finiti + "/" + attesaTotale + " run · " + pct + "%", "on");
  } else {
    statoBench("in corso…", "on");
  }
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
        contaAvanzamento(d.log);
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

// Lo stesso gesto, nella chat. Il modello segue il servizio: e' quello
// che ti aspetteresti, e senza questa sincronizzazione scegli un
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
      // avrebbe usato davvero.
      await caricaModelli(d.provider || optProvider.value, null);
      optMsg.textContent = d.error || ("errore " + r.status);
      optMsg.className = "small rosso";
      return;
    }
    // Come sopra: il menu dice gia' quale modello e' attivo.
    optMsg.textContent = "";
    optMsg.className = "small verde";
    loadModels();
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
    caricaModelli(d.provider || optProvider.value, null);

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
