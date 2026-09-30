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
function punteggioDi(m, cat) {
  const s = m.scores || {};
  // su "tutte" non c'e' un punteggio unico: ci sono piu' categorie e
  // nessuna media ha senso (un 1.00 in codice e un 0.00 in ragionamento
  // non sono "0.50"). Mostriamo invece quante categorie sono state
  // misurate: dice se quel modello e' confrontabile o e' ancora sconosciuto.
  if (cat === "all" || !cat) {
    const n = Object.keys(s).length;
    return n ? { testo: n + "/" + CATEGORIE_TOTALE, cls: "quante" } : null;
  }
  const v = s[cat];
  return (typeof v === "number")
    ? { testo: v.toFixed(2), cls: v >= 0.99 ? "alto" : v > 0 ? "medio" : "basso" }
    : null;
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
benchPanel.addEventListener("click", (e) => { if (e.target === benchPanel) closeBench(); });

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
  benchTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/bench/status");
      const d = await r.json();
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
      clearInterval(benchTimer);
      benchTimer = null;
      statoBench("connessione persa: " + e, "ko");
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

function disegnaCategorieRouting() {
  if (!routingCat) return;
  const misurate = new Set();
  for (const m of tuttiModelli) {
    for (const c of Object.keys(m.scores || {})) misurate.add(c);
  }
  routingCat.replaceChildren();
  const ordine = ["js", "web", "app", "code", "reasoning", "instruction", "tool_use", "writing", "extraction"];
  for (const c of ordine) {
    if (!misurate.has(c)) continue;
    routingCat.appendChild(new Option(CAT_ETICHETTE[c] || c, c));
  }
  if (!routingCat.options.length) {
    routingCat.appendChild(new Option("nessuna categoria misurata", ""));
  }
  // un riassunto delle non misurate: e' l'invito a misurare
  const mancanti = ordine.filter((c) => !misurate.has(c));
  if (routingOut && mancanti.length) {
    routingOut.textContent = "non ancora misurato: " + mancanti.join(", ");
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
      if (!d || !d.totale) return;
      CATEGORIE_TOTALE = d.totale;
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
