(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-lavoro")<0)window.__diagFiles.push("panels-lavoro");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-lavoro");}})();
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
  for (const p of st.sempre || []) {
    const riga = aggiungi("Sempre concesso: " + p, "ok");
    const rev = el("button", "ghost piccolo", "Revoca");
    riga.appendChild(rev);
    on(rev, "click", async () => {
      try {
        const r = await fetch("/api/permessi", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revoca: p }),
        });
        const d = await r.json();
        disegnaPermessi(d.stato || st);
      } catch (e) { /* resta com'e' */ }
    });
  }
  for (const p of st.negati || []) {
    const riga = aggiungi("Negato: " + p, "ko");
    const dim = el("button", "ghost piccolo", "Dimentica");
    dim.title = "Dimentica il 'mai': la prossima volta chiede di nuovo";
    riga.appendChild(dim);
    on(dim, "click", async () => {
      try {
        const r = await fetch("/api/permessi", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revoca: p }),
        });
        const d = await r.json();
        disegnaPermessi(d.stato || st);
      } catch (e) { /* resta com'e' */ }
    });
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
    if (d.in_attesa) {
      permessiMsg.textContent = "domanda partita: dovrebbe comparire il riquadro";
    } else {
      // La diagnosi del server dice perche': valutazione, canale
      // assente, errore. Senza, "non funziona" e' una pista cieca.
      const g = d.diagnosi || {};
      const perche = g.errore ? "errore: " + g.errore
        : g.valuta && g.valuta !== "chiedi" ? "valutazione: " + g.valuta + " (non si chiede proprio)"
        : g.ha_chiedi === false ? "canale assente: il server non puo' chiedere (riavvialo)"
        : "domanda partita e rientrata subito: ricarica con Ctrl+F5, la pagina è vecchia";
      permessiMsg.textContent = "nessun riquadro: " + perche;
    }
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


// Le liste dei servizi e delle chiavi. Stanno qui e non in
// panels-opzioni.js perche' e' qui che vengono disegnate: una costante
// in un file e il suo uso in un altro e' il modo per lasciare, un
// giorno, un selettore che punta a un id che non esiste piu'.
const serviziLista = $("servizi-lista");
const serviziRiepilogo = $("servizi-riepilogo");
const opzioniNota = $("opzioni-nota");

// riga di una chiave: stato, campo vuoto, due pulsanti. `senzaNome` serve
// quando la riga sta dentro la scheda di un servizio: li' il nome e la
// descrizione ci sono gia' sopra, e ripeterlo e' rumore.
function rigaChiave(k, senzaNome) {
  const riga = el("div", senzaNome ? "chiave-campo" : "chiave-riga");
  const testa = el("div", "chiave-testa");
  if (!senzaNome) {
    const nome = el("span", "chiave-nome");
    nome.textContent = k.etichetta;
    testa.appendChild(nome);
  }
  const statoEl = el("span", "chiave-stato " + (k.presente ? "ok" : "vuota"));
  // Solo le chiavi si nascondono mentre si scrivono. Un indirizzo o un
  // numero di secondi no: nasconderli rende impossibile accorgersi di un
  // errore di battitura, che e' l'unico motivo per cui li guardi.
  const segreta = /(_API_KEY|_TOKEN|_KEY)$/.test(k.chiave);
  // l'indizio sono 4 caratteri, mai di piu': serve a distinguere due
  // chiavi, non a usarne una. E il testo cambia con la cosa: "manca la
  // chiave" su un indirizzo locale o su un numero di secondi e' falso,
  // e fa cercare una credenziale che non esiste.
  statoEl.textContent = k.presente
    ? ((segreta ? "configurata " : "impostato: ") + k.indizio)
    : (segreta ? "manca la chiave" : "non impostato");
  testa.appendChild(statoEl);

  const campo = el("input", "chiave-input");
  campo.type = segreta ? "password" : "text";
  campo.placeholder = k.presente
    ? (segreta ? "lascia vuoto per non cambiarla" : "lascia vuoto per non cambiarlo")
    : (segreta ? "incolla qui la chiave" : "scrivi il valore");
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
        if (d.ready && (typeof ready !== "undefined" && !ready)) location.reload();
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

// scheda di un servizio: cosa offre, cosa costa, come iniziare e — se
// il servizio ha una chiave — il campo per metterla. Descrizione e
// campo stanno nella stessa scheda perche' rispondono alla stessa
// domanda: "questo che cos'e', e cosa mi serve per usarlo?".
function schedaServizio(s, chiave) {
  const d = el("div", "gratis-scheda" +
    (chiave && chiave.presente ? " pronta" : (s.chiave ? "" : " senza-chiave")));
  const capo = el("div", "gratis-capo");
  const nome = el("span", "gratis-nome");
  nome.textContent = s.nome;
  const badge = el("span", "gratis-badge " + (s.chiave ? "con-chiave" : "senza-chiave"));
  badge.textContent = s.chiave ? "serve account" : "nessuna chiave";
  if (s.id === "nous" && s.connesso) {
    // Nous non usa chiavi: collegato via Orchestra. Il server lo dice
    // con "connesso", e il badge lo mostra invece di "nessuna chiave".
    badge.textContent = "collegato";
    badge.className = "gratis-badge senza-chiave";
  } else if (chiave && chiave.presente) {
    // La chiave c'e' e il servizio e' pronto: e' la cosa che si vuole
    // sapere per prima guardando la scheda.
    badge.textContent = "pronto";
    badge.className = "gratis-badge con-chiave";
  }
  capo.appendChild(nome);
  capo.appendChild(badge);

  const costo = el("div", "gratis-costo");
  costo.textContent = s.costo;
  const cosa = el("div", "gratis-cosa");
  cosa.textContent = s.cosa;
  const req = el("div", "gratis-req dim small");
  req.textContent = s.requisiti;
  // Dove si prende la chiave: se il testo e' un indirizzo deve essere
  // cliccabile. Prima era un <code>, e un dominio scritto in un blocco
  // di codice sembra qualcosa da copiare a mano invece di un link.
  const dove = (s.come || "").trim();
  const eUrl = /^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(dove);
  const come = el(eUrl ? "a" : "span", "gratis-come");
  come.textContent = dove;
  if (eUrl) {
    come.href = "https://" + dove;
    come.target = "_blank";
    // noopener: la pagina che si apre non deve poter guidare questa
    // finestra. E' l'errore classico con target="_blank".
    come.rel = "noopener noreferrer";
  }

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
  // Il campo della chiave, sotto la descrizione del servizio che la usa.
  if (chiave) d.appendChild(rigaChiave(chiave, true));
  if (s.id === "nous") {
    const box = el("div", "nous-auth");
    const stato = el("span", "dim small");
    const gia = !!s.connesso;
    stato.textContent = gia ? "collegato — se qualcosa non va, ricollega" : "per collegare: usa il pulsante e conferma nel browser";
    const btn = el("button", "primary", gia ? "Ricollega" : "Collega Nous");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      stato.textContent = "avvio…";
      try {
        // Ricollega deve ripartire da zero: senza force, il server
        // vede il token vecchio e risponde "già collegato" — il
        // bottone sembrava solo ricaricare la pagina.
        const corpo = gia ? { force: true } : {};
        const r = await fetch("/api/nous/auth/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(corpo),
        });
        const dd = await leggiJson(r);
        if (!r.ok) {
          stato.textContent = "errore: " + (dd.error || r.status);
          btn.disabled = false;
          return;
        }
        if (dd.connected) {
          stato.textContent = "già collegato";
                    caricaOpzioni();
                    if (typeof ready !== "undefined" && !ready) location.reload();
          btn.disabled = false;
          return;
        }
        try { window.open(dd.verification_url, "_blank"); } catch (e) {}
        stato.textContent = "codice " + dd.user_code + " — conferma nel browser…";
        const poll = async () => {
          const rr = await fetch("/api/nous/auth/status");
          const d2 = await leggiJson(rr);
          if (d2.connected) {
            stato.textContent = "collegato";
            caricaOpzioni();
            if (typeof ready !== "undefined" && !ready) location.reload();
            btn.disabled = false;
            return;
          }
          if (d2.error) {
            stato.textContent = "errore: " + d2.error;
            btn.disabled = false;
            return;
          }
          setTimeout(poll, 3000);
        };
        setTimeout(poll, 3000);
      } catch (e) {
        stato.textContent = "connessione fallita: " + e;
        btn.disabled = false;
      }
    });
    box.appendChild(btn);
    box.appendChild(stato);
    if (gia) {
      const scollega = el("button", "ghost", "Scollega");
      scollega.title = "Dimentica il collegamento (la chiave manuale in .env resta)";
      scollega.addEventListener("click", async () => {
        if (!confirm("Scollegare Nous Research da questo computer?")) return;
        scollega.disabled = true;
        try {
          const r = await fetch("/api/nous/auth/disconnect", { method: "POST" });
          const dd = await leggiJson(r);
          if (!r.ok || !dd.disconnected) {
            stato.textContent = "errore: " + (dd.error || "niente da scollegare");
            scollega.disabled = false;
            return;
          }
          stato.textContent = "scollegato";
          caricaOpzioni();
        } catch (e) {
          stato.textContent = "connessione fallita: " + e;
          scollega.disabled = false;
        }
      });
      box.appendChild(scollega);
    }
    d.appendChild(box);
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

if (optToolProfile) {
  optToolProfile.addEventListener("change", async () => {
    try {
      const r = await fetch("/api/tools/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: optToolProfile.value || null }),
      });
      const dd = await r.json();
      if (!r.ok) throw new Error(dd.error || ("HTTP " + r.status));
    } catch (e) {
      console.warn("profilo strumenti:", e);
    }
  });
}

// I gruppi come li legge chi apre il pannello: gratis, a pagamento,
// sul tuo computer. I nomi nei dati sono piu' fini — un servizio gratis
// "con chiave" e uno "a collegamento diretto" sono due cose diverse per
// chi li implementa, non per chi li usa.
const GRUPPI_SERVIZI = [
  { nome: "Gratis", da: ["Gratis con chiave", "Collegamento diretto"] },
  { nome: "A pagamento", da: ["A pagamento"] },
  { nome: "Sul tuo computer", da: ["Sul tuo computer"] },
];

// Una chiave che non e' un servizio: un'impostazione, o una chiave per
// un pezzo che non compare fra i servizi. Resta visibile e modificabile:
// un campo che c'era e sparisce fa pensare che la chiave sia stata
// cancellata.
function schedaChiave(k) {
  const d = el("div", "gratis-scheda senza-chiave");
  const capo = el("div", "gratis-capo");
  capo.appendChild(el("span", "gratis-nome", k.etichetta));
  d.appendChild(capo);
  d.appendChild(rigaChiave(k, true));
  return d;
}

async function caricaOpzioni() {
  const mia = ++generazioneChiavi;
  if (serviziLista) serviziLista.replaceChildren();
  if (serviziRiepilogo) serviziRiepilogo.textContent = "";
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
    if (optToolProfile) {
      optToolProfile.value = d.tool_profile || "";
    }

    caricaPermessi();
    caricaAutostart();
    // Le skill anche. Una chiamata in piu' a /api/skill durante
    // l'apertura del pannello, e su 103 file la costruzione dell'indice
    // richiede qualche decimo di secondo: per quello NON aspetta il
    // resto del pannello. Se il server non risponde, la sezione resta
    // muta e Opzioni funziona lo stesso.
    caricaSkill();

    // provider e modello: due menu in alto, non due righe di chiavi
    disegnaProvider(d);
    // Il modello vero preselezionato, non il primo free: senza, aprire
    // il pannello (o ricaricarlo dopo un cambio) rimette il menu sul
    // primo free e sembra che il cambio non abbia funzionato — mentre
    // il server ha già cambiato e risponde col modello nuovo.
    caricaModelli(d.provider || optProvider.value, d.model || null);

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
    if (cat.modelli && serviziRiepilogo) {
      serviziRiepilogo.textContent = "Catalogo attuale: " + cat.modelli +
        " modelli, " + (cat.gratuiti || 0) + " gratuiti con tool-calling.";
    }

    // Un elenco solo, in tre gruppi. Prima erano due sezioni e la stessa
    // cosa stava in tutte e due: il campo della chiave in una, la
    // descrizione del servizio nell'altra. Chi voleva sapere cosa fosse
    // NVIDIA doveva cambiare sezione, e chi metteva una chiave non
    // sapeva cosa stava attivando.
    const schede = d.servizi_gratis || [];
    const chiavi = d.chiavi || [];
    const usate = new Set();
    const dentroUnGruppo = new Set();
    for (const g of GRUPPI_SERVIZI) for (const n of g.da) dentroUnGruppo.add(n);

    for (const gruppo of GRUPPI_SERVIZI) {
      const del = schede
        .filter((s) => gruppo.da.includes(s.gruppo || "Gratis con chiave"))
        // Prima quelli che funzionano senza niente: sono la risposta a
        // "da dove parto", che e' la prima domanda di chi apre questa
        // sezione. Chi ha gia' una chiave sa gia' cosa cerca.
        .sort((a, b) => (a.chiave ? 1 : 0) - (b.chiave ? 1 : 0));
      if (!del.length) continue;
      serviziLista.appendChild(el("div", "gratis-gruppo", gruppo.nome));
      for (const s of del) {
        const k = chiavi.find((x) => x.chiave === s.env) || null;
        if (k) usate.add(k.chiave);
        serviziLista.appendChild(schedaServizio(s, k));
      }
    }
    // Un servizio con un gruppo che non conosciamo non sparisce.
    for (const s of schede.filter((x) => !dentroUnGruppo.has(x.gruppo || "Gratis con chiave"))) {
      const k = chiavi.find((x) => x.chiave === s.env) || null;
      if (k) usate.add(k.chiave);
      serviziLista.appendChild(schedaServizio(s, k));
    }

    // Le chiavi che non appartengono a nessun servizio (impostazioni e
    // token di servizi esterni) in fondo, con il loro campo.
    const altre = chiavi.filter((k) => !usate.has(k.chiave));
    if (altre.length) {
      serviziLista.appendChild(el("div", "gratis-gruppo", "Altre chiavi"));
      for (const k of altre) serviziLista.appendChild(schedaChiave(k));
    }
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
  const attuale = (typeof modelPick !== "undefined" && modelPick) ? modelPick.value : "";
  return tuttiModelli
    .filter((m) => typeof (m.scores || {})[scope] === "number")
    .sort((a, b) => {
      const d = b.scores[scope] - a.scores[scope];
      if (d !== 0) return d;
      // a parità di punteggio non spostare chi è già in uso: non c'è
      // miglioramento reale da proporre
      const aAtt = a.id === attuale ? 0 : 1;
      const bAtt = b.id === attuale ? 0 : 1;
      if (aAtt !== bAtt) return aAtt - bAtt;
      return String(a.id).localeCompare(String(b.id));
    });
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
  const punteggioAttuale = (attuale && (tuttiModelli.find((m) => m.id === attuale) || {}).scores || {})[scope];
  // a parità (o se l'attuale ha già il massimo) non c'è motivo di proporre
  // un cambio: spostarsi su un modello con lo stesso punteggio non migliora
  // nulla e genera confusione
  if (attuale === best.id ||
      (typeof punteggioAttuale === "number" && punteggioAttuale >= best.scores[scope])) {
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

// Interruttore dell'automatico: la scelta manuale dal menu in alto lo
// spegne, da qui si riaccende. Senza, il menu sarebbe decorativo.
async function caricaRouting() {
  const box = $("routing-auto");
  if (!box) return;
  try {
    const r = await fetch("/api/routing");
    const d = await r.json();
    if (r.ok) box.checked = !!d.routing;
  } catch (e) { /* resta com'e' */ }
}
on($("routing-auto"), "change", async () => {
  const box = $("routing-auto");
  const out = $("routing-out");
  try {
    const r = await fetch("/api/routing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attivo: !!box.checked }),
    });
    const d = await r.json();
    if (!r.ok) {
      if (out) out.textContent = d.error || "errore";
      box.checked = !box.checked;
      return;
    }
    box.checked = !!d.routing;
    if (out) out.textContent = d.routing ? "automatica accesa" : "automatica spenta: resta il modello scelto";
  } catch (e) {
    if (out) out.textContent = "connessione fallita: " + e;
    box.checked = !box.checked;
  }
});

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
