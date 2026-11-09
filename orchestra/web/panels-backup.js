(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-backup")<0)window.__diagFiles.push("panels-backup");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-backup");}})();
// --------------------------------------------------------------- Backup
//
// PERCHE' QUI E NON NELLE OPZIONI BOT
//
// Il backup non appartiene a un'identita': appartiene a un'INSTALLAZIONE.
// Chi ha l'app in AppData, una copia su D: e due server di prova ha tre
// cartelle dati diverse, e ognuna ha la sua memoria, i suoi bot e le sue
// chiavi. Il pannello le elenca per percorso, perche' l'hash della
// cartella non lo ricorda nessuno — ed e' proprio quello che il CLI da
// solo non poteva mostrare.
//
// Il ripristino chiede conferma e dice dove va a scrivere: e' l'unica
// azione di questa schermata che sovrascrive qualcosa, e il posto dove
// finisce non deve essere una deduzione dell'utente.

function backupNumero(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / (1024 * 1024)).toFixed(1) + " MB";
}

function backupQuando(secondi) {
  if (!secondi) return "";
  try {
    const d = new Date(Number(secondi) * 1000);
    return d.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
  } catch (e) {
    return "";
  }
}

function backupEsito(testo) {
  const box = $("backup-esito");
  if (box) box.textContent = testo || "";
}

function backupChiavi() {
  const c = $("backup-chiavi");
  return c ? !!c.checked : true;
}

async function caricaBackup() {
  const elenco = $("backup-elenco");
  const archiviBox = $("backup-archivi");
  if (!elenco || !archiviBox) return;
  elenco.textContent = "Carico…";
  let d = {};
  try {
    const r = await fetch("/api/backup");
    d = await r.json();
  } catch (e) {
    elenco.textContent = "Impossibile leggere l'elenco.";
    return;
  }
  if (d.error) {
    elenco.textContent = "Errore: " + d.error;
    return;
  }
  elenco.innerHTML = "";
  const corrente = d.corrente || "";
  const installazioni = d.installazioni || [];
  if (!installazioni.length) {
    elenco.textContent = "Nessuna installazione trovata.";
    return;
  }
  for (const v of installazioni) {
    const riga = document.createElement("div");
    riga.className = "backup-riga";

    const testa = document.createElement("div");
    testa.className = "backup-testa";
    const nome = document.createElement("b");
    nome.textContent = v.percorso || "(percorso non registrato)";
    testa.appendChild(nome);
    if (v.corrente) {
      const qui = document.createElement("span");
      qui.className = "backup-qui";
      qui.textContent = "questa installazione";
      testa.appendChild(qui);
    }
    riga.appendChild(testa);

    const dettaglio = document.createElement("div");
    dettaglio.className = "small dim";
    const pezzi = [];
    pezzi.push((v.file || 0) + " file");
    pezzi.push(backupNumero(v.byte));
    if (v.versione) pezzi.push("versione " + v.versione);
    if (v.modificato) pezzi.push("ultimo uso " + backupQuando(v.modificato));
    dettaglio.textContent = pezzi.join(" · ");
    riga.appendChild(dettaglio);

    const dati = document.createElement("div");
    dati.className = "small dim backup-dati";
    dati.textContent = "dati: " + v.dati + (v.id ? " (" + v.id + ")" : "");
    riga.appendChild(dati);

    const barra = document.createElement("div");
    barra.className = "backup-barra";
    const salva = document.createElement("button");
    salva.className = "ghost";
    salva.textContent = "Salva questa";
    salva.onclick = () => backupCrea(v.dati, salva);
    barra.appendChild(salva);
    riga.appendChild(barra);

    elenco.appendChild(riga);
  }

  // Gli archivi: quelli gia' presenti nelle cartelle `backup`, dal piu'
  // recente. Un ripristino parte quasi sempre da qui, e digitare un
  // percorso a mano e' il modo piu' facile per sbagliare file.
  archiviBox.innerHTML = "";
  const archivi = d.archivi || [];
  if (!archivi.length) {
    const vuoto = document.createElement("p");
    vuoto.className = "small dim";
    vuoto.textContent = "Nessun archivio: salva un'installazione, o copia uno zip "
                      + "in una cartella backup.";
    archiviBox.appendChild(vuoto);
    return;
  }
  for (const a of archivi) {
    const riga = document.createElement("div");
    riga.className = "backup-riga";

    const testa = document.createElement("div");
    testa.className = "backup-testa";
    const nome = document.createElement("b");
    nome.textContent = a.nome;
    testa.appendChild(nome);
    if (a.rotto) {
      const rotto = document.createElement("span");
      rotto.className = "backup-qui";
      rotto.textContent = "illeggibile";
      testa.appendChild(rotto);
    }
    riga.appendChild(testa);

    const dettaglio = document.createElement("div");
    dettaglio.className = "small dim";
    const pezzi = [];
    if (a.versione) pezzi.push("versione " + a.versione);
    if (a.creato) pezzi.push("creato " + a.creato.replace("T", " "));
    pezzi.push(backupNumero(a.byte));
    if (a.con_chiavi) pezzi.push("con chiavi");
    dettaglio.textContent = pezzi.join(" · ");
    riga.appendChild(dettaglio);

    if (a.profilo) {
      const prof = document.createElement("div");
      prof.className = "small dim backup-dati";
      prof.textContent = "per: " + a.profilo;
      riga.appendChild(prof);
    }

    const barra = document.createElement("div");
    barra.className = "backup-barra";
    if (corrente && a.dati === corrente) {
      // Il ripristino dell'installazione in uso va fatto a server chiuso:
      // le connessioni sqlite restano aperte, e sostituire i file sotto
      // chi scrive e' peggio che non ripristinare.
      const nota = document.createElement("span");
      nota.className = "small dim";
      nota.textContent = "installazione in uso: ferma Orchestra e usa "
                       + "orchestra restore da terminale";
      barra.appendChild(nota);
    } else {
      const ripristina = document.createElement("button");
      ripristina.className = "ghost";
      ripristina.textContent = "Ripristina";
      ripristina.onclick = () => backupRipristina(a, ripristina);
      barra.appendChild(ripristina);
    }
    riga.appendChild(barra);

    archiviBox.appendChild(riga);
  }
}

async function backupCrea(profilo, bottone) {
  if (bottone) bottone.disabled = true;
  backupEsito("Salvataggio in corso…");
  try {
    const r = await fetch("/api/backup/crea", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profilo: profilo || "", con_chiavi: backupChiavi() }),
    });
    const d = await r.json();
    if (d.error) {
      backupEsito("Errore: " + d.error);
      return;
    }
    const e = (d.esiti || [])[0] || {};
    if (e.esito === "errore") {
      backupEsito("Errore: " + (e.errore || "non riuscito"));
      return;
    }
    backupEsito("Salvato in " + e.percorso + " (" + backupNumero(e.byte) + ").");
    await caricaBackup();
  } catch (e) {
    backupEsito("Errore di rete: " + e);
  } finally {
    if (bottone) bottone.disabled = false;
  }
}

async function backupTutte(bottone) {
  if (bottone) bottone.disabled = true;
  backupEsito("Salvataggio di tutte le installazioni…");
  try {
    const r = await fetch("/api/backup/crea", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tutte: true, con_chiavi: backupChiavi() }),
    });
    const d = await r.json();
    if (d.error) {
      backupEsito("Errore: " + d.error);
      return;
    }
    const esiti = d.esiti || [];
    const ok = esiti.filter((e) => e.esito === "ok").length;
    const male = esiti.filter((e) => e.esito !== "ok");
    let testo = ok + " installazioni salvate.";
    if (male.length) {
      testo += " Non riuscite: " +
        male.map((e) => (e.profilo || e.dati) + " (" + (e.errore || "") + ")").join(", ");
    }
    backupEsito(testo);
    await caricaBackup();
  } catch (e) {
    backupEsito("Errore di rete: " + e);
  } finally {
    if (bottone) bottone.disabled = false;
  }
}

async function backupRipristina(archivio, bottone) {
  const dove = archivio.profilo || archivio.dati || "l'installazione corrente";
  const conferma = window.confirm(
    "Ripristinare " + archivio.nome + "?\n\n" +
    "I dati di " + dove + " vengono sostituiti da quelli dell'archivio.\n" +
    "Prima di toccare, Orchestra salva lo stato attuale nella cartella backup.");
  if (!conferma) return;
  if (bottone) bottone.disabled = true;
  backupEsito("Ripristino in corso…");
  try {
    const r = await fetch("/api/backup/ripristina", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        archivio: archivio.percorso,
        profilo: archivio.dati || "",
        con_chiavi: backupChiavi(),
      }),
    });
    const d = await r.json();
    if (d.error) {
      backupEsito("Errore: " + d.error);
      return;
    }
    let testo = d.ripristinati + " file ripristinati in " + (d.profilo || d.dati) + ".";
    if (d.chiavi) testo += " Ripristinate anche le chiavi.";
    if (d.sicurezza) testo += " Stato precedente salvato in " + d.sicurezza + ".";
    testo += " Riavvia Orchestra per leggere i dati nuovi.";
    backupEsito(testo);
    await caricaBackup();
  } catch (e) {
    backupEsito("Errore di rete: " + e);
  } finally {
    if (bottone) bottone.disabled = false;
  }
}

(function collegaBackup() {
  const aggiorna = $("backup-aggiorna");
  if (aggiorna) on(aggiorna, "click", caricaBackup);
  const tutte = $("backup-tutte");
  if (tutte) on(tutte, "click", () => backupTutte(tutte));
})();
