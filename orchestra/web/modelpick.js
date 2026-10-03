(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("modelpick")<0)window.__diagFiles.push("modelpick");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"modelpick");}})();
// ------------------------------------------------ il selettore dei modelli
//
// Il <select> nativo non si vede e non si tocca: porta solo il value
// al server. Quello che si vede è un bottone che sembra un select, e il
// pannello che si apre sotto è questo.
//
// PERCHE' IL SELECT E' NASCOSTO, e non "coperto"
//
// La prima versione lo lasciava VISIBILE e apriva il pannello sopra.
// Non si vedeva niente, e non per un motivo di cache: al click il
// browser apre il SUO menu, disegnato dal sistema, e quel popup sta
// sempre sopra qualsiasi elemento della pagina. Il pannello era sotto,
// funzionante, e invisibile. Ctrl+F5 non lo avrebbe cambiato: non era
// un problema di caricamento.
//
// Nascosto con visually-hidden, non con display:none: display:none
// toglie l'elemento anche dal percorso di tabulazione, e il value che
// porta al server verrebbe da un campo che nessuno puo' raggiungere.

const mpWrap = document.querySelector(".mp-wrap");
const mpBtn = document.getElementById("model-btn");
const mpEtichetta = document.getElementById("model-label");
let mpPop = null;
let mpVoci = [];
let mpCursore = -1;
let mpAperto = false;

// L'etichetta segue il value. Va chiamata OVUNQUE il value cambia:
// senza, il bottone direbbe un modello mentre il select ne porta un
// altro, e la divergenza si vedrebbe solo alla prima risposta.
function mpSincronizzaEtichetta() {
  if (!mpEtichetta || !mpBtn) return;
  const id = modelPick.value;
  const op = id ? Array.from(modelPick.options).find((o) => o.value === id) : null;
  mpEtichetta.textContent = op ? (op.text || id) : "modello…";
  mpBtn.disabled = !!modelPick.disabled;
}

function mpChiudi() {
  if (mpPop) { mpPop.remove(); mpPop = null; }
  mpVoci = [];
  mpCursore = -1;
  mpAperto = false;
  if (mpBtn) mpBtn.setAttribute("aria-expanded", "false");
}

function mpApri() {
  if (mpAperto || modelPick.disabled) return;
  mpAperto = true;
  if (mpBtn) mpBtn.setAttribute("aria-expanded", "true");

  mpPop = el("div", "mp-pop");
  const cerca = el("input", "mp-cerca");
  cerca.type = "search";
  cerca.placeholder = "cerca fra i modelli…";
  cerca.setAttribute("aria-label", "Cerca un modello");
  cerca.value = "";

  const lista = el("div", "mp-lista");
  mpVoci = [];
  const opzioni = Array.from(modelPick.options).filter((o) => o.value);
  const corrente = modelPick.value;

  for (const o of opzioni) {
    const nodo = el("div", "mp-voce");
    nodo.dataset.id = o.value;
    nodo.dataset.testo = (o.textContent || o.value).toLowerCase();
    if (o.value === corrente) nodo.classList.add("corrente");
    // Il badge dice DA DOVE viene il numero. Un numero senza
    // etichetta sembra parte del nome del modello, e su 400 righe
    // nessuno saprebbe di che cosa sia.
    const p = punteggioDiOpzione(o.value);
    const b = el("span", "mp-bench" + (p !== null ? " " + fasciaPunteggio(p) : ""),
                 p !== null ? String(p) : "—");
    b.title = (p !== null)
      ? "punteggio di benchmark: " + p + " su 100, misurato sui task di Orchestra"
      : "non misurato: nessun benchmark su questo modello";
    nodo.appendChild(b);
    nodo.appendChild(el("div", "mp-nome", o.text));
    nodo.appendChild(el("span", "mp-meta", metaDiOpzione(o.textContent || "")));
    lista.appendChild(nodo);
    mpVoci.push({ id: o.value, nodo });
  }

  const piede = el("div", "mp-piede");
    piede.textContent = opzioni.length +
      " modelli · il numero è il punteggio di benchmark (su 100) · «—» = non misurato";
    // Se il servizio non dichiara il supporto tool, si dice QUI, una
    // volta sola. Lo stesso ragionamento del menu: se il dubbio è
    // identico su ogni riga, non è un'informazione per riga — è
    // un'informazione sul servizio, e va detta una volta.
    if (servizioTace) {
      piede.textContent += " · questo servizio non dichiara il supporto tool: "
        + "non lo sappiamo, e lo scopriamo dal benchmark";
    }

  mpPop.appendChild(cerca);
  mpPop.appendChild(lista);
  mpPop.appendChild(piede);
  mpWrap.appendChild(mpPop);

  // mp-wrap ha position:relative, quindi top:100% è il bordo
  // inferiore del bottone. Senza quella riga di CSS il riferimento
  // sarebbe la pagina, e il pannello comparirebbe nell'angolo in alto
  // a sinistra invece che sotto il bottone.
  mpPop.style.top = "100%";
  mpPop.style.left = "0";

  cerca.addEventListener("input", () => {
    const q = cerca.value.trim().toLowerCase();
    let visibili = 0;
    for (const v of mpVoci) {
      const ok = !q || v.nodo.dataset.testo.includes(q);
      v.nodo.style.display = ok ? "" : "none";
      if (ok) visibili++;
    }
    // La riga "nessun risultato" si crea e si toglie: tenerla sempre
    // nel DOM e spegnerla con display:none lascia un nodo morto nel
    // mezzo della lista, e un nodo morto in una lista filtrata e'
    // quello che rende strano il conteggio.
    let vuota = lista.querySelector(".mp-vuoto");
    if (visibili === 0) {
      if (!vuota) lista.appendChild(el("div", "mp-vuoto", "nessun modello con questo nome"));
    } else if (vuota) {
      vuota.remove();
    }
    mpCursore = -1;
  });

  cerca.addEventListener("keydown", (ev) => {
    const visibili = mpVisibili();
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      mpMuovi(1, visibili);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      mpMuovi(-1, visibili);
    } else if (ev.key === "Home") {
      ev.preventDefault();
      mpCursore = 0;
      mpEvidenzia(visibili);
    } else if (ev.key === "End") {
      ev.preventDefault();
      mpCursore = Math.max(0, visibili.length - 1);
      mpEvidenzia(visibili);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      const scelta = mpCursore >= 0 ? visibili[mpCursore] : null;
      if (scelta) mpScegli(scelta.id);
      else if (visibili.length) mpScegli(visibili[0].id);
    } else if (ev.key === "Escape") {
      // ESC chiude SENZA cambiare niente. Un menu che al primo
      // refuso cambia il modello in uso costa un turno di lavoro.
      ev.preventDefault();
      ev.stopPropagation();
      mpChiudi();
      if (mpBtn) mpBtn.focus();
    } else if (ev.key === "Tab") {
      mpChiudi();
    }
  });

  cerca.addEventListener("click", (ev) => ev.stopPropagation());
  lista.addEventListener("click", (ev) => {
    const voce = ev.target.closest(".mp-voce");
    if (voce) mpScegli(voce.dataset.id);
  });

  cerca.focus();
}

function mpVisibili() {
  return mpVoci.filter((v) => v.nodo.style.display !== "none");
}

function mpEvidenzia(visibili) {
  mpVoci.forEach((v) => v.nodo.classList.remove("cursore"));
  const n = visibili[mpCursore];
  if (n) {
    n.nodo.classList.add("cursore");
    n.nodo.scrollIntoView({ block: "nearest" });
  }
}

function mpMuovi(d, visibili) {
  if (!visibili.length) return;
  if (mpCursore < 0) mpCursore = d > 0 ? -1 : visibili.length;
  mpCursore = (mpCursore + d + visibili.length) % visibili.length;
  mpEvidenzia(visibili);
}

function mpScegli(id) {
  if (!id) return;
  // Il value E il change. Scrivere il value da solo non basterebbe:
  // nessuno riceverebbe la notifica, il select mostrerebbe un modello
  // e il backend continuerebbe a chiamarne un altro — la chat
  // risponderebbe col vecchio senza che nulla lo dica.
  modelPick.value = id;
  modelPick.dispatchEvent(new Event("change", { bubbles: true }));
  mpChiudi();
}

function punteggioDiOpzione(id) {
  const m = modelliPerId && modelliPerId[id];
  const t = m && m.punteggio_unico;
  if (t && typeof t.punteggio === "number") return Math.round(t.punteggio);
  return null;
}

function fasciaPunteggio(p) {
  if (p >= 80) return "buono";
  if (p >= 55) return "medio";
  return "";
}

function metaDiOpzione(testo) {
  const parti = String(testo).split("·").map((s) => s.trim()).filter(Boolean);
  return parti.slice(-1)[0] || "";
}

// Il bottone al posto del select.
on(mpBtn, "click", (ev) => {
  ev.stopPropagation();
  if (mpAperto) mpChiudi(); else mpApri();
});

// La tastiera sul bottone chiuso: giu'/Invio apre. Sul select nativo e'
// gratis; qui va rifatto, ed e' la ragione per cui il pannello non e'
// una scorciatoia.
on(mpBtn, "keydown", (ev) => {
  if (mpAperto) return;
  if (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    mpApri();
  }
});

on(document, "click", (ev) => {
  if (mpAperto && mpPop && !mpPop.contains(ev.target)) mpChiudi();
});

on(document, "keydown", (ev) => {
  if (mpAperto && ev.key === "Escape") { mpChiudi(); if (mpBtn) mpBtn.focus(); }
});