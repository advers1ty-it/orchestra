(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("main")<0)window.__diagFiles.push("main");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"main");}})();
// ------------------------------------------------------------- azioni
async function send() {
  const text = input.value.trim();
  if (!text || busy || !ready) return;
  input.value = "";
  autoGrow();
  setBusy(true);
  try {
    const r = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      addText("error", err.error || `errore ${r.status}`);
      setBusy(false);
    }
  } catch (e) {
    addText("error", String(e));
    setBusy(false);
  }
}

async function cancel() {
  btnCancel.disabled = true;
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

on(input, "input", autoGrow);
on(input, "keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
btnSend.onclick = send;
btnCancel.onclick = cancel;
btnReset.onclick = reset;

connect();
// Opzioni si caricano QUI, non solo quando apri il pannello. I
// selettori di servizio e di scopo vivono nell'header, e senza questa
// chiamata restano disabilitati fino a quando non apri Opzioni: si
// vedono, sembrano cliccabili, e non lo sono. Il pannello e' una vista
// degli stessi dati, non il posto dove vengono costruiti.
caricaOpzioni().catch(() => {
  // un errore qui non deve fermare il bootstrap: la chat resta viva,
  // e i selettori semplicemente restano disabilitati
});
fetch("/api/state").then(r => r.json()).then(s => {
  if (s.ready === false) { showBanner(s.error); return; }
  ready = true;
  showVersion(s.version);
  if (!log.children.length) handle("snapshot", s);
}).catch(() => { conn.textContent = "server non raggiungibile"; });

// La versione è il modo più economico per capire se stai guardando la
// pagina giusta. Senza, una UI in cache vecchia si manifesta come
// "funziona tutto tranne una cosa" e sembra un bug.
function showVersion(v) {
  $("ver").textContent = v || "?";
  $("ver").title = `interfaccia ${v || "?"} — se non corrisponde al server, ricarica`;
}
