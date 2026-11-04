(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-storia")<0)window.__diagFiles.push("panels-storia");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-storia");}})();
// ------------------------------------------------------------------ storico
// Le conversazioni salvate su disco. Il pannello si ricarica da sé quando
// si apre, non ha un pulsante "applica": quello che c'è è già applicato.

const storicoElenco = $("storico-elenco");
const storicoMsg = $("storico-msg");
const storicoNuova = $("storico-nuova");
const storicoRicarica = $("storico-ricarica");

function _storico_data(d) {
  try {
    return new Date(d * 1000).toLocaleString("it-IT", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return ""; }
}

async function caricaStorico() {
  if (!storicoElenco) return;
  storicoMsg.textContent = "caricamento...";
  storicoMsg.className = "small dim";
  try {
    const resp = await fetch("/api/storico");
    const d = await resp.json();
    if (!resp.ok) {
      storicoMsg.textContent = d.error || ("errore " + resp.status);
      storicoMsg.className = "small rosso";
      return;
    }
    storicoElenco.replaceChildren();
    const sessioni = d.sessioni || [];
    if (!sessioni.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.textContent = "Nessuna conversazione salvata.";
      storicoElenco.appendChild(li);
      storicoMsg.textContent = "";
      return;
    }
    for (const s of sessioni) {
      const li = document.createElement("li");
      li.className = "storico-riga" + (s.id === d.attiva ? " attiva" : "");

      const info = document.createElement("div");
      info.className = "storico-info";
      const titolo = document.createElement("span");
      titolo.className = "storico-titolo";
      titolo.textContent = s.titolo || "(senza titolo)";
      const meta = document.createElement("span");
      meta.className = "small dim";
      meta.textContent = `${_storico_data(s.aggiornata)} · ${s.n_messaggi} msg · ${s.modello || "?"}`;
      info.appendChild(titolo);
      info.appendChild(meta);
      li.appendChild(info);

      const bottoni = document.createElement("div");
      bottoni.className = "storico-bottoni";

      const apri = document.createElement("button");
      apri.textContent = s.id === d.attiva ? "Aperta" : "Apri";
      apri.disabled = s.id === d.attiva;
      apri.className = s.id === d.attiva ? "" : "primary";
      apri.addEventListener("click", async () => {
        storicoMsg.textContent = "apertura...";
        try {
          const r = await fetch("/api/storico/apri", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: s.id }),
          });
          const rd = await r.json();
          if (!r.ok) {
            storicoMsg.textContent = rd.error || ("errore " + r.status);
            storicoMsg.className = "small rosso";
            return;
          }
          // La conversazione cambia in chat: si ricarica lo snapshot
          // dalla stessa risposta, così non si legge uno stato vecchio.
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          storicoMsg.textContent = "conversazione aperta";
          storicoMsg.className = "small verde";
          await caricaStorico();
        } catch (e) {
          storicoMsg.textContent = "apertura fallita: " + e;
          storicoMsg.className = "small rosso";
        }
      });
      bottoni.appendChild(apri);

      const elimina = document.createElement("button");
      elimina.textContent = "Elimina";
      elimina.addEventListener("click", async () => {
        if (!confirm("Eliminare questa conversazione? Non si recupera.")) return;
        try {
          const r = await fetch("/api/storico/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: s.id }),
          });
          const rd = await r.json();
          if (!r.ok) {
            storicoMsg.textContent = rd.error || ("errore " + r.status);
            storicoMsg.className = "small rosso";
            return;
          }
          if (rd.snapshot) handle("snapshot", rd.snapshot);
          storicoMsg.textContent = "eliminata";
          storicoMsg.className = "small verde";
          await caricaStorico();
        } catch (e) {
          storicoMsg.textContent = "eliminazione fallita: " + e;
          storicoMsg.className = "small rosso";
        }
      });
      bottoni.appendChild(elimina);

      li.appendChild(bottoni);
      storicoElenco.appendChild(li);
    }
    storicoMsg.textContent = "";
  } catch (e) {
    storicoMsg.textContent = "caricamento fallito: " + e;
    storicoMsg.className = "small rosso";
  }
}

if (storicoNuova) {
  storicoNuova.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/storico/nuova", { method: "POST" });
      const d = await r.json();
      if (!r.ok) {
        storicoMsg.textContent = d.error || ("errore " + r.status);
        storicoMsg.className = "small rosso";
        return;
      }
      if (d.snapshot) handle("snapshot", d.snapshot);
      storicoMsg.textContent = "nuova conversazione";
      storicoMsg.className = "small verde";
      await caricaStorico();
    } catch (e) {
      storicoMsg.textContent = "non riesco: " + e;
      storicoMsg.className = "small rosso";
    }
  });
}

if (storicoRicarica) {
  storicoRicarica.addEventListener("click", caricaStorico);
}

// ------------------------------------------------------------------- memoria

const memoriaElenco = $("memoria-elenco");
const memoriaMsg = $("memoria-msg");
const memoriaNuovo = $("memoria-nuovo");
const memoriaAggiungi = $("memoria-aggiungi");
const memoriaPercorso = $("memoria-percorso");

async function caricaMemoria() {
  if (!memoriaElenco) return;
  try {
    const resp = await fetch("/api/memoria");
    const d = await leggiJson(resp);
    if (!resp.ok) {
      memoriaMsg.textContent = d.error || ("errore " + resp.status);
      memoriaMsg.className = "small rosso";
      return;
    }
    if (memoriaPercorso && d.percorso) {
      memoriaPercorso.textContent = d.percorso;
    }
    memoriaElenco.replaceChildren();
    const fatti = d.fatti || [];
    if (!fatti.length) {
      const li = document.createElement("li");
      li.className = "small dim";
      li.textContent = "Nessun fatto ricordato.";
      memoriaElenco.appendChild(li);
      memoriaMsg.textContent = "";
      return;
    }
    for (const fatto of fatti) {
      const li = document.createElement("li");
      li.className = "memoria-riga";

      const testo = document.createElement("span");
      testo.className = "memoria-fatto";
      testo.textContent = fatto;
      li.appendChild(testo);

      const via = document.createElement("button");
      via.textContent = "Dimentica";
      via.addEventListener("click", async () => {
        try {
          const r = await fetch("/api/memoria/elimina", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fatto: fatto }),
          });
          const rd = await r.json();
          if (!r.ok) {
            memoriaMsg.textContent = rd.error || ("errore " + r.status);
            memoriaMsg.className = "small rosso";
            return;
          }
          memoriaMsg.textContent = rd.tolto ? "dimenticato" : "non era in memoria";
          memoriaMsg.className = rd.tolto ? "small verde" : "small dim";
          await caricaMemoria();
        } catch (e) {
          memoriaMsg.textContent = "non riesco: " + e;
          memoriaMsg.className = "small rosso";
        }
      });
      li.appendChild(via);
      memoriaElenco.appendChild(li);
    }
    memoriaMsg.textContent = "";
  } catch (e) {
    memoriaMsg.textContent = "caricamento fallito: " + e;
    memoriaMsg.className = "small rosso";
  }
}

if (memoriaAggiungi) {
  memoriaAggiungi.addEventListener("click", async () => {
    const fatto = (memoriaNuovo.value || "").trim();
    if (!fatto) {
      memoriaMsg.textContent = "scrivi qualcosa da ricordare";
      memoriaMsg.className = "small dim";
      return;
    }
    try {
      const r = await fetch("/api/memoria/aggiungi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fatto: fatto }),
      });
      const d = await r.json();
      if (!r.ok) {
        memoriaMsg.textContent = d.error || ("errore " + r.status);
        memoriaMsg.className = "small rosso";
        return;
      }
      memoriaNuovo.value = "";
      memoriaMsg.textContent = d.nuovo ? "ricordato" : "era gi\u00e0 in memoria";
      memoriaMsg.className = "small verde";
      await caricaMemoria();
    } catch (e) {
      memoriaMsg.textContent = "non riesco: " + e;
      memoriaMsg.className = "small rosso";
    }
  });
}

if (memoriaNuovo) {
  memoriaNuovo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && memoriaAggiungi) memoriaAggiungi.click();
  });
}
