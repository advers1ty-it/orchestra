(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-bot")<0)window.__diagFiles.push("panels-bot");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-bot");}})();
// ---- Bot: identita' persistenti -------------------------------------------
//
// Un bot non e' una seconda applicazione: e' una sessione con un nome, un
// modello, una persona e un progetto. La UI qui fa tre cose sole — scegliere
// chi sta parlando, crearne uno, e dire con chi puo' parlare. Tutto il resto
// (conversazione, storico, profondita' delle chiamate) vive nel server.

let botElenco = [];
let botScelto = 0;
let botAttivoOra = false;
// Il timer che guarda se la chat Telegram si e' collegata. Sta qui e non
// accanto alle funzioni che lo usano perche' `riempiModuloBot` gira anche
// durante il caricamento iniziale, prima che quel blocco sia eseguito.
let tgTimer = null;
// Il nome con cui l'agente principale si presenta. Vuoto = etichetta
// storica "agente principale".
let nomePrincipale = "agente principale";

function aggiornaSelettoriBot() {
  // Con un bot attivo il modello e il servizio arrivano dalla SUA
  // configurazione: cambiarli dal menu in alto sarebbe un comando che
  // sembra funzionare e non cambia quello che stai usando. Si
  // disabilitano, e la nota dice dove si cambiano davvero.
  const bloccato = botAttivoOra;
  const pp = $("provider-pick");
  if (pp) {
    pp.disabled = bloccato;
    pp.title = bloccato ? "Il servizio del bot si cambia da Opzioni → Bot"
                        : "Servizio in uso";
  }
  const mp = $("model-pick");
  if (mp) mp.disabled = bloccato;
  const mb = $("model-btn");
  if (mb) {
    mb.disabled = bloccato;
    mb.title = bloccato ? "Il modello del bot si cambia da Opzioni → Bot"
                        : "Modello in uso";
  }
  const sp = $("scope-pick");
  if (sp) sp.disabled = bloccato;
}

function botNota(testo, errore) {
  const el = $("bot-msg");
  if (!el) return;
  el.textContent = testo || "";
  el.style.color = errore ? "var(--err)" : "var(--muted)";
}

function botNotaLavoro(testo, errore) {
  const el = $("bot-lavoro-msg");
  if (!el) return;
  el.textContent = testo || "";
  el.style.color = errore ? "var(--err)" : "var(--muted)";
}

function riempiModuloBot(b) {
  botScelto = b && b.id ? b.id : 0;
  const campi = {
    "bot-nome": b ? b.nome : "",
    "bot-provider": b ? (b.provider || "") : "",
    "bot-modello": b ? (b.modello || "") : "",
    "bot-progetto": b ? (b.progetto || "") : "",
    "bot-profilo": b ? (b.profilo || "") : "",
    "bot-parla": b ? (b.parla_con || []).join(", ") : "",
    "bot-persona": b ? (b.persona || "") : "",
    "bot-policy-tools": b ? ((b.policy || {}).tools || []).join(", ") : "",
    "bot-policy-nega-tools": b ? ((b.policy || {}).nega_tools || []).join(", ") : "",
    "bot-policy-shell": b ? ((b.policy || {}).shell || []).join(", ") : "",
    "bot-policy-nega-shell": b ? ((b.policy || {}).nega_shell || []).join(", ") : "",
  };
  for (const [id, valore] of Object.entries(campi)) {
    const el = $(id);
    if (el) el.value = valore || "";
  }
  if (typeof tgSvuotaQr === "function") tgSvuotaQr();
  if (typeof caricaTelegram === "function") caricaTelegram();
  botNota(b ? ("modifica " + b.nome) : "");
}

function svuotaModuloBot() {
  riempiModuloBot(null);
  botNota("");
}

function disegnaBot(d) {
  botElenco = d.bots || [];
  const attivo = d.attivo || null;
  botAttivoOra = !!attivo;
  if (d.principale) {
    nomePrincipale = (d.principale.nome || "").trim() || "agente principale";
  }
  aggiornaSelettoriBot();

  const pick = $("bot-pick");
  if (pick) {
    pick.innerHTML = "";
    const base = document.createElement("option");
    base.value = "";
    base.textContent = nomePrincipale;
    pick.appendChild(base);
    for (const b of botElenco) {
      const o = document.createElement("option");
      o.value = String(b.id);
      // Lo stato anche nel menu in testa: se un bot sta lavorando (in
      // background o in un turno che hai lasciato), l'utente lo vede
      // senza aprire Opzioni. Il nome resta il valore; il suffisso e'
      // solo informazione.
      const stato = b.busy ? " · lavora"
        : (b.coda ? " · +" + b.coda : "");
      o.textContent = b.nome + stato;
      if (attivo && String(attivo.id) === String(b.id)) o.selected = true;
      pick.appendChild(o);
    }
    const gest = document.createElement("option");
    gest.value = "__gestisci__";
    gest.textContent = "＋ gestisci bot…";
    pick.appendChild(gest);
  }

  const prov = $("bot-provider");
  if (prov) {
    const scelto = prov.value;
    prov.innerHTML = "";
    const base = document.createElement("option");
    base.value = "";
    base.textContent = "come l'app";
    prov.appendChild(base);
    for (const p of (d.providers || [])) {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      prov.appendChild(o);
    }
    prov.value = scelto || "";
  }

  const prj = $("bot-progetto");
  if (prj) {
    const scelto = prj.value;
    prj.innerHTML = "";
    const base = document.createElement("option");
    base.value = "";
    base.textContent = "nessuno";
    prj.appendChild(base);
    for (const p of (d.progetti || [])) {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      prj.appendChild(o);
    }
    prj.value = scelto || "";
  }

  const el = $("bot-elenco");
  if (!el) return;
  el.innerHTML = "";
  if (!botElenco.length) {
    const p = document.createElement("p");
    p.className = "small dim";
    p.textContent = "Nessun bot. Compila i campi e premi Salva per crearne uno.";
    el.appendChild(p);
    return;
  }
  for (const b of botElenco) {
    const riga = document.createElement("div");
    riga.className = "bot-riga"
      + (attivo && String(attivo.id) === String(b.id) ? " attivo" : "");
    const nome = document.createElement("span");
    nome.className = "bot-nome";
    nome.textContent = b.nome;
    const grow = document.createElement("span");
    grow.className = "grow";
    const sub = document.createElement("span");
    sub.className = "bot-sub";
    const pezzi = [b.provider || "come l'app",
                   b.modello_effettivo || b.modello || "predefinito",
                   b.progetto || "nessun progetto"];
    if (b.parla_con && b.parla_con.length)
      pezzi.push("parla con " + b.parla_con.join(", "));
    if (b.policy && ((b.policy.tools || []).length || (b.policy.shell || []).length
                     || (b.policy.nega_tools || []).length
                     || (b.policy.nega_shell || []).length)) {
      const parti = [];
      if ((b.policy.tools || []).length) parti.push((b.policy.tools || []).length + " tool");
      if ((b.policy.nega_tools || []).length) parti.push((b.policy.nega_tools || []).length + " vietati");
      if ((b.policy.shell || []).length) parti.push("shell: " + (b.policy.shell || []).join(", "));
      if ((b.policy.nega_shell || []).length) parti.push("nega: " + (b.policy.nega_shell || []).join(", "));
      pezzi.push("policy " + parti.join(", "));
    }
    if (b.busy) pezzi.push("al lavoro");
    if (b.coda) pezzi.push("in coda: " + b.coda);
    sub.textContent = pezzi.join(" · ");
    riga.appendChild(nome);
    riga.appendChild(grow);
    riga.appendChild(sub);
    if (b.ultimo) {
      // L'ultima risposta del lavoro in background, in una riga sola.
      // Senza, per sapere com'e' andata bisogna attivare il bot e
      // aprire la conversazione — che e' proprio il passaggio che il
      // lavoro in background voleva evitare.
      const u = document.createElement("div");
      const stato = b.ultimo.stato || (b.ultimo.ok ? "completato" : "fallito");
      const esito = b.ultimo.ok && b.ultimo.risposta
        ? "ultimo: " + b.ultimo.risposta.slice(0, 120)
        : stato + ": " + (b.ultimo.errore || "nessun risultato").slice(0, 120);
      u.className = "bot-ultimo" + (b.ultimo.ok ? "" : " err");
      u.textContent = esito;
      u.title = b.ultimo.risposta || b.ultimo.errore || "";
      riga.appendChild(u);
    }
    if (b.ultimo && b.ultimo.worktree && !b.ultimo.worktree.scartato) {
      // Dove sono finiti i file del lavoro. Senza questa riga il bot
      // scriverebbe "fatto" e l'utente non saprebbe dove guardare: il
      // progetto aperto non contiene niente, ed e' il punto.
      const wt = b.ultimo.worktree;
      const w = document.createElement("div");
      w.className = "bot-worktree";
      w.textContent = "isolato: " + (wt.branch || "ramo") + " · "
        + (wt.radice || wt.percorso || "");
      w.title = wt.unisci ? "per unire: " + wt.unisci : "";
      riga.appendChild(w);
      const scarta = document.createElement("button");
      scarta.className = "ghost bot-riprova";
      scarta.textContent = "Scarta checkout";
      scarta.addEventListener("click", (ev) => {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        scartaCheckoutBot(b.ultimo.id);
      });
      riga.appendChild(scarta);
    } else if (b.in_corso_worktree) {
      const wt = b.in_corso_worktree;
      const w = document.createElement("div");
      w.className = "bot-worktree";
      w.textContent = "isolato in corso: " + (wt.branch || "ramo");
      w.title = wt.radice || "";
      riga.appendChild(w);
    }
    if (b.ultimo && b.ultimo.merge && b.ultimo.merge.pronto
        && !(b.ultimo.worktree && b.ultimo.worktree.scartato)) {
      // Il bot ha dichiarato di aver finito E verificato. La verifica e'
      // quella che ha scritto: si vede nel tooltip prima di decidere.
      const m = b.ultimo.merge;
      const rigaM = document.createElement("div");
      rigaM.className = "bot-merge" + (m.unito ? " unito" : "");
      if (m.unito) {
        rigaM.textContent = "unito nel progetto"
          + (m.commit ? ": " + String(m.commit).slice(0, 8) : "");
        rigaM.title = m.verifica || "";
      } else {
        rigaM.textContent = "pronto per il merge: "
          + (m.riepilogo || "modifiche verificate").slice(0, 120);
        rigaM.title = m.verifica || "";
      }
      riga.appendChild(rigaM);
      if (!m.unito) {
        const btn = document.createElement("button");
        btn.className = "ghost bot-riprova";
        btn.textContent = "Unisci";
        btn.title = m.verifica || "";
        btn.addEventListener("click", (ev) => {
          if (ev && ev.stopPropagation) ev.stopPropagation();
          unisciLavoroBot(b.ultimo.id);
        });
        riga.appendChild(btn);
      }
    }
    if (b.riprovabile) {
      // Un lavoro interrotto dal riavvio non deve sparire: e' proprio
      // quello che l'esecuzione durevole e' venuta a salvare. Il
      // pulsante lo rimette in coda senza doverlo riscrivere.
      if (!b.ultimo || b.riprovabile.id !== b.ultimo.id) {
        const r = document.createElement("div");
        r.className = "bot-ultimo err";
        r.textContent = "da riprovare: "
          + ((b.riprovabile.errore || b.riprovabile.testo || "")
             .slice(0, 100));
        riga.appendChild(r);
      }
      if (b.riprovabile.worktree && !b.riprovabile.worktree.scartato
          && (!b.ultimo || b.riprovabile.id !== b.ultimo.id)) {
        // Il checkout del lavoro da riprovare: senza questa riga, dopo
        // un nuovo tentativo quello vecchio sparirebbe dal pannello e
        // resterebbe su disco per sempre.
        const vecchio = document.createElement("div");
        vecchio.className = "bot-worktree";
        vecchio.textContent = "checkout da riprovare: "
          + (b.riprovabile.worktree.branch || "ramo");
        vecchio.title = b.riprovabile.worktree.radice || "";
        riga.appendChild(vecchio);
        const scartaVecchio = document.createElement("button");
        scartaVecchio.className = "ghost bot-riprova";
        scartaVecchio.textContent = "Scarta checkout";
        scartaVecchio.addEventListener("click", (ev) => {
          if (ev && ev.stopPropagation) ev.stopPropagation();
          scartaCheckoutBot(b.riprovabile.id);
        });
        riga.appendChild(scartaVecchio);
      }
      const btn = document.createElement("button");
      btn.className = "ghost bot-riprova";
      btn.textContent = "Riprova";
      btn.addEventListener("click", (ev) => {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        riprovaLavoroBot(b.riprovabile.id);
      });
      riga.appendChild(btn);
    }
    if (b.in_corso_id) {
      // La coda e' su disco: un lavoro puo' restare in corso anche se la
      // conversazione non e' quella attiva. Senza questo pulsante l'unico
      // modo di fermarlo sarebbe aspettare o chiudere il server.
      const btn = document.createElement("button");
      btn.className = "ghost bot-riprova";
      btn.textContent = "Annulla lavoro";
      btn.addEventListener("click", (ev) => {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        annullaLavoroBot(b.in_corso_id);
      });
      riga.appendChild(btn);
    }
    riga.addEventListener("click", () => riempiModuloBot(b));
    el.appendChild(riga);
  }
}

async function caricaBot() {
  if (!$("bot-elenco") && !$("bot-pick")) return;
  try {
    const r = await fetch("/api/bots");
    const d = await r.json();
    if (d.error) { botNota(d.error, true); return; }
    disegnaBot(d);
  } catch (e) {
    botNota("non riesco a caricare i bot", true);
  }
}

function listaDaCampo(id) {
  return ($(id).value || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function datiModuloBot() {
  const parla = ($("bot-parla").value || "")
    .split(",").map((s) => s.trim()).filter(Boolean);
  return {
    nome: ($("bot-nome").value || "").trim(),
    provider: $("bot-provider").value || "",
    modello: ($("bot-modello").value || "").trim(),
    progetto: $("bot-progetto").value || "",
    profilo: $("bot-profilo").value || "",
    persona: $("bot-persona").value || "",
    parla_con: parla,
    policy: {
      tools: listaDaCampo("bot-policy-tools"),
      nega_tools: listaDaCampo("bot-policy-nega-tools"),
      shell: listaDaCampo("bot-policy-shell"),
      nega_shell: listaDaCampo("bot-policy-nega-shell"),
    },
  };
}

async function salvaBot() {
  const body = datiModuloBot();
  if (!body.nome) { botNota("serve un nome per il bot", true); return; }
  const url = botScelto ? "/api/bots/aggiorna" : "/api/bots/crea";
  if (botScelto) body.id = botScelto;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.error) { botNota(d.error, true); return; }
    botNota(botScelto ? "bot aggiornato" : "bot creato");
    await caricaBot();
    if (d.bot) riempiModuloBot(d.bot);
  } catch (e) {
    botNota("errore di rete: il bot non e' stato salvato", true);
  }
}

function identitaNota(testo, errore) {
  const el = $("identita-msg");
  if (!el) return;
  el.textContent = testo || "";
  el.style.color = errore ? "var(--err)" : "var(--muted)";
}

async function caricaIdentita() {
  if (!$("identita-nome") && !$("identita-persona")) return;
  try {
    const r = await fetch("/api/identita");
    const d = await r.json();
    if (d.error) { identitaNota(d.error, true); return; }
    if ($("identita-nome")) $("identita-nome").value = d.nome || "";
    if ($("identita-persona")) $("identita-persona").value = d.persona || "";
    nomePrincipale = (d.nome || "").trim() || "agente principale";
    identitaNota("");
  } catch (e) {
    identitaNota("non riesco a leggere l'identità", true);
  }
}

async function salvaIdentita() {
  const body = {
    nome: ($("identita-nome").value || "").trim(),
    persona: ($("identita-persona").value || "").trim(),
  };
  try {
    const r = await fetch("/api/identita", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.error) { identitaNota(d.error, true); return; }
    nomePrincipale = (d.nome || "").trim() || "agente principale";
    identitaNota("identità salvata");
    // Il menu in testa e la nota di attivazione leggono dai bot: si
    // ricarica anche quello, altrimenti il nome nuovo resta invisibile
    // finche' non si riapre la pagina.
    await caricaBot();
  } catch (e) {
    identitaNota("errore di rete: identità non salvata", true);
  }
}

async function avviaLavoroBot() {
  if (!botScelto) { botNotaLavoro("scegli un bot dalla lista", true); return; }
  const testo = ($("bot-compito").value || "").trim();
  if (!testo) {
    botNotaLavoro("scrivi il compito da affidare al bot", true);
    return;
  }
  try {
    const r = await fetch("/api/bots/avvia", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: botScelto, testo: testo }),
    });
    const d = await r.json();
    if (d.error) { botNotaLavoro(d.error, true); return; }
    $("bot-compito").value = "";
    botNotaLavoro("avviato: " + (d.in_coda || 1) + " in coda");
    await caricaBot();
  } catch (e) {
    botNotaLavoro("errore di rete: il lavoro non e' partito", true);
  }
}

async function aggiornaStatoBot() {
  await caricaBot();
  botNotaLavoro("stato aggiornato");
}

async function riprovaLavoroBot(id) {
  if (!id) return;
  try {
    const r = await fetch("/api/lavori/riprova", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id }),
    });
    const d = await r.json();
    if (d.error) { botNotaLavoro(d.error, true); return; }
    botNotaLavoro("lavoro rimesso in coda");
    await caricaBot();
  } catch (e) {
    botNotaLavoro("errore di rete: il lavoro non e' stato riprovato", true);
  }
}

async function annullaLavoroBot(id) {
  if (!id) return;
  try {
    const r = await fetch("/api/lavori/annulla", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id }),
    });
    const d = await r.json();
    if (d.error) { botNotaLavoro(d.error, true); return; }
    botNotaLavoro("lavoro annullato");
    await caricaBot();
  } catch (e) {
    botNotaLavoro("errore di rete: il lavoro non e' stato annullato", true);
  }
}

async function unisciLavoroBot(id) {
  if (!id) return;
  if (!confirm("Unire il ramo del bot nel progetto? Il progetto deve "
      + "essere senza modifiche non committate. In caso di conflitto "
      + "il merge viene annullato.")) return;
  try {
    const r = await fetch("/api/lavori/unisci", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id }),
    });
    const d = await r.json();
    if (d.error) { botNotaLavoro(d.error, true); return; }
    botNotaLavoro(d.gia_unito ? "era gia' unito" : "ramo unito nel progetto");
    await caricaBot();
  } catch (e) {
    botNotaLavoro("errore di rete: merge non eseguito", true);
  }
}

async function scartaCheckoutBot(id) {
  if (!id) return;
  if (!confirm("Scartare il checkout isolato? Le modifiche non "
      + "committate del bot andranno perse.")) return;
  try {
    const r = await fetch("/api/lavori/scarta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id }),
    });
    const d = await r.json();
    if (d.error) { botNotaLavoro(d.error, true); return; }
    botNotaLavoro("checkout scartato");
    await caricaBot();
  } catch (e) {
    botNotaLavoro("errore di rete: checkout non scartato", true);
  }
}

async function attivaBotDaId(id) {
  try {
    const r = await fetch("/api/bots/attiva", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id || null }),
    });
    const d = await r.json();
    if (d.error) {
      botNota(d.error, true);
      if (typeof addNote === "function") addNote(d.error);
      return;
    }
    const nome = d.bot ? d.bot.nome : nomePrincipale;
    if (typeof addNote === "function") addNote("ora parli con " + nome);
    // La connessione SSE e' legata alla sessione: senza riconnettere,
    // continuerebbe a mostrare gli eventi del bot precedente mentre la
    // chat e' gia' passata all'altro. La riconnessione manda anche lo
    // snapshot nuovo, quindi il log si ricostruisce da solo.
    if (typeof connect === "function") connect();
    caricaBot();
    if (typeof caricaProgetto === "function") caricaProgetto();
    if (typeof caricaSideSessioni === "function") caricaSideSessioni();
  } catch (e) {
    botNota("errore di rete: cambio bot non riuscito", true);
  }
}

async function attivaBotScelto() {
  if (!botScelto) { botNota("scegli un bot dalla lista", true); return; }
  await attivaBotDaId(botScelto);
}

async function eliminaBotScelto() {
  if (!botScelto) { botNota("scegli un bot dalla lista", true); return; }
  const b = botElenco.find((x) => String(x.id) === String(botScelto));
  if (!b) return;
  if (!confirm("Eliminare il bot «" + b.nome + "»? La conversazione resta "
               + "nella cronologia, ma l'identita' non esiste piu'.")) return;
  try {
    const r = await fetch("/api/bots/elimina", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: botScelto }),
    });
    const d = await r.json();
    if (d.error) { botNota(d.error, true); return; }
    svuotaModuloBot();
    await caricaBot();
    if (typeof connect === "function") connect();
    botNota("bot eliminato");
  } catch (e) {
    botNota("errore di rete: il bot non e' stato eliminato", true);
  }
}

// ---- Telegram: lo stesso bot, scritto dal telefono -------------------------
//
// Tre passi, nell'ordine in cui vanno fatti: il token di @BotFather, il QR da
// inquadrare, e la chat che da quel momento riceve le risposte. Il QR lo
// disegna il server (`orchestra/qr.py`): il codice di collegamento non passa
// per un servizio esterno, perche' chi lo legge puo' collegarsi al bot.
//
// Il token non torna mai indietro dal server: il campo resta vuoto anche
// dopo averlo salvato, e mostra solo "token salvato". Un token che si puo'
// rileggere dal browser e' un token che finisce in uno screenshot.

function tgNota(testo, errore) {
  const el = $("tg-stato");
  if (!el) return;
  el.textContent = testo || "";
  // Come `botNota`: il colore dell'errore e' una variabile del tema, non
  // una classe che nessun foglio di stile definisce.
  el.style.color = errore ? "var(--err)" : "var(--muted)";
}

function tgSvuotaQr() {
  const box = $("tg-qr");
  if (box) box.innerHTML = "";
  if (tgTimer) { clearInterval(tgTimer); tgTimer = null; }
}

async function caricaTelegram() {
  if (!$("tg-stato")) return;
  if (!botScelto) {
    tgNota("salva il bot, poi collega Telegram");
    return;
  }
  try {
    const r = await fetch("/api/telegram");
    const d = await r.json();
    if (d.error) { tgNota(d.error, true); return; }
    const v = (d.bots || []).find((x) => String(x.bot_id) === String(botScelto));
    if (!v) { tgNota("stato Telegram non disponibile", true); return; }
    if (!v.token) {
      tgNota("nessun token: incolla qui sotto quello di @BotFather");
      return;
    }
    const pezzi = ["bot @" + (v.username || "?")];
    pezzi.push(v.collegato ? ("chat collegata: " + v.chat)
                           : "nessuna chat collegata");
    pezzi.push(v.attivo ? "in ascolto" : "non in ascolto");
    tgNota(pezzi.join(" · "));
  } catch (e) {
    tgNota("non riesco a leggere lo stato Telegram", true);
  }
}

async function chiamaTelegram(percorso, corpo) {
  const r = await fetch(percorso, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo || {}),
  });
  return r.json();
}

async function salvaTokenTelegram() {
  if (!botScelto) { tgNota("scegli un bot dalla lista", true); return; }
  const campo = $("tg-token");
  const token = (campo && campo.value || "").trim();
  if (!token) { tgNota("incolla il token di @BotFather", true); return; }
  tgNota("verifico il token con Telegram...");
  try {
    const d = await chiamaTelegram("/api/telegram/token",
                                   { id: botScelto, token: token });
    if (d.error) { tgNota(d.error, true); return; }
    if (campo) campo.value = "";
    await caricaTelegram();
  } catch (e) {
    tgNota("errore di rete: token non salvato", true);
  }
}

async function togliTokenTelegram() {
  if (!botScelto) { tgNota("scegli un bot dalla lista", true); return; }
  if (!confirm("Togliere il token Telegram a questo bot? La chat smette "
               + "di ricevere risposte.")) return;
  try {
    const d = await chiamaTelegram("/api/telegram/token",
                                   { id: botScelto, token: "" });
    if (d.error) { tgNota(d.error, true); return; }
    tgSvuotaQr();
    await caricaTelegram();
  } catch (e) {
    tgNota("errore di rete: token non tolto", true);
  }
}

function tgDisegnaQr(d) {
  const box = $("tg-qr");
  if (!box) return;
  box.innerHTML = "";
  const img = document.createElement("img");
  img.alt = "codice per collegare questa chat";
  // SVG dentro un data URI: nessuna richiesta a un servizio esterno, e
  // nessuna immagine da salvare su disco per mostrarne una.
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(d.svg);
  img.style.width = "196px";
  img.style.height = "196px";
  img.style.background = "#fff";
  img.style.padding = "8px";
  img.style.borderRadius = "10px";
  box.appendChild(img);
  const p = document.createElement("p");
  p.className = "small dim";
  p.style.margin = "6px 0 0";
  p.textContent = "Inquadra con il telefono, oppure apri " + d.link
    + ". Il codice vale dieci minuti e una volta sola.";
  box.appendChild(p);
}

async function collegaTelegram() {
  if (!botScelto) { tgNota("scegli un bot dalla lista", true); return; }
  tgNota("preparo il codice...");
  try {
    const d = await chiamaTelegram("/api/telegram/collega", { id: botScelto });
    if (d.error) { tgNota(d.error, true); return; }
    tgDisegnaQr(d);
    tgNota("in attesa che una chat mandi il codice...");
    // Il collegamento avviene dall'altra parte (il telefono scrive al
    // bot), quindi qui si guarda e basta: nessun pulsante da premere
    // quando arriva.
    const scadenza = Date.now() + 10 * 60 * 1000;
    if (tgTimer) clearInterval(tgTimer);
    tgTimer = setInterval(async () => {
      if (Date.now() > scadenza) {
        clearInterval(tgTimer);
        tgTimer = null;
        tgNota("il codice e' scaduto: rigeneralo", true);
        return;
      }
      await caricaTelegram();
      const testo = ($("tg-stato") && $("tg-stato").textContent) || "";
      if (testo.indexOf("chat collegata:") >= 0) {
        clearInterval(tgTimer);
        tgTimer = null;
        tgSvuotaQr();
        await caricaTelegram();
      }
    }, 3000);
  } catch (e) {
    tgNota("errore di rete: codice non generato", true);
  }
}

async function scollegaTelegram() {
  if (!botScelto) { tgNota("scegli un bot dalla lista", true); return; }
  try {
    const d = await chiamaTelegram("/api/telegram/scollega", { id: botScelto });
    if (d.error) { tgNota(d.error, true); return; }
    tgSvuotaQr();
    await caricaTelegram();
  } catch (e) {
    tgNota("errore di rete: chat non scollegata", true);
  }
}


(function collegaBot() {
  const pick = $("bot-pick");
  if (pick) {
    pick.addEventListener("change", async () => {
      const v = pick.value;
      if (v === "__gestisci__") {
        if (typeof apriOpzioni === "function") apriOpzioni();
        if (typeof mostraSezione === "function") mostraSezione("bot");
        caricaBot();
        return;
      }
      await attivaBotDaId(v ? parseInt(v, 10) : null);
    });
  }
  // Gli elementi si prendono una volta e si controllano prima di
  // agganciare: un listener su null uccide il resto del bundle, e in un
  // file concatenato "il resto" sono tutte le funzioni dopo questa riga.
  const btnNuovo = $("bot-nuovo");
  const btnSalva = $("bot-salva");
  const btnAttiva = $("bot-attiva");
  const btnElimina = $("bot-elimina");
  const btnAvvia = $("bot-avvia");
  const btnStato = $("bot-stato");
  const btnIdentita = $("identita-salva");
  if (btnIdentita) btnIdentita.addEventListener("click", salvaIdentita);
  if (btnNuovo) btnNuovo.addEventListener("click", svuotaModuloBot);
  if (btnSalva) btnSalva.addEventListener("click", salvaBot);
  if (btnAttiva) btnAttiva.addEventListener("click", attivaBotScelto);
  if (btnElimina) btnElimina.addEventListener("click", eliminaBotScelto);
  if (btnAvvia) btnAvvia.addEventListener("click", avviaLavoroBot);
  if (btnStato) btnStato.addEventListener("click", aggiornaStatoBot);
  const btToken = $("tg-salva");
  const btTogli = $("tg-togli");
  const btCollega = $("tg-collega");
  const btScollega = $("tg-scollega");
  if (btToken) btToken.addEventListener("click", salvaTokenTelegram);
  if (btTogli) btTogli.addEventListener("click", togliTokenTelegram);
  if (btCollega) btCollega.addEventListener("click", collegaTelegram);
  if (btScollega) btScollega.addEventListener("click", scollegaTelegram);
  // Riempie il menu in testa e la lista del pannello. Se i bot non ci sono
  // ancora, la richiesta torna vuota e non si vede niente: nessun errore.
  caricaBot();
})();
