  // ------------------------------------------------------ modale memoria

  const memModal = $("mem-modal");
  const memLista = $("mem-lista");
  const memCerca = $("mem-cerca");
  const memStat = $("mem-stat");
  const memMsg = $("mem-msg");
  const memTutti = $("side-mem-tutti");

  function _memMsg(txt, tipo) {
    if (!memMsg) return;
    memMsg.textContent = txt;
    memMsg.className = "small" + (tipo ? " " + tipo : "");
  }

  function _memStatTxt(d) {
    const ind = d.indice;
    if (!ind || ind.errore) return (d.n_fatti || 0) + " fatti";
    const kb = Math.round((ind.byte_file || 0) / 1024);
    let out = ind.totale + " fatti";
    if (kb) out += " · " + kb + " KB";
    if (ind.mai_usati) out += " · " + ind.mai_usati + " mai cercati";
    return out;
  }

  async function memCarica(query) {
    if (!memLista) return;
    memLista.innerHTML = '<div class="mem-vuoto">Caricamento...</div>';
    try {
      let url = "/api/memoria";
      let opts = {};
      if (query) {
        url = "/api/memoria/cerca";
        opts = { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: query, limite: 200 }) };
      }
      const r = await fetch(url, opts);
      const d = await leggiJson(r);
      if (!r.ok) { _memMsg(d.error || ("errore " + r.status), "rosso"); return; }
      if (memStat) memStat.textContent = _memStatTxt(d);
      memLista.replaceChildren();
      const fatti = query ? (d.risultati || []) : (d.fatti || []);
      if (!fatti.length) {
        const v = document.createElement("div");
        v.className = "mem-vuoto";
        v.textContent = query ? 'Nessun risultato per "' + query + '".' : "Nessun fatto ricordato.";
        memLista.appendChild(v);
        return;
      }
      for (const f of fatti) {
        const testo = typeof f === "string" ? f : (f.testo || "");
        const imp = typeof f === "object" && f.importante;
        memLista.appendChild(_MemItem(testo, imp));
      }
      _memMsg(fatti.length + " fatti" + (query ? " trovati" : " totali"), "");
    } catch (e) {
      _memMsg("errore: " + e, "rosso");
    }
  }

  function _MemItem(testo, imp) {
    const row = document.createElement("div");
    row.className = "mem-item" + (imp ? " imp" : "");
    if (imp) {
      const st = document.createElement("span");
      st.className = "stella";
      st.textContent = "\u2605";
      st.title = "in ogni prompt";
      row.appendChild(st);
    }
    const txt = document.createElement("div");
    txt.className = "txt";
    txt.textContent = testo;
    row.appendChild(txt);
    const via = document.createElement("span");
    via.className = "via";
    via.textContent = imp ? "importante" : "fatto";
    row.appendChild(via);
    const btns = document.createElement("div");
    btns.className = "btns";
    const modBtn = document.createElement("button");
    modBtn.textContent = "Modifica";
    modBtn.addEventListener("click", () => _MemModifica(row, testo));
    const delBtn = document.createElement("button");
    delBtn.textContent = "\u00d7";
    delBtn.title = "Dimentica";
    delBtn.addEventListener("click", async () => {
      if (!confirm("Dimenticare questo fatto?")) return;
      try {
        const r = await fetch("/api/memoria/elimina", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ fatto: testo }) });
        const d = await leggiJson(r);
        if (!r.ok) { _memMsg(d.error || ("errore " + r.status), "rosso"); return; }
        _memMsg(d.tolto ? "dimenticato" : "non era in memoria", d.tolto ? "verde" : "");
        await memCarica(memCerca.value.trim() || null);
      } catch (e) { _memMsg("errore: " + e, "rosso"); }
    });
    btns.appendChild(modBtn);
    btns.appendChild(delBtn);
    row.appendChild(btns);
    return row;
  }

  function _MemModifica(row, vecchio) {
    if (row.querySelector(".mem-edit")) return;
    const ta = document.createElement("textarea");
    ta.className = "mem-edit open";
    ta.value = vecchio;
    row.appendChild(ta);
    ta.focus();
    ta.select();
    const salva = async () => {
      const nuovo = ta.value.trim();
      if (!nuovo || nuovo === vecchio) {
        row.removeChild(ta);
        return;
      }
      ta.disabled = true;
      try {
        const r = await fetch("/api/memoria/modifica", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vecchio: vecchio, nuovo: nuovo }) });
        const d = await leggiJson(r);
        if (!r.ok) { _memMsg(d.error || ("errore " + r.status), "rosso"); return; }
        _memMsg(d.modificato ? "fatto aggiornato" : "non trovato", d.modificato ? "verde" : "");
        await memCarica(memCerca.value.trim() || null);
      } catch (e) { _memMsg("errore: " + e, "rosso"); }
    };
    ta.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); salva(); }
      if (ev.key === "Escape") { ev.preventDefault(); row.removeChild(ta); }
    });
    ta.addEventListener("blur", () => setTimeout(() => { if (row.contains(ta)) salva(); }, 150));
  }

  if (memTutti) {
    memTutti.addEventListener("click", async () => {
      if (!memModal) return;
      if (memCerca) memCerca.value = "";
      memModal.classList.add("show");
      await memCarica(null);
    });
  }
  if (memModal) {
    memModal.addEventListener("click", (ev) => {
      if (ev.target === memModal) memModal.classList.remove("show");
    });
    const chiudi = $("mem-chiudi");
    if (chiudi) chiudi.addEventListener("click", () => memModal.classList.remove("show"));
    const trova = $("mem-trova");
    if (trova) trova.addEventListener("click", () => {
      const q = (memCerca.value || "").trim();
      memCarica(q || null);
    });
    const annulla = $("mem-annulla-cerca");
    if (annulla) annulla.addEventListener("click", () => {
      memCerca.value = "";
      memCarica(null);
    });
    if (memCerca) memCerca.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); memCarica(memCerca.value.trim() || null); }
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && memModal.classList.contains("show")) memModal.classList.remove("show");
    });
  }

