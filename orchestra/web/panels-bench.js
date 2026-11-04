(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-bench")<0)window.__diagFiles.push("panels-bench");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-bench");}})();
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
  if (r.stopped_because) {
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
  caricaRouting();
}
function closeBench() {
  benchPanel.classList.add("hidden");
  if (benchTimer) { clearInterval(benchTimer); benchTimer = null; }
}
on($("bench-close"), "click", closeBench);
on($("opz-bench-apri"), "click", () => { chiudiOpzioni(); openBench(); });
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
