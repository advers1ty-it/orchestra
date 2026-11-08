(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-shell")<0)window.__diagFiles.push("panels-shell");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-shell");}})();
// --------------------------------------------------------- pannello laterale
//
// Flex-item del body, non overlay: la chat si restringe e resta leggibile.
// Un modale coprirebbe la conversazione proprio mentre la si sfoglia.

const sidebar = $("sidebar");
const sideElenco = $("side-elenco");
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
    if (window.innerWidth <= 640) document.body.classList.add("sidebar-aperta");
  } else {
    sidebar.setAttribute("hidden", "");
    document.body.classList.remove("sidebar-aperta");
  }
}

// All'avvio si carica, sempre: la sidebar è aperta di default, e senza
// questa chiamata la cronologia restava vuota fino al primo Ctrl+B.
// Il bottone dell'header chiama riduciSide(), che non carica — solo
// Ctrl+B passava da qui, ed è per questo che "la prima volta non c'è".
// La X non c'è più: il bottone RIDUCE a una striscia invece di chiudere.
// La cronologia serve troppo spesso per costare due clic.

// Rotaia delle sezioni: visibile solo a sidebar ridotta, un'icona per
// sezione. Il clic riapre e porta alla sezione.
for (const b of document.querySelectorAll("#side-rail button")) {
  b.addEventListener("click", () => {
    allargaSide();
    const t = $(b.dataset.sez);
    if (t && t.scrollIntoView) t.scrollIntoView({ block: "nearest" });
  });
}

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
  // Anche i progetti: la lista dei progetti registrati e' nella
  // sidebar, e deve essere aggiornata quando la sidebar si apre —
  // un progetto registrato in un'altra finestra non apparirebbe
  // altrimenti, e l'utente lo crederebbe perso.
  await Promise.all([caricaSideSessioni(), caricaSideTracce(),
                      caricaProgetti()]);
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

      // Elimina: mancava in sidebar, c'era solo nelle Opzioni. Chi vive
      // nella sidebar (ed è il pannello che si tiene aperto) non aveva
      // modo di cancellare una conversazione senza aprire le Opzioni.
      const del = document.createElement("button");
      del.className = "side-del";
      del.textContent = "\u2715";
      del.title = "Elimina questa conversazione";
      del.addEventListener("click", async () => {
        if (!confirm(`Eliminare "${(s.titolo || "(senza titolo)").slice(0, 40)}"? Non si recupera.`)) return;
        try {
          const r = await fetch("/api/storico/elimina", {
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
          if (sideMsg) { sideMsg.textContent = "eliminazione fallita: " + e; sideMsg.className = "small rosso side-msg"; }
        }
      });
      li.appendChild(del);

      sideElenco.appendChild(li);
    }
  } catch (e) {
    if (sideMsg) { sideMsg.textContent = "caricamento fallito: " + e; sideMsg.className = "small rosso side-msg"; }
  }
}

// La finestra che apriva una skill non c'e' piu': adesso "Apri" la mostra
// dentro al modale Capacita', con il testo e gli allegati. Una seconda
// finestra per una cosa che il modale sa gia' mostrare e' un modo per
// perdere il segno di dove si era.

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

//
// Modale, non pannello laterale: è un posto dove si VA a guardare e da
// cui si esce.
//
// Tre tab ma due sorgenti. Le skill hanno una vita propria — importa,
// accetta, scarta, cestina, rimetti — e il loro codice sta in
// panels-skill.js: qui si apre la porta, non si riscrive il pannello.
// Gli strumenti arrivano da /api/capacita e si leggono soltanto.
//
// Le skill stavano anche in Opzioni, con lo stesso elenco in un altro
// formato: qui una lista di nomi con un "apri" che apriva una finestra,
// là il pannello vero. Due elenchi della stessa cosa mentono appena
// divergono, quindi il pannello vero adesso è qui, accanto al cestino e
// alle proposte, e le Opzioni non ne parlano più.

const capacita = $("capacita");
const capLista = $("cap-lista");
const capFiltro = $("cap-filtro");
const capMsg = $("cap-msg");
let capTab = "skill";
let capTool = [];

function apriCapacita() {
  if (!capacita) return;
  capacita.classList.remove("hidden");
  mostraCapTab(capTab);
  // Le skill si rileggono a ogni apertura: l'agente propone una
  // procedura mentre il modale è chiuso, e una lista vecchia qui è
  // esattamente il punto in cui non si nota.
  if (typeof caricaSkill === "function") caricaSkill();
}

function chiudiCapacita() {
  if (capacita) capacita.classList.add("hidden");
}

// Una tab per volta, come le sezioni di Opzioni. Il caricamento segue
// la tab: gli strumenti si chiedono quando li guardi, non prima.
function mostraCapTab(t) {
  capTab = t;
  for (const u of ["skill", "cestino", "tool"]) {
    const sez = $("cap-sez-" + u);
    // hidden è l'attributo, non lo stile: è quello che il DOM dei test
    // rispetta, ed è quello che usa anche l'accessibilità.
    if (sez) {
      if (u === t) sez.removeAttribute("hidden");
      else sez.setAttribute("hidden", "");
    }
    const b = $("cap-tab-" + u);
    if (b) b.classList.toggle("attiva", u === t);
  }
  if (t === "tool") caricaStrumenti();
}

// Il bottone che apre Capacita' e' il "side-cap" nella sidebar, agganciato
// piu' in basso. Un secondo aggancio su un id che il markup non ha non
// e' innocuo: e' un bottone che non esiste, e il giorno in cui qualcuno
// rimette quell'id per sbaglio non si accorge che il bottone vero e' un
// altro.
const capClose = $("capacita-close");
if (capClose) capClose.addEventListener("click", chiudiCapacita);

for (const t of ["skill", "cestino", "tool"]) {
  const b = $("cap-tab-" + t);
  if (b) b.addEventListener("click", () => mostraCapTab(t));
}

if (capFiltro) capFiltro.addEventListener("input", disegnaStrumenti);

async function caricaStrumenti() {
  if (capMsg) { capMsg.textContent = "caricamento..."; capMsg.className = "small dim"; }
  try {
    const r = await fetch("/api/capacita");
    const d = await r.json();
    if (!r.ok) {
      if (capMsg) { capMsg.textContent = d.error || ("errore " + r.status); capMsg.className = "small rosso"; }
      return;
    }
    capTool = d.tool || [];
    disegnaStrumenti();
    if (capMsg) {
      capMsg.textContent = capTool.length === 1
        ? "1 strumento"
        : capTool.length + " strumenti";
      capMsg.className = "small dim";
    }
  } catch (e) {
    if (capMsg) { capMsg.textContent = "non raggiungibile: " + e; capMsg.className = "small rosso"; }
  }
}

function disegnaStrumenti() {
  if (!capLista) return;
  const q = ((capFiltro && capFiltro.value) || "").toLowerCase().trim();
  const visti = q
    ? capTool.filter(x => (x.nome || "").toLowerCase().includes(q)
                     || (x.descrizione || "").toLowerCase().includes(q))
    : capTool;

  capLista.replaceChildren();
  if (!visti.length) {
    const p = document.createElement("p");
    p.className = "cap-vuoto";
    p.textContent = q ? "Nessun risultato per questo filtro."
                      : "Non c'è niente da mostrare.";
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
    capLista.appendChild(riga);
  }
}

// Dalla sidebar si apre lo stesso modale, non una seconda finestra.
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

// Aperta all'avvio, sempre — ma solo su desktop. Su telefono la sidebar
// è un drawer: parte chiusa, si apre col pulsante hamburger.
if (window.innerWidth > 640) {
  sidebar.removeAttribute("hidden");
}

// Il bottone alterna aperta/ridotta. Non chiude: la cronologia serve
// troppo spesso per costare due clic.
if (sideBtn) {
  sideBtn.addEventListener("click", () => {
    if (window.innerWidth <= 640) {
      apriSide();
      return;
    }
    if (sidebar && sidebar.classList.contains("ridotta")) allargaSide();
    else riduciSide();
  });
}
// Chiusura del drawer mobile toccando il backdrop.
const sideBackdrop = $("side-backdrop");
if (sideBackdrop) {
  sideBackdrop.addEventListener("click", () => {
    if (window.innerWidth <= 640) apriSide(false);
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

// Il caricamento all'avvio e' in FONDO del file, non qui. Stava qui,
// subito dopo la dichiarazione di `sidebar`, ma `caricaSide` tocca
// anche `sideSkill`, `sideElenco` e i `prog*` dei progetti, che sono
// `const` dichiarate piu' sotto: in temporal dead zone il riferimento
// lancia e le liste restano vuote — senza errori in console, perche'
// la funzione e' hoisted e sembra chiamabile.
//
// La regola e' una sola: nessun `const` puo' essere letto prima della
// sua dichiarazione, e le dichiarazioni stanno in fondo. Per questo
// la chiamata sta in fondo anche lei.

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

// Il nodo del ragionamento "vivo", cioè quello che sta accumulando adesso.
// Un nodo per ciclo di thinking: quando l'agente chiama un tool e poi
// ragiona ancora, NON deve riempire il blocco di prima (che resterebbe
// ancorato in cima, sotto il ragionamento iniziale), ma aprirne uno nuovo
// in fondo. Così il ragionamento segue la conversazione invece di
// accumularsi tutto in un punto fisso che i tool spingono su.
let ragionamentoCorrente = null;

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
  // Nodo nuovo, in fondo, a ogni ciclo: il precedente resta dov'è (e se
  // era aperto si chiude da sé perché non è più quello "corrente").
  // Così il ragionamento dopo un tool non si accoda a quello prima del
  // tool — che ormai è salito in cima — ma parte pulito sotto i tool.
  const n = document.createElement("div");
  n.className = "ragionamento";
  n.textContent = "";
  log.appendChild(n);
  ragionamentoCorrente = n;
  n.removeAttribute("hidden");
  scrollDown();
}

function ragionamentoAggiungi(testo) {
  const n = ragionamentoCorrente || ragionamentoApri();
  n.textContent += testo;
  scrollDown();
}

function ragionamentoChiudi() {
  // Il blocco resta visibile come storia: si stacca solo il puntatore,
  // così il prossimo ragionamento apre un nodo nuovo. Non si nasconde.
  ragionamentoCorrente = null;
}

// ------------------------------------------------- onboarding guidato
// La prima volta si mostra un selettore di obiettivo: l'utente non deve
// conoscere i modelli, sceglie che lavoro fare e Orchestra configura
// scope/profilo/prompt iniziale.
const OBBIETTIVI = [
  { id: "code", t: "Programmare", d: "Fix bug, feature, refactor, test, review del codice.", scope: "code", profile: "base",
    prompt: "Analizza il progetto corrente e proponi un piano di lavoro conciso. Se c'e' un bug o una feature da fare, dimmi quale sarebbe il primo passo sensato." },
  { id: "web", t: "Sito web", d: "Landing, pagine, layout, CSS, accessibilita'.", scope: "web", profile: "base",
    prompt: "Aiutami a progettare o correggere un sito web. Chiedimi prima dettagli su obiettivo, contenuti e stile, poi proponi struttura e codice." },
  { id: "app", t: "App mobile", d: "Schermate, build Android/React Native, correzioni runtime.", scope: "app", profile: "base",
    prompt: "Aiutami con un'app mobile. Dimmi il framework e il problema, e analizza il codice rilevante prima di modificarlo." },
  { id: "dati", t: "Dati / analisi", d: "CSV, PDF, aggregazioni, outliner, report.", scope: "extraction", profile: "ricerca",
    prompt: "Ho dei dati da analizzare. Spiegami il formato e che domande devo fare, poi proponi i calcoli e il report." },
  { id: "docs", t: "Scrivere/documentare", d: "README, guide, changelog, note tecniche.", scope: "writing", profile: "base",
    prompt: "Aiutami a scrivere o migliorare la documentazione del progetto. Indica i file rilevanti e il pubblico target." },
  { id: "auto", t: "Automazione", d: "Script, batch, organizzazione file, pulizia.", scope: "code", profile: "base",
    prompt: "Voglio automatizzare un compito. Descrivilo, e proponi uno script sicuro e verificabile." },
  { id: "devops", t: "Test / CI / build", d: "Debug di build, pipeline, test, fallimenti.", scope: "code", profile: "base",
    prompt: "Un test o una build falliscono. Analizza gli errori e proponi una correzione minimale con verifica." },
  { id: "repo", t: "Capire un repository", d: "Architettura, punti critici, onboarding.", scope: "code", profile: "base",
    prompt: "Analizza questo repository e spiegami architettura, dipendenze e dove mettere mano. Non modificare nulla senza chiedermi conferma." },
  { id: "ricerca", t: "Ricerca / sintesi", d: "Documenti, siti, appunti, comparazioni.", scope: "reasoning", profile: "ricerca",
    prompt: "Aiutami a fare ricerca e sintesi. Indica fonti e produced un sunto strutturato con fonti." },
  { id: "piano", t: "Pianificare un lavoro", d: "Breakdown, checklist, milestone.", scope: "", profile: "base",
    prompt: "Scomponi un obiettivo in passi verificabili. Dimmi quali file o artefatti verranno toccati e come verifico il risultato." },
  { id: "debug", t: "Debug / crash", d: "Traceback, stack trace, logs, regressioni.", scope: "code", profile: "base",
    prompt: "Ho un errore o un crash. Analizza traceback/logs, trova la causa e proponi la minima correzione con test." },
  { id: "backend", t: "API / backend", d: "Endpoint, database, auth, modelli, validazione.", scope: "code", profile: "base",
    prompt: "Aiutami a progettare o correggere un backend/API. Prima discuti risorse, payload, auth e database, poi implementa step by step." },
  { id: "ui", t: "Interfaccia frontend", d: "Componenti, stato, stile, accessibilita'.", scope: "web", profile: "base",
    prompt: "Aiutami con l'interfaccia frontend. Indica framework/stile desiderato; proponi componenti e verifica accessibilita'." },
  { id: "db", t: "Database / SQL", d: "Schema, migration, query, indici.", scope: "code", profile: "base",
    prompt: "Aiutami con database e SQL. Analizza schema, query e migrare in sicurezza; proponi indici e test." },
  { id: "perf", t: "Performance", d: "Profiling, miglioramenti, regressioni.", scope: "code", profile: "base",
    prompt: "Migliora le performance del codice o di una query. Misura prima, poi proponi la minima ottimizzazione verificata." },
  { id: "git", t: "Git / collaborazione", d: "Branch, commit, PR, review.", scope: "code", profile: "base",
    prompt: "Aiutami con git e collaborazione: branch, commit, PR, review, risoluzione conflitti." },
  { id: "security", t: "Security review", d: "Validazione input, segreti, auth, superficie attacco.", scope: "code", profile: "base",
    prompt: "Fai una security review del codice indicato. Trova vulnerabilita', impatto e correzioni minime." },
  { id: "design", t: "Design / UX", d: "Wireframe, tono visivo, flussi.", scope: "web", profile: "base",
    prompt: "Aiutami a progettare UX/UI. Definisci obiettivo, utente, flusso, poi variante visiva." },
  { id: "lead", t: "Scrivere un README", d: "Onboarding dev e documentazione utile.", scope: "writing", profile: "base",
    prompt: "Scrivi o ristruttura il README per utenti / contributori. Indica prerequisiti e comandi." },
  { id: "json", t: "JSON / config", d: "API payloads, configurazioni, manifest.", scope: "code", profile: "base",
    prompt: "Aiutami a modelizzare JSON/configurazioni. Valida schema e compatibilita'." },
];

function chiudiOnboarding() {
  const o = document.getElementById("onboard");
  if (o) {
    o.classList.add("hidden");
    o.setAttribute("hidden", "");
    o.style.display = "none";
  }
  const d = document.getElementById("onboard-details");
  if (d) {
    d.classList.add("hidden");
    d.setAttribute("hidden", "");
    d.style.display = "none";
  }
  try { localStorage.setItem("orchestra.onboard.done", "1"); } catch (e) {}
}

let _onboardSel = null;

function mostraDettagli(cat) {
  _onboardSel = cat;
  const d = document.getElementById('onboard-details');
  const dcat = document.getElementById('onboard-details-cat');
  const dcat2 = document.getElementById('onboard-details-cat2');
  const din = document.getElementById('onboard-details-input');
  if (dcat) dcat.textContent = cat.t;
  if (dcat2) dcat2.textContent = cat.t;
  if (din) din.placeholder = 'es. ' + cat.d;
  // nascondi primo backdrop, mostra secondo
  document.getElementById('onboard').style.display = 'none';
  document.getElementById('onboard').hidden = true;
  d.style.display = '';
  d.hidden = false;
  if (din) din.focus();
}

function tornaIndietro() {
  _onboardSel = null;
  document.getElementById('onboard-details').style.display = 'none';
  document.getElementById('onboard-details').hidden = true;
  document.getElementById('onboard').style.display = '';
  document.getElementById('onboard').hidden = false;
}

async function avviaDalDettaglio() {
  const inp = document.getElementById('onboard-details-input');
  const txt = (inp && inp.value || '').trim();
  if (!txt) { inp && inp.focus(); return; }
  const cat = _onboardSel;
  const obiettivo = cat ? cat.d + '. ' + txt : txt;
  const profile = (cat && cat.profile) || 'auto';
  try {
    const r = await fetch('/api/goal/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ objective: obiettivo, profile, kind: 'goal' }),
    });
    const j = await r.json();
    if (!r.ok) {
      alert('Avvio fallito: ' + (j.error || 'sconosciuto'));
      return;
    }
    // chiudi entrambi i backdrop
    chiudiOnboarding();
    if (goalBar) { goalBar.hidden = false; goalPolling(); }
    caricaGoal();
    // imposta il campo input con l'obiettivo e avvia
    const input = document.getElementById('input');
    if (input) { input.value = obiettivo; if (typeof autoGrow === 'function') autoGrow(); }
    // avvia il goal via scheduler o direttamente
    if (typeof send === 'function') {
      // il goal è già stato avviato dal backend, ma mostriamo l'obiettivo
      const ev = new Event('input');
      input && input.dispatchEvent(ev);
    }
  } catch (e) {
    alert('Errore di rete: ' + e.message);
  }
}

async function avviaObiettivo(o) {
  // imposta profile e scope, poi mostra dettagli invece di inviare subito
  try {
    await fetch('/api/tools/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: o.profile || 'auto' }),
    });
  } catch (e) { /* best effort */ }
  if (typeof applicaScope === 'function' && o.scope) {
    const sp = document.getElementById('scope-pick');
    if (sp) { sp.value = o.scope; }
    try { applicaScope(o.scope); } catch (e) {}
  }
  // mostra schermata dettagli invece di inviare subito
  mostraDettagli(o);
}

function mostraOnboarding(forza) {
  const det = document.getElementById("onboard-details");
  if (det) { det.classList.add("hidden"); det.setAttribute("hidden", ""); det.style.display = "none"; }
  const o = document.getElementById("onboard");
  if (!o) return;
  if (!forza && localStorage.getItem("orchestra.onboard.done")) return;
  const cards = document.getElementById("onboard-cards");
  if (cards && !cards.childElementCount) {
    for (const o of OBBIETTIVI) {
      const b = document.createElement("button");
      b.className = "onboard-card";
      const t = document.createElement("div"); t.className = "t"; t.textContent = o.t;
      const d = document.createElement("div"); d.className = "d"; d.textContent = o.d;
      b.appendChild(t); b.appendChild(d);
      b.addEventListener("click", () => avviaObiettivo(o));
      cards.appendChild(b);
    }
  }
  o.classList.remove("hidden");
  o.removeAttribute("hidden");
  o.style.display = "";
}

const _avviaOnboardingSeServe = () => {
  const skip = document.getElementById("onboard-skip");
  if (skip) skip.addEventListener("click", chiudiOnboarding);
  const o = document.getElementById("onboard");
  // onboarding non si apre piu' da solo all'avvio: resta accessibile dal bottone "Cosa fai?"
};
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _avviaOnboardingSeServe, { once: true });
} else {
  _avviaOnboardingSeServe();
}

const btnOnboard = $("btn-onboard");
if (btnOnboard) {
  // mostra modal anche se aveva gia' detto "Salta"
  btnOnboard.addEventListener("click", () => {
    try { localStorage.removeItem("orchestra.onboard.done"); } catch (e) {}
    mostraOnboarding(true);
  });
}
// handler per schermata dettagli
const btnDettagliBack = $("onboard-back");
if (btnDettagliBack) btnDettagliBack.addEventListener("click", tornaIndietro);
const btnDettagliAvvia = $("onboard-avvia");
if (btnDettagliAvvia) btnDettagliAvvia.addEventListener("click", avviaDalDettaglio);
const dettagliInput = $("onboard-details-input");
if (dettagliInput) dettagliInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    avviaDalDettaglio();
  }
});



// ------------------------------------------------- dipendenze opzionali (pannello)
const btnDeps = $("opzioni-deps");
function _depsChiudi() {
  const m = document.getElementById("deps-modal");
  if (m) m.remove();
}
async function _depsStato() {
  const r = await fetch("/api/dipendenze/stato");
  return r.json().catch(() => ({ deps: [] }));
}
async function _depsInstalla(nome, btn) {
  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "installazione…";
  try {
    const r = await fetch("/api/dipendenze/installa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) alert(d.error || "Errore installazione " + nome);
    else alert((d.output || "fatto").slice(-1200));
  } catch (e) {
    alert("Errore: " + e);
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
    // ricarica stato
    _depsApri();
  }
}
async function _depsApri() {
  _depsChiudi();
  const data = await _depsStato();
  const deps = data.deps || [];
  const modal = document.createElement("div");
  modal.id = "deps-modal";
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText = "background:var(--bg,#1a1a2e);color:var(--fg,#eee);padding:20px;border-radius:12px;max-width:420px;width:90%;max-height:80vh;overflow:auto;box-shadow:0 8px 32px rgba(0,0,0,.4);";
  // Il titolo diceva "opzionali" perche' il pannello conosceva solo quelle
  // tre (ddgs, faster-whisper, cloudflared). Ora la lista viene da
  // `requirements.txt`, quindi contiene anche cio' che serve ai tool:
  // chiamarle opzionali sarebbe falso, e un utente che non le installa
  // trova un tool che dice "installa Pillow" e un pannello che non lo
  // nominava.
  let html = "<h3 style='margin:0 0 12px'>Dipendenze</h3>";
  html += "<p style='font-size:12px;opacity:.7;margin:0 0 12px'>Python: " + (data.python || "?") + "</p>";
  for (const d of deps) {
    const ok = d.stato === "ok";
    html += "<div style='display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.1)'>";
    html += "<div><strong>" + d.nome + "</strong><br><span style='font-size:11px;opacity:.6'>" + (ok ? (d.versione || "ok") : "da installare") + " · " + (d.via || "") + (d.perche ? " · " + d.perche : "") + "</span></div>";
    if (!ok) {
      html += "<button class='deps-install' data-nome='" + d.nome + "' style='padding:4px 10px;border-radius:6px;border:1px solid #555;background:transparent;color:inherit;cursor:pointer;font-size:12px'>Installa</button>";
    } else {
      html += "<span style='color:#4ade80;font-size:12px'>✓ ok</span>";
    }
    html += "</div>";
  }
  html += "<div style='text-align:right;margin-top:12px'><button id='deps-chiudi' style='padding:6px 14px;border-radius:6px;border:1px solid #555;background:transparent;color:inherit;cursor:pointer'>Chiudi</button></div>";
  box.innerHTML = html;
  modal.appendChild(box);
  document.body.appendChild(modal);
  modal.addEventListener("click", (e) => { if (e.target === modal) _depsChiudi(); });
  const chiudi = document.getElementById("deps-chiudi");
  if (chiudi) chiudi.addEventListener("click", _depsChiudi);
  box.querySelectorAll(".deps-install").forEach((b) => {
    b.addEventListener("click", () => _depsInstalla(b.dataset.nome, b));
  });
}
if (btnDeps) btnDeps.addEventListener("click", _depsApri);

// ------------------------------------------------- documentazione (nuova scheda)
const btnDocs = $("btn-docs");
if (btnDocs) btnDocs.addEventListener("click", () => window.open("/docs", "_blank", "noopener"));

// ------------------------------------------------- diagnostica allowlisted
// Era un modal costruito a mano da JavaScript e aperto da un pulsante in
// alto: un overlay in piu', con stile duplicato e nessun collegamento con
// il resto dell'interfaccia. Ora e' una sezione di Opzioni, e l'unica cosa
// che resta del vecchio e' la chiamata all'endpoint. L'output NON si
// accumula: eseguire due volte il comando deve dare due risultati, non
// quattro.
const diagScelta = $("diag-scelta");
const diagRun = $("diag-run");
const diagOut = $("diag-out");
if (diagRun && diagOut) {
  diagRun.addEventListener("click", async () => {
    const sel = diagScelta ? diagScelta.value : "";
    diagOut.value = "Esecuzione " + sel + "...";
    try {
      const d = await fetch("/api/diagnosi/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comando: sel }),
      });
      const r = await d.json().catch(() => ({}));
      diagOut.value = (r.output || r.error || JSON.stringify(r)).slice(-4000);
      if (r.returncode && r.returncode !== 0) {
        diagOut.value += String.fromCharCode(10) + "[codice " + r.returncode + "]";
      }
    } catch (e) {
      diagOut.value = "Errore: " + e;
    }
  });
}
