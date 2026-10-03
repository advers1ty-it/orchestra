(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("modelpick")<0)window.__diagFiles.push("modelpick");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"modelpick");}})();
// ------------------------------------------------ popup del selettore modello
//
// Il <select> nativo resta, e non viene nascosto. Il pannello si apre
// SOPRA, coprendolo. Motivo: il native porta con se' cose che non si
// scrivono — Tab che arriva al campo, frecce, Esc, e soprattutto il
// fatto che il suo value è quello che il server legge per sapere quale
// modello è scelto. Se lo nascondessi con display:none il browser
// smetterebbe di mettergli il focus, Tab lo salterebbe, e il value
// arriverebbe da un campo che l'utente non può né vedere né toccare.
//
// Il pannello fa tre cose che il native non può fare: cerca fra 400
// righe, colora il punteggio, e dice da dove viene quel numero.
//
// E una cosa che sembra dettaglio e non lo è: ESC chiude SENZA
// cambiare niente. Un menu che al primo refuso ti cambia il modello in
// uso è un menu che costa un turno di lavoro.

const mpWrap = document.querySelector(".mp-wrap");
let mpPop = null;
let mpVoci = [];      // [{id, nodo}]
let mpCursore = -1;
let mpAperto = false;

function mpChiudi() {
  if (mpPop) { mpPop.remove(); mpPop = null; }
  mpVoci = [];
  mpCursore = -1;
  mpAperto = false;
}

function mpApri() {
  if (mpAperto || modelPick.disabled) return;
  mpAperto = true;

  mpPop = el("div", "mp-pop");
  const cerca = el("input", "mp-cerca");
  cerca.type = "search";
  cerca.placeholder = "cerca fra i modelli…";
  cerca.setAttribute("aria-label", "Cerca un modello");
  cerca.value = "";

  const lista = el("div", "mp-lista");
  mpVoci = [];

  const opzioni = Array.from(modelPick.options)
    .filter((o) => o.value);
  const corrente = modelPick.value;

  for (const o of opzioni) {
    // I metadati stanno nel testo dell'opzione, che il pannello
    // ricalca: non c'e' un oggetto modello associato alla riga, e
    // aggiungerne uno solo per il popup significa tenere due liste
    // che possono divergere. La riga nativa resta la fonte.
    const testo = o.textContent || o.value;
    const nodo = el("div", "mp-voce");
    nodo.dataset.id = o.value;
    nodo.dataset.testo = testo.toLowerCase();
    if (o.value === corrente) nodo.classList.add("corrente");

    const nome = el("div", "mp-nome", o.text);
    const p = punteggioDiOpzione(o);
    if (p !== null) {
      nodo.appendChild(el("span", "mp-bench " + fasciaPunteggio(p), `${p}`));
      nodo.title = `punteggio di benchmark: ${p} su 100 — misurato sui task di Orchestra`;
    } else {
      nodo.appendChild(el("span", "mp-bench", "—"));
      nodo.title = "non misurato: nessun benchmark su questo modello";
    }
    nodo.appendChild(nome);
    nodo.appendChild(el("span", "mp-meta", metaDiOpzione(testo)));
    lista.appendChild(nodo);
    mpVoci.push({ id: o.value, nodo });
  }

  const piede = el("div", "mp-piede");
  piede.textContent =
    `${opzioni.length} modelli · il numero è il punteggio di benchmark (su 100) · "—" = non misurato`;

  mpPop.appendChild(cerca);
  mpPop.appendChild(lista);
  mpPop.appendChild(piede);
  mpWrap.appendChild(mpPop);

  // posiziona sotto il select
  const r = modelPick.getBoundingClientRect();
  const w = mpWrap.getBoundingClientRect();
  mpPop.style.left = (r.left - w.left) + "px";
  mpPop.style.top = (r.bottom - w.top + 4) + "px";

  cerca.addEventListener("input", () => {
    const q = cerca.value.trim().toLowerCase();
    let visibili = 0;
    for (const v of mpVoci) {
      const ok = !q || v.nodo.dataset.testo.includes(q);
      v.nodo.style.display = ok ? "" : "none";
      if (ok) visibili++;
    }
    // La riga "nessun risultato" si crea e si toglie: metterla sempre
    // nel DOM e spegnerla con display:none è la via che lascia un
    // nodo morto nel mezzo della lista, e un nodo morto in una lista
    // filtrata è quello che rende strano il conteggio.
    let vuota = lista.querySelector(".mp-vuoto");
    if (visibili === 0) {
      if (!vuota) lista.appendChild(el("div", "mp-vuoto", "nessun modello con questo nome"));
    } else if (vuota) {
      vuota.remove();
    }
    mpCursore = -1;
  });

  cerca.addEventListener("keydown", (ev) => {
    const visibili = mpVoci.filter((v) => v.nodo.style.display !== "none");
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      mpMuovi(1, visibili);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      mpMuovi(-1, visibili);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      const scelta = mpCursore >= 0 ? visibili[mpCursore] : null;
      if (scelta) { mpScegli(scelta.id); }
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      mpChiudi();
      modelPick.focus();
    }
  });

  cerca.addEventListener("click", (ev) => ev.stopPropagation());
  lista.addEventListener("click", (ev) => {
    const voce = ev.target.closest(".mp-voce");
    if (voce) mpScegli(voce.dataset.id);
  });

  cerca.focus();
}

function mpMuovi(d, visibili) {
  if (!visibili.length) return;
  mpCursore = (mpCursore + d + visibili.length + 1) % (visibili.length + 1) - (d < 0 ? 0 : 0);
  if (mpCursore < 0) mpCursore = 0;
  mpCursore = Math.max(0, Math.min(mpCursore, visibili.length - 1));
  mpVoci.forEach((v) => v.nodo.classList.remove("cursore"));
  const n = visibili[mpCursore];
  if (n) { n.nodo.classList.add("cursore"); n.nodo.scrollIntoView({ block: "nearest" }); }
}

function mpScegli(id) {
  if (!id) return;
  // Si cambia il value e si spara l'evento change: è il cammino che il
  // select nativo percorre, quindi il codice che ascolta quel cambio
  // funziona identico. Scrivere modelPick.value da solo non basterebbe:
  // nessuno riceverebbe la notifica e il modello non cambierebbe.
  modelPick.value = id;
  modelPick.dispatchEvent(new Event("change", { bubbles: true }));
  mpChiudi();
}

function punteggioDiOpzione(o) {
  const m = modelliPerId && modelliPerId[o.value];
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
  // dal testo dell'opzione: contesto e prezzo sono gia' li'
  const parti = testo.split("·").map((s) => s.trim()).filter(Boolean);
  return parti.slice(-1)[0] || "";
}

on(modelPick, "focus", () => mpApri());
on(modelPick, "click", () => mpApri());
on(document, "click", (ev) => {
  if (mpAperto && mpPop && !mpPop.contains(ev.target)) mpChiudi();
});
on(document, "keydown", (ev) => {
  if (mpAperto && ev.key === "Escape") { mpChiudi(); modelPick.focus(); }
});