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
  const n = ragionamentoNodo();
  n.textContent = "";
  n.removeAttribute("hidden");
  scrollDown();
}

function ragionamentoAggiungi(testo) {
  const n = ragionamentoNodo();
  n.textContent += testo;
  scrollDown();
}

function ragionamentoChiudi() {
  const n = document.getElementById("ragionamento");
  if (n) n.setAttribute("hidden", "");
}
