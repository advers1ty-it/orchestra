(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("main")<0)window.__diagFiles.push("main");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"main");}})();
// ------------------------------------------------------------- azioni
async function send() {
  const text = input.value.trim();
  // Solo gli allegati caricati: uno rimasto "carico..." o con un
  // errore non ha un id, e mandarlo cosi' fa fallire l'invio con un
  // messaggio che parla di registro — che a te non dice niente.
  const daMando = allegatiInAttesa.filter((a) => !a.errore && a.id && !a.in_caricamento);
  const nonPronti = allegatiInAttesa.filter((a) => a.in_caricamento && !a.errore);
  if (nonPronti.length) {
    addText("error", "aspetta che l'allegato finisca di caricare");
    return;
  }
  // Solo allegati, senza testo: si manda lo stesso. Un file da solo e'
  // una domanda ("che c'e' in questa foto?") e non merita un blocco.
  if ((!text && !daMando.length) || busy || !ready) return;
  input.value = "";
  autoGrow();
  setBusy(true);
  try {
    const r = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // Gli allegati viaggiano con il messaggio, non da soli: li
      // manda chi preme Invio, e vengono svuotati solo se la richiesta
      // e' andata a buon fine. Se fallisce restano attaccati al
      // campo, perche' altrimenti perdi un file da 40.000 token
      // premendo due volte per errore.
      body: JSON.stringify({
              text,
              // Solo gli id: il file e' gia' al server, che lo ha validato
              // quando e' stato caricato.
              allegati: daMando.map((a) => a.id).filter(Boolean),
              scope: scopeAttivo || null,
              // Self-correzione: se il toggle ✓ e' attivo e c'e' un file da
              // controllare, si chiede al server di verificare il lavoro prima
              // di accettarlo. Lista vuota = nessuna verifica, come prima.
              verifica: verificaPayload(),
            }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      addText("error", err.error || `errore ${r.status}`);
      setBusy(false);
      // riattacca: il file non e' partito, e perderlo qui significa
      // doverlo cercare di nuovo
      return;
    }
    // il conto in token torna dal server, non e' stimato qui: il
    // server conosce le pagine del PDF e quante immagini sono, e una
    // stima fatta dal browser sarebbe una stima diversa dalla verita'
    try {
      const esito = await r.json();
      if (esito.allegati && esito.allegati.length) {
        const totale = esito.allegati.reduce((s, a) => s + (a.token || 0), 0);
        addText("info", `allegati: ${esito.allegati.length} · ~${totale.toLocaleString()} token`);
      }
    } catch (e) { /* la risposta non conta: il messaggio e' partito */ }
    allegatiInAttesa = [];
    disegnaAllegati();
  } catch (e) {
    addText("error", String(e));
    setBusy(false);
  }
}

async function cancel() {
  try { await fetch("/api/cancel", { method: "POST" }); } catch {}
}

async function reset() {
  try {
    const r = await fetch("/api/reset", { method: "POST" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      addText("error", err.error || `errore ${r.status}`);
    }
  } catch (e) { addText("error", String(e)); }
}

function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
}

// ---- Allegati: foto, PDF, testo
//
// I file si scelgono con la graffetta o con l'incolla (Ctrl+V), e si
// mandano INSIEME al messaggio successivo, non da soli.
//
// Il conto in token e' accanto al nome perche' e' la cosa che decide:
// 40.000 token e' una richiesta da trenta centesimi, 1.100 e' un
// centesimo. Vederlo solo dopo averlo gia' speso non serve.
//
// Il file non viene scritto su disco: va al server come data URL e
// basta. Un allegato da 12 MB in un file sul disco sopravvive alla
// sessione, occupa spazio per sempre, e finisce in qualche backup.
// Sul server non finisce niente: vive finche' la richiesta dura.
const btnAllega = $("btn-allega");
const fileInput = $("file-input");
const listaAllegati = $("allegati-lista");

let allegatiInAttesa = [];

// 12 MB, uguale al tetto del server. Qui si ferma PRIMA di leggere il
// file: un file da 40 MB letto in memoria e poi rifiutato e' una
// pagina bianca per un secondo, e il rifiuto non arriva.
const LIMITE_MB = 12;

function _leggiFile(file) {
  return new Promise((ok, ko) => {
    const lettore = new FileReader();
    lettore.onload = () => ok(lettore.result);
    lettore.onerror = () => ko(new Error("lettura fallita"));
    lettore.readAsDataURL(file);
  });
}

async function aggiungiFile( listaFile ) {
  if (!allegatiInAttesa.length && !busy) allegatiInAttesa = [];
  for (const file of listaFile) {
    if (file.size > LIMITE_MB * 1024 * 1024) {
      allegatiInAttesa.push({
        errore: file.name + ": " + Math.round(file.size / 1048576) +
                " MB, il limite e' " + LIMITE_MB,
      });
      disegnaAllegati();
      continue;
    }
    // La riga appare SUBITO, anche prima della risposta: unattesa
    // senza nulla che spieghi il perche' sembra una pagina rotta, e
    // l'utente prova a cliccare il pulsante che non c'e' ancora.
    const voce = { nome: file.name, in_caricamento: true, data_url: null };
    allegatiInAttesa.push(voce);
    disegnaAllegati();
    try {
      const data_url = await _leggiFile(file);
      voce.data_url = data_url;
      // Il file va al server QUI, una volta sola. Prima lo mandavo due
      // volte — una per il conto, una per l'invio — e un file da 12 MB
      // viaggiava 32: il secondo passaggio moriva e il browser
      // diceva "Failed to fetch", che sembra un problema di rete.
      const esito = await _manda_allega(file.name, data_url);
      if (!esito.ok) {
        voce.errore = file.name + ": " + esito.errore;
        disegnaAllegati();
        continue;
      }
      // id: quello che andra' a /api/send. Senza questo la riga
      // restava "carico..." per sempre: il flag non lo toglieva
      // nessuno, perche' non c'era nessuno a farlo.
      //
      // La risposta porta gli id come lista. Un file ne ha uno solo,
      // e mettere la lista intera nella voce faceva arrivare a
      // /api/send [["al-..."]] invece di ["al-..."]: una lista dentro
      // la lista, che il server respinge come "allegato non valido".
      // Sembrava funzionasse — la riga si riempiva, il conto c'era —
      // e falliva solo all'invio.
      const idArr = Array.isArray(esito.id) ? esito.id : [esito.id];
      voce.id = idArr[0] || null;
      voce.token_stimati = esito.token;
      voce.in_caricamento = false;
    } catch (e) {
      voce.errore = file.name + ": " + (e && e.message ? e.message : e);
      voce.in_caricamento = false;
    }
    disegnaAllegati();
  }
}

// Manda un file e ne restituisce id e costo. Gli errori arrivano come
// testo: qui il fallimento e' sempre leggibile, e un "Failed to
// fetch" qui significherebbe che la connessione e' caduta davvero.
async function _manda_allega(nome, data_url) {
  const r = await fetch("/api/allega", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: [{ nome, data_url }] }),
  });
  let d = {};
  try { d = await r.json(); } catch (e) { /* risposta non JSON */ }
  if (!r.ok) return { ok: false, errore: d.error || ("errore " + r.status) };
  return { ok: true, id: d.id, token: d.token, allegati: d.allegati };
}

function disegnaAllegati() {
  if (!listaAllegati) return;
  const utili = allegatiInAttesa.filter((a) => !a.errore);
  listaAllegati.replaceChildren();
  listaAllegati.hidden = !allegatiInAttesa.length;

  for (const [i, a] of allegatiInAttesa.entries()) {
    if (a.errore) {
      const e = el("div", "allegato-errore");
      e.textContent = a.errore;
      listaAllegati.appendChild(e);
      continue;
    }
    const riga = el("div", "allegato-riga");

    const icona = el("span", "allegato-icona");
    icona.textContent = a.in_caricamento ? "⏳"
      : (a.data_url || "").startsWith("data:image") ? "🖼"
      : (a.data_url || "").startsWith("data:application/pdf") ? "📄" : "📝";
    riga.appendChild(icona);

    // Il nome e' modificabile: il file che si chiama IMG_4821.jpg
    // finisce in contesto come "IMG_4821.jpg", e un modello risponde
    // meglio a "listino-prezzi-giugno.pdf" che a un nome di telefono.
    const nome = el("span", "allegato-nome");
    const campo = el("input");
    campo.type = "text";
    campo.value = a.nome;
    campo.title = "Cambia il nome che vedra' l'agente";
    on(campo, "input", (e) => { a.nome = e.target.value || "allegato"; });
    nome.appendChild(campo);
    riga.appendChild(nome);

    const costo = el("span", "allegato-costo");
    if (a.in_caricamento) {
      costo.textContent = "carico…";
    } else if (typeof a.token_stimati === "number") {
      costo.textContent = "~" + a.token_stimati.toLocaleString() + " token";
      // sopra 20.000 token la richiesta costa decine di centesimi:
      // si avvisa, non si vieta. Vietare sarebbe corretto e
      // inutile — il utente puo' sapere che costa e decidere.
      if (a.token_stimati > 20000) costo.className = "allegato-costo alto";
    }
    riga.appendChild(costo);

    const togli = el("button", "allegato-tomba", "×");
    togli.title = "Togli questo allegato";
    on(togli, "click", () => {
      allegatiInAttesa.splice(i, 1);
      disegnaAllegati();
    });
    riga.appendChild(togli);

    listaAllegati.appendChild(riga);
  }
  if (!utili.length && !allegatiInAttesa.some((a) => a.errore)) {
    listaAllegati.hidden = true;
  }
}

on(btnAllega, "click", () => { if (fileInput) fileInput.click(); });

on(fileInput, "change", async () => {
  const files = Array.from(fileInput.files || []);
  if (files.length) await aggiungiFile(files);
  fileInput.value = "";   // cosi' scegliere lo stesso file due volte funziona
});

// Incollare un'immagine dagli appunti e' il modo piu' naturale di
// darne una, molto piu' del "vai a cercarla". E' anche quello che
// su Windows e' gratis: il file e' gia' in memoria.
on(document, "paste", async (e) => {
  if (busy) return;
  const dt = e.clipboardData;
  if (!dt || !dt.files || !dt.files.length) return;
  const file = dt.files[0];
  // Solo immagini incollate: un file di testo incollato lo mette
  // gia' l'utente nel campo, e metterlo due volte e' peggio che
  // lasciarglielo scrivere.
  if (!file.type.startsWith("image/")) return;
  e.preventDefault();
  await aggiungiFile([file]);
});

on(input, "input", autoGrow);

// ------------------------------------------------- verifica del lavoro
// Toggle ✓ accanto alla graffetta. Quando è attivo, il prossimo invio
// chiede al server di verificare OGGETTIVAMENTE il risultato e, se non
// torna, rimandare il modello indietro col motivo. Mai un modello che
// giudica un modello: si controlla il file, il JSON, la somma.
let verificaAttiva = false;

function verificaPayload() {
  // Attivo solo con un file indicato: senza file non c'è niente da
  // controllare, e mandare una verifica vuota sarebbe rumore.
  if (!verificaAttiva) return [];
  const file = ($("verifica-file").value || "").trim();
  if (!file) return [];
  const tipo = $("verifica-tipo").value;
  const spec = { tipo, file };
  // I parametri extra dipendono dal tipo: senza, il server li ignora e
  // usa default ragionevoli, ma per "somma" e "contiene" servono.
  if (tipo === "testo_lungo") spec.minimo = 1;
  if (tipo === "testo_contiene") spec.frammenti = [];
  return [spec];
}

const btnVerifica = $("btn-verifica");
const verificaPop = $("verifica-pop");
const btnMic = $("btn-mic-float");

function apriChiudiVerifica() {
  verificaPop.hidden = !verificaPop.hidden;
}

if (btnVerifica && verificaPop) {
  // Il toggle riflette SUBITO lo stato: il ✓ acceso dice "la prossima
  // verifica", spento dice "gira normale". Se non si accendesse, non si
  // saprebbe se è attivo finché non parte il turno.
  btnVerifica.addEventListener("click", () => {
    verificaAttiva = !verificaAttiva;
    btnVerifica.classList.toggle("acceso", verificaAttiva);
    apriChiudiVerifica();
    if (verificaAttiva && !($("verifica-file").value || "").trim()) {
      $("verifica-file").focus();
    }
  });
  // Cambiare tipo o file chiude il popover: la scelta è fatta, e
  // lasciarlo aperto copre il campo di scrittura.
  on("verifica-tipo", "change", apriChiudiVerifica);
  on("verifica-file", "change", apriChiudiVerifica);
}
// Dittazione vocale: Web Speech API quando disponibile (Chrome desktop
// e Android), altrimenti audio -> server -> faster-whisper.
let _micRec = false, _micStream = null, _micChunks = [];
let _recTimer = null;
function _micDisponibile() {
  return Promise.resolve(
    !!(window.SpeechRecognition || window.webkitSpeechRecognition)
    || (window._sttDisponibile === true));
}
function _micAvvia() {
  if (!btnMic || btnMic.disabled) return;
  const ws = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (ws) {
    _micRec = true;
    btnMic.classList.add("recording");
    const rec = new ws();
    rec.lang = (navigator.language || "it-IT");
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let t = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        t += e.results[i][0].transcript;
      }
      input.value = (input.value + t).slice(0, 4000);
    };
    rec.onerror = (e) => { console.warn("speech error", e); _micFerma(); };
    rec.onend = () => {
      const _had = (input.value || "").trim().length > 0;
      _micFerma();
      if (_had && !busy && ready) { setTimeout(send, 50); }
    };
    rec.start();
    return;
  }
  // Fallback: registra audio e manda al server
  navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
    _micStream = stream;
    _micRec = true;
    _micChunks = [];
    btnMic.classList.add("recording");
    const mr = new MediaRecorder(stream);
    mr.ondataavailable = (e) => { if (e.data.size > 0) _micChunks.push(e.data); };
    mr.onstop = async () => {
      const blob = new Blob(_micChunks, { type: "audio/webm" });
      const b64 = await blob.arrayBuffer().then(b => btoa(String.fromCharCode(...new Uint8Array(b))));
      try {
        const r = await fetch("/api/transcribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ audio: b64, filename: "audio.webm" }),
        });
        const j = await r.json();
        if (j.text) input.value = (input.value + " " + j.text).slice(0, 4000);
        else if (j.error) _micMessaggio(j.error);
      } catch (e) { _micMessaggio("errore trascrizione"); }
      _micFerma();
      if ((input.value || "").trim() && !busy && ready) { setTimeout(send, 50); }
    };
    mr.start();
    _recTimer = setTimeout(() => mr.stop(), 60000);
  }).catch((e) => { _micMessaggio("microfono non accessibile: " + e.message); });
}
function _micFerma() {
  if (_recTimer) { clearTimeout(_recTimer); _recTimer = null; }
  if (_micStream) { _micStream.getTracks().forEach(t => t.stop()); _micStream = null; }
  _micRec = false;
  if (btnMic) btnMic.classList.remove("recording");
}
function _micMessaggio(msg) {
  if (!btnMic) return;
  const old = btnMic.title;
  btnMic.title = msg;
  setTimeout(() => { if (btnMic) btnMic.title = "Dittazione vocale (faster-whisper)"; }, 4000);
}
if (btnMic) {
  btnMic.addEventListener("click", () => {
    if (_micRec) { _micFerma(); return; }
    _micAvvia();
  });
}
on(input, "keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
btnSend.onclick = send;
if (btnAllega) btnAllega.disabled = !ready;
// Verifica: stesso gate dell'allegato. Prima restava disabilitato per
// sempre (nessuna riga lo abilitava), quindi il ✓ non si accendeva mai,
// il popover non si apriva e la self-correzione non si attivava: di fuori
// sembrava rotta. Con `ready` segue lo stesso ciclo dell'allegato.
if (btnVerifica) btnVerifica.disabled = !ready;
if (btnMic) {
  btnMic.disabled = !ready;
  btnMic.hidden = true;
  // Il microfono è disponibile solo se il browser parla (Web Speech
  // API) o se il server ha whisper installato. Se entrambi mancano,
  // il pulsante non compare affatto.
  _micDisponibile().then((ok) => {
    if (!btnMic) return;
    btnMic.hidden = !ok;
    btnMic.disabled = !ready || !ok;
  });
}

// All'avvio chiediamo al server se whisper è installato: così il pulsante
// microfono compare solo quando c'è una via d'uscita (Web Speech API nel
// browser, o faster-whisper sul server). Se entrambi mancano, non
// mostriamo niente: non è un pulsante finto.
function _sttCheck() {
  fetch("/api/stt/status")
    .then(r => r.json())
    .then(j => { window._sttDisponibile = !!(j && j.disponibile); })
    .catch(() => { window._sttDisponibile = false; });
}
_sttCheck();

// Steer: inietta un messaggio al modello durante il lavoro
// (steerBar/steerInput/steerSend sono dichiarati in core.js)
function inviaSteer() {
  const testo = steerInput.value.trim();
  if (!testo) return;
  steerInput.value = "";
  fetch("/api/steer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ testo })
  }).then(r => r.json()).then(d => {
    if (!d.ok) alert(d.error || "Steer fallito");
    else {
      // Conferma visibile: l'utente deve sapere che la guida e' stata
      // ricevuta e verrà letta al prossimo tool, non aspettare in silenzio.
      const anteprima = testo.length > 80 ? testo.slice(0, 80) + "…" : testo;
      addNote(`guida inviata: «${anteprima}» — verrà letta al prossimo tool`);
    }
  });
  steerInput.focus();
}
if (steerSend) steerSend.onclick = inviaSteer;
if (steerStop) steerStop.onclick = cancel;
if (steerInput) steerInput.addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); inviaSteer(); }
});

connect();
// PWA: registra il service worker per cache offline della shell.
if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
// ---- Install PWA
// beforeinstallprompt scatta SOLO con manifest valido + service worker +
// secure context (localhost o HTTPS — il tunnel Cloudflare e' HTTPS).
// Senza questo handler il browser si limita a mettere la sua icona
// nell'toolbar, che nessuno trova: da qui "non vedo la richiesta di
// installazione". Un pulsante "Installa" appare quando il prompt e'
// disponibile e parte su un clic. Se le condizioni non ci sono (es. HTTP
// pubblico non-localhost) resta nascosto: non c'e' niente da mostrare.
let deferredPrompt = null;
let installBtn = $("btn-install");
function aggiornaInstall() {
  if (!installBtn) return;
  installBtn.hidden = !deferredPrompt;
}
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();          // tengo il prompt, lo mostro io al clic
    deferredPrompt = e;
    aggiornaInstall();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    aggiornaInstall();
  });
}
if (installBtn) {
  installBtn.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    const p = deferredPrompt;
    deferredPrompt = null;
    try {
      p.prompt();
      const { userChoice } = await p.userChoice;
      if (userChoice === "accepted" && typeof addNote === "function") {
        addNote("Orchestra installata: la trovi come un'app e funziona anche offline.");
      }
    } catch (e) { /* annullato o il browser non lo accetta: niente */ }
    aggiornaInstall();
  });
}
aggiornaInstall();

// ---- Header mobile: il pulsante "altre opzioni" espande/chiude i
// controlli secondari. Di default l'header resta compatto (logo, scopo,
// modello) cosi' non ruba quattro righe sullo schermo di un telefono.
// Desktop il pulsante non esiste (via CSS), quindi niente da fare.
(function () {
  const tog = $("btn-header-toggle");
  if (!tog) return;
  const hdr = tog.closest ? tog.closest("header") : null;
  if (!hdr) return;
  tog.addEventListener("click", () => {
    const aperto = hdr.classList.toggle("esteso");
    tog.setAttribute("aria-expanded", aperto ? "true" : "false");
    document.body.classList.toggle("header-menu-aperto", aperto);
    document.body.style.overflow = aperto ? "hidden" : "";
  });
  // chiusura con Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && hdr.classList.contains("esteso")) {
      hdr.classList.remove("esteso");
      tog.setAttribute("aria-expanded", "false");
      document.body.classList.remove("header-menu-aperto");
      document.body.style.overflow = "";
    }
  });
})();
// Opzioni si caricano QUI, non solo quando apri il pannello. I
// selettori di servizio e di scopo vivono nell'header, e senza questa
// chiamata restano disabilitati fino a quando non apri Opzioni: si
// vedono, sembrano cliccabili, e non lo sono. Il pannello e' una vista
// degli stessi dati, non il posto dove vengono costruiti.
// Le categorie si chiedono al server, che le conta dai task veri.
// Prima le categorie, poi il resto: cosi' il riepilogo sotto i
// selettori sappia cosa e' misurabile prima di dire "non ancora
// misurato" — o "senza test".
caricaCategorie();
caricaOpzioni().catch(() => {
  // un errore qui non deve fermare il bootstrap: la chat resta viva,
  // e i selettori semplicemente restano disabilitati
});
fetch("/api/state").then(r => r.json()).then(s => {
  if (s.version) showVersion(s.version);
  ready = s.ready !== false;
  // I bottoni allega e verifica seguono `ready`. Prima erano impostati una
  // sola volta all'avvio, quando ready era ancora false: restavano
  // disabilitati per sempre e il ✓ non si accendeva mai.
  if (btnAllega) btnAllega.disabled = !ready;
  if (btnVerifica) btnVerifica.disabled = !ready;
  if (!ready) { showBanner(s.error); if (typeof apriOpzioni === "function") apriOpzioni(); return; }
  // setBusy applica `ready` ai controlli. Senza questa chiamata il
  // flag e' impostato ma nessuno lo guarda: il campo resta disabilitato
  // e la pagina sembra rotta. E' lo stesso buco dei selettori di
  // servizio e scopo — una variabile che cambia non abilita niente da
  // sola, serve qualcuno che la legga e agisca.
  setBusy(false);
  // Sul telefono/tunnel il SSE puo' non consegnare lo snapshot
  // iniziale (buffering Cloudflare): /api/state e' la fonte di verita'
  // al caricamento, quindi lo applichiamo sempre, non solo se il log
  // e' vuoto. Un eventuale snapshot SSE successivo lo rimpiazza.
  handle("snapshot", s);
}).catch(() => { conn.textContent = "server non raggiungibile"; });

// La versione è il modo più economico per capire se stai guardando la
// pagina giusta. Senza, una UI in cache vecchia si manifesta come
// "funziona tutto tranne una cosa" e sembra un bug.
function showVersion(v) {
  $("ver").textContent = v || "?";
  $("ver").title = `interfaccia ${v || "?"} — se non corrisponde al server, ricarica`;
}

// ---------------------------------------------------- tracce dei turni
// La diagnosi dopo il fatto: ogni turno lascia una traccia su disco, e
// qui si riapre "perché è andato com'è andato" senza ripeterlo. Una riga
// per turno recente; al click, la sequenza esatta degli eventi.
// Codici di esito in parole: l'utente legge "completato",
// non "risposta_finale".
function etichettaEsito(esito) {
  return {
    risposta_finale: "completato",
    max_iterations: "fermato al limite",
    canceled_da_should_continue: "annullato",
    budget_exceeded: "budget finito",
    gira_a_vuoto: "girava a vuoto",
    troppi_errori_consecutivi: "troppi errori",
    verifica_fallita: "verifica fallita",
    solo_parole: "solo parole, niente fatti",
    // Il turno ha lavorato, ma si e' chiuso annunciando altro lavoro
    // invece di farlo. Diverso da "solo parole": qui qualcosa e' stato
    // fatto, e il lavoro e' rimasto a meta'.
    annuncio_finale: "fermato su un annuncio",
  }[esito || ""] || esito || "?";
}
async function caricaSideTracce() {
  const ul = $("side-tracce");
  if (!ul) return;
  try {
    const d = await (await fetch("/api/tracce")).json();
    const tracce = (d.tracce || []).slice(0, 15);
    ul.replaceChildren();
    if (!tracce.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.textContent = "Nessun compito registrato ancora: il primo apparirà qui.";
      ul.appendChild(li);
      return;
    }
    for (const t of tracce) {
      const li = document.createElement("li");
      li.className = "side-traccia";
      const btn = document.createElement("button");
      btn.className = "side-apri";
      const quando = new Date(t.ts * 1000).toLocaleString("it-IT",
        {day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit"});
      const esito = t.esito || "?";
      const classe = esito === "risposta_finale" ? "ok" : "attenzione";
      const titolo = document.createElement("span");
      titolo.className = "side-testo";
      titolo.textContent = `${quando} · ${etichettaEsito(esito)} · ${t.tool_chiamate} tool`;
      const meta = document.createElement("span");
      meta.className = "side-meta";
      meta.textContent = t.errori ? `${t.errori} errori` : `${t.n_eventi} eventi`;
      btn.appendChild(titolo);
      btn.appendChild(meta);
      btn.addEventListener("click", () => apriTraccia(t.id, btn));
      li.appendChild(btn);
      ul.appendChild(li);
    }
  } catch (e) { /* le tracce sono un extra: se non caricano, la sidebar vive */ }
}

// Il dettaglio sta in un modale: aperto sotto la lista finiva fuori
// dal viewport, e il click sembrava non funzionare.
function apriModaleTraccia() {
  const m = $("traccia-modal");
  if (!m) return;
  m.hidden = false;
  m.classList.add("show");
}
function chiudiModaleTraccia() {
  const m = $("traccia-modal");
  if (!m) return;
  m.hidden = true;
  m.classList.remove("show");
}
on($("traccia-chiudi"), "click", chiudiModaleTraccia);
on($("traccia-modal"), "click", (e) => {
  // click sul fondo (non sulla scatola) chiude
  if (e.target === e.currentTarget) chiudiModaleTraccia();
});
document.addEventListener("keydown", (e) => {
  const m = $("traccia-modal");
  if (e.key === "Escape" && m && !m.hidden) chiudiModaleTraccia();
});

async function apriTraccia(id, btn) {
  const det = $("side-traccia-dettaglio");
  if (!det) return;
  try {
    const t = await (await fetch("/api/tracce/" + id)).json();
    if (t.error) { det.textContent = t.error; apriModaleTraccia(); return; }
    det.replaceChildren();
    const intest = document.createElement("div");
    intest.className = "small dim";
    intest.textContent =
      `#${t.riepilogo.id} · ${t.riepilogo.modello || "?"} · ` +
      `${t.riepilogo.iterazioni} iter · ${t.riepilogo.token} tok · ` +
      `${t.riepilogo.durata_s.toFixed(1)}s · ${etichettaEsito(t.riepilogo.esito)}`;
    det.appendChild(intest);
    const ol = document.createElement("ol");
    ol.className = "side-traccia-eventi";
    for (const e of (t.eventi || [])) {
      const li = document.createElement("li");
      const tipo = e.tipo;
      let riga = tipo;
      if (tipo === "tool_start") riga = `tool → ${e.dati.name}`;
      else if (tipo === "tool_end") riga = `tool ${e.dati.name}: ${e.dati.ok ? "ok" : "errore"}`;
      else if (tipo === "assistant") riga = e.dati.content && e.dati.content.trim()
        ? `assistant: ${e.dati.content.trim().slice(0, 60)}` : "assistant (chiama tool)";
      else if (tipo === "verifica") riga = `verifica: ${e.dati.ok ? "passata" : e.dati.motivo}`;
      else if (tipo === "gira_a_vuoto") riga = `GIRA A VUOTO su ${e.dati.tool}`;
      else if (tipo === "fallback_triggered") riga = `fallback → ${e.dati.model || e.dati.provider}`;
      else if (tipo === "compaction") riga = `compattazione ${e.dati.tokens_before}→${e.dati.tokens_after}`;
      li.textContent = riga;
      li.className = "side-traccia-ev " + (tipo === "tool_end" && !e.dati.ok ? "err" : "");
      ol.appendChild(li);
    }
    det.appendChild(ol);
    apriModaleTraccia();
  } catch (e) {
    det.textContent = "apertura traccia fallita: " + e;
    apriModaleTraccia();
  }
}

// ------------------------------------------------------------- Dettatura vocale (STT)
//
// Microfono flottante in basso a destra. Due vie:
//   1. Web Speech API (Chrome desktop + Android): gratis, zero server.
//   2. MediaRecorder + /api/transcribe (faster-whisper sul server): per i
//      browser senza Web Speech API (Safari/iOS). Funziona solo se whisper
//      e' installato sul PC che serve l'app.
const micFloat = $("mic-float");
let micRecording = false;
let micRecognition = null;
let mediaRecorder = null;
let micChunks = [];

const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const hasWebSpeech = !!SpeechRecognitionCtor;

async function micDisponibile() {
  if (hasWebSpeech) return true;
  try {
    const r = await fetch("/api/stt/status");
    const j = await r.json();
    return !!(j && j.disponibile);
  } catch (e) { return false; }
}

function micUpdateUI() {
  if (!micFloat) return;
  micFloat.classList.toggle("recording", micRecording);
  const span = micFloat.querySelector("span");
  if (span) span.textContent = micRecording ? "⏹" : "🎤";
  micFloat.title = micRecording ? "Ferma la dettatura" : "Dettatura vocale";
}

async function micToggle() {
  if (micRecording) {
    if (micRecognition) { try { micRecognition.stop(); } catch (e) {} }
    if (mediaRecorder && mediaRecorder.state !== "inactive") { try { mediaRecorder.stop(); } catch (e) {} }
    micRecording = false;
    micUpdateUI();
    return;
  }
  if (hasWebSpeech) {
    try {
      micRecognition = new SpeechRecognitionCtor();
      micRecognition.lang = "it-IT";
      micRecognition.interimResults = true;
      micRecognition.continuous = true;
      micRecognition.onresult = (e) => {
        let final = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) final += e.results[i][0].transcript;
        }
        if (final) {
          input.value = (input.value + " " + final).trim();
          autoGrow();
        }
      };
      micRecognition.onend = () => {
        const _had = (input.value || "").trim().length > 0;
        micRecording = false; micUpdateUI();
        // Auto-invio: quando la dettatura finisce (sia manuale che
        // automatica) e c'e' testo, manda il messaggio da solo.
        if (_had && !busy && ready) { setTimeout(send, 50); }
      };
      micRecognition.onerror = (e) => {
        addText("error", "dettatura: " + ((e && e.error) || "errore"));
        micRecording = false; micUpdateUI();
      };
      micRecognition.start();
      micRecording = true;
      micUpdateUI();
    } catch (e) {
      addText("error", "dettatura non avviata: " + e);
    }
  } else {
    // MediaRecorder + whisper sul server
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      micChunks = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) micChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        const blob = new Blob(micChunks, { type: mediaRecorder.mimeType || "audio/webm" });
        const reader = new FileReader();
        reader.onloadend = async () => {
          try {
            const b64 = (reader.result || "").split(",")[1] || "";
            const r = await fetch("/api/transcribe", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ audio: b64, filename: "audio.webm" }),
            });
            const j = await r.json();
            if (j && j.text) {
              input.value = (input.value + " " + j.text).trim();
              autoGrow();
              if ((input.value || "").trim() && !busy && ready) { setTimeout(send, 50); }
            } else {
              addText("error", "trascrizione fallita: " + ((j && j.error) || "errore"));
            }
          } catch (e) { addText("error", "trascrizione fallita: " + e); }
        };
        reader.readAsDataURL(blob);
        stream.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} });
      };
      mediaRecorder.start();
      micRecording = true;
      micUpdateUI();
    } catch (e) {
      addText("error", "microfono non disponibile: " + e);
    }
  }
}

(async function initMic() {
  const avail = await micDisponibile();
  if (!avail || !micFloat) return;
  micFloat.classList.add("show");
  micFloat.onclick = micToggle;
})();
