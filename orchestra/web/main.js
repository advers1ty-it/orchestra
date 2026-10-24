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
  if (typeof btnStop !== "undefined" && btnStop) btnStop.disabled = true;
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
on(input, "keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
btnSend.onclick = send;
if (btnAllega) btnAllega.disabled = !ready;
if (typeof btnStop !== "undefined" && btnStop) btnStop.onclick = cancel;

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
  if (s.ready === false) { showBanner(s.error); if (typeof apriOpzioni === "function") apriOpzioni(); return; }
  ready = true;
  // setBusy applica `ready` ai controlli. Senza questa chiamata il
  // flag e' impostato ma nessuno lo guarda: il campo resta disabilitato
  // e la pagina sembra rotta. E' lo stesso buco dei selettori di
  // servizio e scopo — una variabile che cambia non abilita niente da
  // sola, serve qualcuno che la legga e agisca.
  setBusy(false);
  if (!log.children.length) handle("snapshot", s);
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
