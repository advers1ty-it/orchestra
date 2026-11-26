(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("modelpick")<0)window.__diagFiles.push("modelpick");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"modelpick");}})();
// il selettore dei modelli: Il <select> nativo non si vede e non si tocca: porta solo il value al server.

const mpWrap = document.querySelector(".mp-wrap");
const mpBtn = document.getElementById("model-btn");
const mpEtichetta = document.getElementById("model-label");
let mpPop = null;
let mpVoci = [];
let mpCursore = -1;
let mpAperto = false;

// L'etichetta segue il value.
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

// `servizioTaceArrivato` dice se il servizio non dichiara il supporto tool.
function mpApri(servizioTaceArrivato) {
  const servizioNonDichiaraTool = servizioTaceArrivato === true;
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
    // Il badge dice DA DOVE viene il numero.
    const p = punteggioDiOpzione(o.value);
    const b = el("span", "mp-bench" + (p !== null ? " " + fasciaPunteggio(p) : ""),
                 p !== null ? String(p) : "n/d");
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
      " modelli · il numero è il punteggio di benchmark (su 100) · «n/d» = non misurato";
    // Se il servizio non dichiara il supporto tool, si dice QUI, una volta sola.
    if (servizioNonDichiaraTool) {
      piede.textContent += " · questo servizio non dichiara il supporto tool: "
        + "non lo sappiamo, e lo scopriamo dal benchmark";
    }

  mpPop.appendChild(cerca);
  mpPop.appendChild(lista);
  mpPop.appendChild(piede);
  mpWrap.appendChild(mpPop);

  // mp-wrap ha position:relative, quindi top:100% è il bordo inferiore del bottone.
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
    // La riga "nessun risultato" si crea e si toglie: tenerla sempre nel DOM e spegnerla con display:none lascia un
    // nodo morto nel mezzo della lista, e un nodo morto in una lista filtrata e' quello che rende strano il conteggio.
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
  // Il value E il change.
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
  // Il test puo' caricare solo questo file: un ReferenceError qui blocca il menu.
  const sa = (typeof servizioTace !== "undefined") ? servizioTace : false;
  if (mpAperto) mpChiudi(); else mpApri(sa);
});

// La tastiera sul bottone chiuso: giu'/Invio apre.
on(mpBtn, "keydown", (ev) => {
  if (mpAperto) return;
  if (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    const sa = (typeof servizioTace !== "undefined") ? servizioTace : false;
    mpApri(sa);
  }
});

on(document, "click", (ev) => {
  if (mpAperto && mpPop && !mpPop.contains(ev.target)) mpChiudi();
});

on(document, "keydown", (ev) => {
  if (mpAperto && ev.key === "Escape") { mpChiudi(); if (mpBtn) mpBtn.focus(); }
});