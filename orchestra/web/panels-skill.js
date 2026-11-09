(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-skill")<0)window.__diagFiles.push("panels-skill");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-skill");}})();
// ------------------------------------------------------------------ skill
//
// Il pannello delle skill, dentro il modale Capacita'.
//
// Sta qui e non nelle Opzioni perche' e' li' che si va a guardare: tre
// sezioni — quante sono, da dove vengono, e le due liste. Le generate
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

let skillDati = { scaricate: [], generate: [], proposte: [], categorie: [],
                  totale: 0, scaricate_n: 0, generate_n: 0, proposte_n: 0,
                  nel_prompt_max: 0, cestino: [] };

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
        proposte: d.lista_proposte || [],
        categorie: d.categorie || [],
        totale: d.totale || 0,
        scaricate_n: d.scaricate || 0,
        generate_n: d.generate || 0,
        proposte_n: d.proposte || 0,
        nel_prompt_max: d.nel_prompt_max || 0,
        cestino: d.cestino || [],
      };
      disegnaSkill();
    }
  } catch (e) {
    // Le skill non sono un requisito. Se questo fallisce, il modale si
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

function skillCartaProposta(s) {
  // Una proposta ha due pulsanti e non uno: "Apri" da solo lascerebbe
  // il dubbio se accettarla o no, e "Cestino" e' una parola ambigua per
  // una cosa che non esiste ancora. Tieni / Scarta dicono cosa succede.
  const carta = el("div", "skill-carta skill-carta-proposta");
  const capo = el("div", "skill-carta-capo");
  const segno = el("span", "skill-segno");
  segno.textContent = "?";
  segno.title = "proposta: non e' ancora nel prompt";
  capo.appendChild(segno);
  const titolo = el("span", "skill-carta-nome");
  titolo.textContent = s.nome;
  capo.appendChild(titolo);
  carta.appendChild(capo);

  const desc = el("div", "skill-carta-desc");
  desc.textContent = s.descrizione || "(senza descrizione)";
  desc.title = s.descrizione || "";
  carta.appendChild(desc);

  const meta = el("div", "skill-carta-meta");
  meta.textContent = s.con_prove
    ? (s.prove + (s.prove === 1 ? " prova" : " prove") + " · non ancora nel prompt")
    : "senza prove · non ancora nel prompt";
  carta.appendChild(meta);

  const pie = el("div", "skill-carta-pie");
  const apri = el("button", "ghost skill-pulsante");
  apri.textContent = "Apri";
  apri.title = "Leggi la procedura e le prove prima di decidere";
  apri.onclick = () => skillApri(s);
  pie.appendChild(apri);

  const tieni = el("button", "primary skill-pulsante");
  tieni.textContent = "Tieni";
  tieni.title = "Accetta: entra nel prompt quando il compito le somiglia";
  tieni.onclick = () => skillConferma(s.nome);
  pie.appendChild(tieni);

  const scarta = el("button", "ghost skill-pulsante skill-bottone-cancella");
  scarta.textContent = "Scarta";
  scarta.title = "Non serve: va nel cestino e non te la ripropongo";
  scarta.onclick = () => skillScarta(s.nome);
  pie.appendChild(scarta);
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
  skillDati.proposte = elenco.lista_proposte || [];
  skillDati.categorie = elenco.categorie || [];
  skillDati.totale = elenco.totale || 0;
  skillDati.scaricate_n = elenco.scaricate || 0;
  skillDati.generate_n = elenco.generate || 0;
  skillDati.proposte_n = elenco.proposte || 0;
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

// Accettare e scartare. Sono le due azioni che rendono una proposta una
// decisione invece di un file scritto da qualcuno che non sei tu.
async function skillConferma(nome) {
  try {
    const d = await skillPost({ azione: "conferma", nome });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillMossa(nome + " accettata: da ora entra nel prompt quando serve");
    } else {
      skillMossa((d && d.error) || "accettazione rifiutata");
    }
  } catch (e) {
    skillMossa("errore: " + (e.message || e));
  }
}

async function skillScarta(nome) {
  try {
    const d = await skillPost({ azione: "scarta", nome });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillMossa(nome + " scartata: resta nel cestino, non te la ripropongo");
    } else {
      skillMossa((d && d.error) || "scarto rifiutato");
    }
  } catch (e) {
    skillMossa("errore: " + (e.message || e));
  }
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
         + skillDati.generate_n + " imparate dall'agente"
         + (skillDati.proposte_n
            ? ", " + skillDati.proposte_n + " da accettare" : "")
         + " · nel prompt: fino a "
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
    const proposte = skillDati.proposte || [];
    if (proposte.length) {
      // Le proposte stanno in cima e da sole: mescolate alle accettate,
      // una procedura che non e' ancora nel prompt sembrerebbe in uso.
      const tit = el("div", "skill-sottotitolo");
      const s1 = el("span");
      s1.textContent = "Da accettare (" + proposte.length + ")";
      tit.appendChild(s1);
      gen.appendChild(tit);
      for (const s of proposte) gen.appendChild(skillCartaProposta(s));
    }
    if (!skillDati.generate.length && !proposte.length) {
      // Il vuoto e' un messaggio, non uno spazio — e deve dire il vero:
      // prima diceva "lavora con lui e guarda qui dopo", che era falso,
      // perche' nessuno generava niente se non chiamato apposta.
      gen.appendChild(el("div", "skill-vuota",
        "Nessuna ancora. Quando una sequenza di comandi ti funziona " +
        "tre volte, Orchestra te la propone qui: la leggi, la tieni o " +
        "la scarti. Puoi anche chiedergliela: \"salva questa procedura " +
        "come skill\"."));
    } else if (skillDati.generate.length) {
      if (proposte.length) {
        const tit2 = el("div", "skill-sottotitolo");
        const s2 = el("span");
        s2.textContent = "Accettate";
        tit2.appendChild(s2);
        gen.appendChild(tit2);
      }
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
// l'indice di cento skill se poi vai solo a cambiare modello: le skill
// ora si chiedono all'apertura del modale Capacita', che e' il posto
// dove le guardi.

function mostraSezione(nome) {
  const sezioni = document.querySelectorAll(".opz-sez");
  const daMostrare = Array.from(sezioni).find((s) => s.dataset.sez === nome);
  // Una sezione inesistente non deve nascondere tutto: senza questo
  // controllo un nome sbagliato lasciava il pannello vuoto, senza dire
  // perche'. Prima si verifica che esista, poi si tocca il DOM.
  if (!daMostrare) return;
  for (const s of sezioni) {
    const mostra = s.dataset.sez === nome;
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
  // Storico e memoria idem: si caricano quando si aprono, non
  // all'avvio. Caricarli sempre aggiungerebbe due richieste a ogni
  // apertura del pannello Opzioni, anche quando si va a cambiare solo
  // il modello.
  if (nome === "storico") caricaStorico();
  if (nome === "identita") caricaIdentita();
  if (nome === "bot") caricaBot();
  if (nome === "memoria") caricaMemoria();
  if (nome === "remoto") caricaRemoto();
  if (nome === "autostart") caricaAutostart();
  if (nome === "benchmark") { /* il benchmark resta nel suo pannello */ }
  // Il backup si carica quando lo apri: elencare installazioni e archivi
  // all'avvio aggiungerebbe una richiesta (e una scansione di cartelle)
  // a ogni apertura del pannello, anche quando si va solo a cambiare
  // modello.
  if (nome === "backup" && typeof caricaBackup === "function") caricaBackup();
}

function caricaRemoto() {
  const stato = document.getElementById("remoto-stato");
  const corpo = document.getElementById("remoto-corpo");
  // info del server corrente (token)
  fetch("/api/remote/info").then(r => r.json()).then(info => {
    const tok = info.token || "";
    document.getElementById("remoto-token").textContent = tok || "(nessun token - avvia remoto per generarne uno)";
    const copia = document.getElementById("remoto-copia-token");
    if (copia) copia.onclick = () => { navigator.clipboard.writeText(tok); copia.textContent = "copiato"; setTimeout(()=>copia.textContent="Copia",1200); };
  }).catch(() => {});
  // stato del server remoto (lanciato da UI o CLI)
  fetch("/api/remote/status").then(r => r.json()).then(res => {
    const st = res.stato || {};
    if (!res.vivo) {
      stato.textContent = "Server remoto fermo. Premi 'Avvia remoto' o 'Avvia tunnel'.";
      corpo.classList.add("hidden");
      return;
    }
    stato.textContent = "Server remoto attivo (pid " + (st.pid||"") + ").";
    corpo.classList.remove("hidden");
    const urlBox = document.getElementById("remoto-url");
    urlBox.innerHTML = "";
    const urls = [];
    if (st.tunnel_url) urls.push({label:"Tunnel pubblico", url:st.tunnel_url});
    if (st.url) urls.push({label:"Rete locale (LAN)", url:st.url});
    for (const u of urls) {
      const div = document.createElement("div");
      div.style.marginBottom = "4px";
      const a = document.createElement("a");
      a.href = u.url; a.target = "_blank"; a.textContent = u.url;
      div.textContent = u.label + ": ";
      div.appendChild(a);
      urlBox.appendChild(div);
    }
    const qr = document.getElementById("remoto-qr");
    qr.innerHTML = "";
    const target = (st.tunnel_url || st.url || "");
    if (target) {
      const img = document.createElement("img");
      img.src = "https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=" + encodeURIComponent(target);
      img.alt = "QR code";
      img.style.borderRadius = "8px";
      qr.appendChild(img);
      const p = document.createElement("p");
      p.className = "dim small";
      p.textContent = "Scansiona con il telefono per aprire.";
      qr.appendChild(p);
    }
  }).catch(() => {
    stato.textContent = "Impossibile caricare lo stato.";
  });
}

// pulsanti avvia/ferma
(function wireRemotoBtns() {
  const avvia = document.getElementById("remoto-avvia");
  const tunnel = document.getElementById("remoto-tunnel");
  const ferma = document.getElementById("remoto-ferma");
  const stato = document.getElementById("remoto-stato");
  async function start(mode) {
    if (stato) stato.textContent = "Avvio in corso...";
    try {
      const r = await fetch("/api/remote/start", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({mode})});
      const j = await r.json();
      if (!j.ok) { if (stato) stato.textContent = "Errore: " + (j.errore||""); return; }
      caricaRemoto();
      // se tunnel, l'URL pubblico arriva dopo: fai polling
      if (mode === "tunnel") {
        let tries = 0;
        const iv = setInterval(() => {
          tries++;
          caricaRemoto();
          if (tries > 30) clearInterval(iv);
        }, 2000);
      }
    } catch (e) { if (stato) stato.textContent = "Errore di rete."; }
  }
  if (avvia) avvia.addEventListener("click", () => start("remote"));
  if (tunnel) tunnel.addEventListener("click", () => start("tunnel"));
  if (ferma) ferma.addEventListener("click", async () => {
    try { await fetch("/api/remote/stop", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"}); } catch(e){}
    caricaRemoto();
  });
})();

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
