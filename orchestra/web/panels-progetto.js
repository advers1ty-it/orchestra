(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-progetto")<0)window.__diagFiles.push("panels-progetto");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-progetto");}})();
// ------------------------------------------------- goal, piani, scheduler, gate
//
// Il pannello goal era HTML morto: esisteva la barra ma nessuno la
// collegava alle API. Qui si collega tutto: creazione con piano/retry/
// criteri, lista con gate di accettazione visibile, scheduler manuale
// (Prossimo) e polling solo a pannello aperto.

const goalBar = $("goal-bar");
const goalInput = $("goal-input");
const goalProfile = $("goal-profile");
const goalKind = $("goal-kind");
const goalPriority = $("goal-priority");
const goalDepends = $("goal-depends");
const goalMaxIters = $("goal-maxiters");
const goalAttempts = $("goal-attempts");
const goalPartial = $("goal-partial");
const goalCriteri = $("goal-criteri");
const goalRecovery = $("goal-recovery");
const goalStatus = $("goal-status");
const goalOutput = $("goal-output");
const goalList = $("goal-list");
const goalPronti = $("goal-pronti");
let goalSelezionato = null;
let goalPoll = 0;

function goalJson(testo) {
  const t = (testo || "").trim();
  if (!t) return undefined;
  return JSON.parse(t);
}

// Il gate visivo: traduce stato+errore+output in un badge. La regola e'
// la stessa del backend (accettazione.py): done = gate ok, a meno che
// l'output dichiari un parziale accettato; failed con "accettazione
// fallita" = gate bocciato; il resto e' in attesa o fallito altrove.
function goalGate(g) {
  const stato = g.status || "";
  const err = g.error || "";
  const out = g.last_output || "";
  if (stato === "done") {
    if (out.indexOf("[parziale accettato:") === 0) {
      return { cls: "gate-parziale", testo: "gate: parziale" };
    }
    return { cls: "gate-ok", testo: "gate: ok" };
  }
  if (stato === "failed") {
    if (err.indexOf("accettazione fallita") === 0) {
      return { cls: "gate-ko", testo: "gate: bocciato" };
    }
    return { cls: "gate-attesa", testo: "fallito" };
  }
  if (stato === "cancelled") return { cls: "gate-attesa", testo: "cancellato" };
  return { cls: "gate-attesa", testo: "gate: in attesa" };
}

function goalRiga(g) {
  const riga = document.createElement("div");
  riga.className = "goal-row" + (goalSelezionato === g.id ? " sel" : "");
  const gate = goalGate(g);

  const id = document.createElement("span");
  id.className = "goal-id";
  id.textContent = String(g.id || "").slice(0, 8);
  id.title = g.id || "";
  riga.appendChild(id);

  const kind = document.createElement("span");
  kind.className = "goal-kind";
  kind.textContent = g.kind === "piano" ? "piano" : "goal";
  riga.appendChild(kind);

  const st = document.createElement("span");
  st.className = "goal-stato stato-" + (g.status || "pending");
  st.textContent = g.status || "?";
  riga.appendChild(st);

  const gb = document.createElement("span");
  gb.className = "goal-gate " + gate.cls;
  gb.textContent = gate.testo;
  gb.title = g.error || (g.last_output || "").slice(0, 300);
  riga.appendChild(gb);

  const meta = document.createElement("span");
  meta.className = "goal-meta";
  const dip = (g.depends_on || []).length
    ? " dip:" + (g.depends_on || []).map((d) => String(d).slice(0, 6)).join(",")
    : "";
  meta.textContent = "prio:" + (g.priority || 0)
    + " tent:" + (g.attempts || 0) + "/" + (g.max_attempts || 1) + dip;
  riga.appendChild(meta);

  const obj = document.createElement("span");
  obj.className = "goal-obj";
  obj.textContent = g.objective || "";
  obj.title = g.objective || "";
  riga.appendChild(obj);

  riga.addEventListener("click", () => {
    goalSelezionato = g.id;
    if (goalOutput) goalOutput.textContent = (g.last_output || "") + (g.error ? "\n[errore] " + g.error : "");
    caricaGoal();
  });
  return riga;
}

async function caricaGoal() {
  if (!goalBar || goalBar.hidden) return;
  try {
    const [rs, rr, sched] = await Promise.all([
      fetch("/api/goal/status").then((r) => r.json().catch(() => ({}))),
      fetch("/api/goal/ready").then((r) => r.json().catch(() => ({}))),
      fetch("/api/scheduler/status").then((r) => r.json().catch(() => ({}))),
    ]);
    const goals = rs.goals || [];
    if (goalPronti) {
      const n = (rr.pronti || []).length;
      goalPronti.textContent = n === 1 ? "1 goal pronto" : n + " goal pronti";
    }
    const schedBtn = $("goal-sched");
    const schedStat = $("goal-sched-stat");
    if (schedBtn) schedBtn.textContent = sched.running ? "Coda: on" : "Coda: off";
    if (schedStat) {
      schedStat.textContent = sched.running
        ? ("coda attiva · " + (sched.rounds || 0) + " esecuzioni"
           + (sched.last_id ? " · ultima: " + String(sched.last_id).slice(0, 8) + "/" + (sched.last_status || "") : ""))
        : "";
    }
    if (goalList) {
      goalList.replaceChildren();
      const attivi = goals.filter((g) => g.status === "running" || g.status === "pending");
      const chiusi = goals.filter((g) => g.status !== "running" && g.status !== "pending");
      for (const g of attivi.concat(chiusi).slice(0, 60)) {
        goalList.appendChild(goalRiga(g));
      }
      if (!goals.length) {
        const vuoto = document.createElement("div");
        vuoto.className = "goal-meta";
        vuoto.textContent = "Nessun goal. Scrivi un obiettivo e premi Avvia, oppure crea un piano.";
        goalList.appendChild(vuoto);
      }
    }
    // Polling solo se serve: c'e' almeno un goal in corsa e il pannello e' aperto.
    const serve = goals.some((g) => g.status === "running");
    if (goalStatus && !serve) goalStatus.textContent = "";
  } catch (e) {
    if (goalStatus) goalStatus.textContent = "goal non raggiungibili: " + e;
  }
}

function goalPolling() {
  if (goalPoll) return;
  goalPoll = setInterval(() => {
    if (goalBar && !goalBar.hidden) caricaGoal();
  }, 2000);
}

on("btn-goal", "click", () => {
  if (!goalBar) return;
  goalBar.hidden = !goalBar.hidden;
  if (!goalBar.hidden) {
    goalPolling();
    caricaGoal();
  }
});

on("goal-refresh", "click", () => caricaGoal());

on("goal-start", "click", async () => {
  const objective = (goalInput && goalInput.value || "").trim();
  if (!objective) {
    if (goalStatus) goalStatus.textContent = "scrivi prima l'obiettivo";
    return;
  }
  let criteri, recovery;
  try {
    criteri = goalJson(goalCriteri && goalCriteri.value);
    recovery = goalJson(goalRecovery && goalRecovery.value);
  } catch (e) {
    if (goalStatus) goalStatus.textContent = "JSON non valido: " + e.message;
    return;
  }
  const corpo = {
    objective: objective,
    profile: goalProfile && goalProfile.value || "auto",
    kind: goalKind && goalKind.value || "goal",
    max_iterations: parseInt(goalMaxIters && goalMaxIters.value || "60", 10),
    priority: parseInt(goalPriority && goalPriority.value || "0", 10),
    depends_on: (goalDepends && goalDepends.value || "").split(",").map((s) => s.trim()).filter(Boolean),
    max_attempts: parseInt(goalAttempts && goalAttempts.value || "1", 10),
    consenti_parziale: !!(goalPartial && goalPartial.checked),
    criteri: criteri,
    recovery: recovery,
  };
  if (goalStatus) goalStatus.textContent = "avvio...";
  try {
    const r = await fetch("/api/goal/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (goalStatus) goalStatus.textContent = d.error || ("errore " + r.status);
      return;
    }
    goalSelezionato = d.id;
    if (goalInput) goalInput.value = "";
    if (goalBar) { goalBar.hidden = false; }
    if (goalStatus) goalStatus.textContent = (corpo.kind === "piano" ? "piano creato: " : "avviato: ") + d.id + " — segui il progresso qui sotto";
    goalPolling();
    caricaGoal();
  } catch (e) {
    if (goalStatus) goalStatus.textContent = "errore: " + e;
  }
});

on("goal-run-next", "click", async () => {
  if (goalStatus) goalStatus.textContent = "scheduler...";
  try {
    const r = await fetch("/api/goal/run-next", { method: "POST" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) {
      if (goalStatus) goalStatus.textContent = d.error || ("errore " + r.status);
      return;
    }
    goalSelezionato = d.id;
    if (goalStatus) goalStatus.textContent = "scheduler ha avviato: " + d.id;
    caricaGoal();
  } catch (e) {
    if (goalStatus) goalStatus.textContent = "errore: " + e;
  }
});

on("goal-stop", "click", async () => {
  if (!goalSelezionato) {
    if (goalStatus) goalStatus.textContent = "seleziona prima un goal dalla lista";
    return;
  }
  try {
    await fetch("/api/goal/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: goalSelezionato }),
    });
    if (goalStatus) goalStatus.textContent = "stop inviato";
    caricaGoal();
  } catch (e) {
    if (goalStatus) goalStatus.textContent = "errore: " + e;
  }
});

on("goal-sched", "click", async () => {
  // La coda spende token veri: parte solo su pressione esplicita, e il
  // bottone dice sempre se e' on o off leggendo lo stato dal server.
  try {
    const st = await fetch("/api/scheduler/status").then((r) => r.json().catch(() => ({})));
    const rotta = st.running ? "/api/scheduler/stop" : "/api/scheduler/start";
    const r = await fetch(rotta, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval: 5 }),
    });
    const d = await r.json().catch(() => ({}));
    if (goalStatus) goalStatus.textContent = d.error || (st.running ? "coda fermata" : "coda avviata");
    caricaGoal();
  } catch (e) {
    if (goalStatus) goalStatus.textContent = "errore: " + e;
  }
});

// ------------------------------------------------------------- il progetto
//
// Il progetto dice su CHE COSA si sta lavorando, e DOVE. Non e' solo
// un'etichetta: e' la cartella in cui l'agente scrive, e il confine
// di sicurezza si sposta con lui.
//
// Il progetto attivo e' un menu a tendina: sceglierlo cambia subito
// il progetto, niente bottone. Un select non puo' sembrare una ricerca
// (era il difetto del vecchio input con "OK"), e l'azione e' immediata.
// L'opzione "nessun progetto" CANCELLA l'etichetta: si puo' lavorare
// senza progetto, e i fatti non vengono etichettati.
//
// Lo switch automatico (l'agente che riconosce il nome del progetto)
// arriva dall'evento "progetto_cambiato", che chiama caricaProgetto():
// qui il select viene aggiornato, cosi' resta coerente con quello che
// l'agente ha scelto da solo.
const progSelect = $("side-progetto-select");
const progFatti = $("side-progetto-fatti");

// Il valore del select: vuoto = nessun progetto.
function _progettoLabel() {
  if (!progSelect) return "";
  return (progSelect.value || "").trim();
}

async function caricaProgetto() {
  if (!progSelect) return;
  try {
    const r = await fetch("/api/progetto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return;
    const attivo = d.attivo || "";
    // Ricostruisce il menu: "nessun progetto" + i progetti registrati.
    // Solo se l'utente non sta scegliendo: altrimenti gli si cambia la
    // selezione sotto le dita, nel momento stesso in cui la sta toccando.
    if (document.activeElement !== progSelect) {
      progSelect.innerHTML = "";
      const vuoto = document.createElement("option");
      vuoto.value = "";
      vuoto.textContent = "nessun progetto";
      progSelect.appendChild(vuoto);
      (d.progetti || []).forEach((p) => {
        const o = document.createElement("option");
        o.value = p;
        o.textContent = p;
        progSelect.appendChild(o);
      });
    }
    // Mette la selezione sul progetto attivo. Se l'utente sta scegliendo,
    // il browser ha gia' il valore giusto: non lo sovrascrivo.
    if (document.activeElement !== progSelect) {
      progSelect.value = attivo;
    }
    if (progFatti) {
      if (attivo) {
        progFatti.textContent = d.n_fatti
          ? (d.n_fatti + (d.n_fatti === 1 ? " fatto" : " fatti") + " di «" + attivo + "»")
          : ("nessun fatto per «" + attivo + "»");
      } else {
        progFatti.textContent = "la memoria è condivisa: i fatti senza progetto valgono per tutti";
      }
    }
  } catch (e) {
    if (progFatti) progFatti.textContent = "non riesco a leggere i progetti";
  }
}

async function impostaProgetto() {
  if (!progSelect) return;
  const nome = _progettoLabel();
  if (progFatti) progFatti.textContent = "salvo...";
  try {
    const r = await fetch("/api/progetto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ progetto: nome }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (progFatti) progFatti.textContent = d.error || ("errore " + r.status);
      return;
    }
    await caricaProgetto();
  } catch (e) {
    if (progFatti) progFatti.textContent = "errore: " + e;
  }
}

// Scegliere nel menu cambia subito il progetto: niente bottone, e
// niente Invio. Il gesto e' la selezione stessa.
if (progSelect) {
  progSelect.addEventListener("change", impostaProgetto);
}

// ------------------------------------------------- la sezione Progetti
//
// I progetti registrati, con la cartella di ciascuno e quanti file
// hanno toccato. Registrare un progetto e' una cosa che fai una
// volta; aprire un progetto e' una cosa che fai ogni volta che
// inizi a lavorare. Per questo la sezione sta separata dal campo
// qui sopra.
// La sidebar tiene solo il menu a tendina del progetto attivo. Tutto il
// resto — la lista, la cancellazione, la nuova <
const progModal = $("progetti-modal"),
  progModalLista = $("progetti-modal-lista"),
  progModalNome = $("progetti-modal-nome"),
  progModalPercorso = $("progetti-modal-percorso"),
  progModalAlias = $("progetti-modal-alias"),
  progModalOk = $("progetti-modal-registra"),
  progModalFile = $("progetti-modal-file"),
  progGestisci = $("side-progetti-gestisci"),
  progChiudi = $("progetti-modal-chiudi"),
  progChiudi2 = $("progetti-modal-chiudi2");

async function caricaProgetti() {
  if (!progModalLista) return;
  try {
    const r = await fetch("/api/progetti");
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return;
    progModalLista.replaceChildren();
    const progetti = d.progetti || [];
    if (!progetti.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.textContent = "nessun progetto registrato";
      progModalLista.appendChild(li);
      return;
    }
    progetti.forEach((p) => {
      const li = document.createElement("li");
      if (p.attivo) li.classList.add("attivo");

      const riga = document.createElement("div");
      riga.className = "riga";
      const nome = document.createElement("span");
      nome.className = "nome";
      nome.textContent = p.nome;
      riga.appendChild(nome);

      // Il pulsante "apri" non c'e' piu': il menu a tendina in alto
      // sceglie il progetto attivo, e qui sarebbe ridondante. Restano
      // "file" (vedi i file toccati) e "×" (dimentica il progetto).

      const file = document.createElement("button");
      file.className = "ghost";
      file.textContent = "file";
      file.title = "I file toccati in questo progetto";
      file.addEventListener("click", () => caricaFileProgetto(p.nome));
      riga.appendChild(file);

      const via = document.createElement("button");
      via.className = "ghost";
      via.textContent = "×";
      via.title = "Dimentica questo progetto";
      via.addEventListener("click", async () => {
        try {
          await fetch("/api/progetti/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nome: p.nome }),
          });
          await caricaProgetti();
          await caricaProgetto();
        } catch (e) { /* la lista si ricarica comunque */ }
      });
      riga.appendChild(via);

      li.appendChild(riga);

      const perc = document.createElement("div");
      perc.className = "perc";
      perc.textContent = p.percorso || "";
      li.appendChild(perc);

      // Gli alias: gli altri nomi dello stesso progetto. Si vedono
      // perche' sono l'informazione che permette a Orchestra di
      // capire "let's work on the restaurant site" — e se l'utente
      // non li vede, non sa che quella frase funziona.
      const alias = p.alias || [];
      if (alias.length) {
        const al = document.createElement("div");
        al.className = "perc dim";
        al.textContent = "anche: " + alias.join(", ");
        li.appendChild(al);
      }

      const nf = document.createElement("div");
      nf.className = "n-file";
      const n = p.n_file || 0;
      nf.textContent = n + (n === 1 ? " file toccato" : " file toccati");
      li.appendChild(nf);

      progModalLista.appendChild(li);
    });
  } catch (e) {
    if (progModalLista) progModalLista.innerHTML = "";
  }
}

async function caricaFileProgetto(nome) {
  if (!progModalFile) return;
  try {
    const r = await fetch("/api/progetti/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ progetto: nome }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return;
    progModalFile.innerHTML = "";
    const file = d.file || [];
    if (!file.length) {
      const p = document.createElement("p");
      p.className = "small dim";
      p.textContent = "nessun file toccato in «" + nome + "»";
      progModalFile.appendChild(p);
      return;
    }
    file.forEach((f) => {
      const riga = document.createElement("div");
      riga.className = "riga";
      const path = document.createElement("span");
      path.textContent = f.path;
      const az = document.createElement("span");
      az.className = "azione";
      az.textContent = f.azione;
      riga.appendChild(path);
      riga.appendChild(az);
      progModalFile.appendChild(riga);
    });
  } catch (e) {
    if (progModalFile) progModalFile.textContent = "non riesco a leggere i file";
  }
}

if (progModalOk) {
  progModalOk.addEventListener("click", async () => {
    const nome = (progModalNome && progModalNome.value || "").trim();
    const percorso = (progModalPercorso && progModalPercorso.value || "").trim();
    // Gli alias: gli altri nomi dello stesso progetto. Vanno nel
    // body, e senza di loro il riconoscimento in un'altra lingua
    // non funziona — un progetto chiamato "Sito Ristorante" non
    // contiene la parola "restaurant".
    const alias = (progModalAlias && progModalAlias.value || "").trim();
    if (!nome || !percorso) {
      if (progFatti) progFatti.textContent = "serve il nome e la cartella";
      return;
    }
    try {
      const r = await fetch("/api/progetti/registra", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nome: nome, percorso: percorso, alias: alias }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (progFatti) progFatti.textContent = d.errore || ("errore " + r.status);
        return;
      }
      if (progModalNome) progModalNome.value = "";
      if (progModalPercorso) progModalPercorso.value = "";
      if (progModalAlias) progModalAlias.value = "";
      if (progSelect) progSelect.value = nome;
      await impostaProgetto();
      await caricaProgetti();
    } catch (e) {
      if (progFatti) progFatti.textContent = "errore: " + e;
    }
  });
}

// ── Modal progetti: apertura e chiusura ─────────────────────────
// Stesso pattern del modal memoria: overlay fissato sopra tutto,
// show/hide, Escape chiude. Il pulsante in testata della sidebar
// ("Gestione") e i due pulsanti interni fanno la stessa cosa.
function apriProgetti() {
  if (!progModal) return;
  progModal.hidden = false;
  caricaProgetti();
}
function chiudiProgetti() {
  if (!progModal) return;
  progModal.hidden = true;
}
on(progGestisci, "click", apriProgetti);
on(progChiudi, "click", chiudiProgetti);
on(progChiudi2, "click", chiudiProgetti);
if (progModal) {
  progModal.addEventListener("click", (e) => {
    if (e.target === progModal) chiudiProgetti();
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && progModal && !progModal.hidden) chiudiProgetti();
});

// Il primo caricamento. Lo script ha `defer`, quindi il DOM e' gia'
// pronto qui: non serve aspettare nessun evento.
//
// Senza questo il campo parte vuoto anche se un progetto e' attivo —
// e il peggio e' che sembra che non ce ne sia nessuno. Un progetto
// attivo che non si vede e' un progetto che non esiste.
caricaProgetto();
caricaProgetti();

// E la sidebar, che adesso puo' chiamare `caricaProgetti` senza
// cadere nella temporal dead zone: `progElenco` e gli altri `prog*`
// sono `const` dichiarate piu' sopra, e qui sono gia' inizializzate.
//
// Sta qui e non al suo posto naturale per la stessa ragione del
// commento che c'e' piu' in alto: la funzione e' hoisted, ma le
// variabili che tocca no. La lista dei progetti, infatti, si vedeva
// vuota e la console diceva "Cannot access 'progElenco' before
// initialization" — l'errore piu' rumoroso del gruppo, perche' la
// promessa rifiutata parte da una riga che sembra innocua.
if (sidebar && !sidebar.hasAttribute("hidden")) {
  caricaSide();
}
