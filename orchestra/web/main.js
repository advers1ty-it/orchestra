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

input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
btnSend.onclick = send;
btnCancel.onclick = cancel;
btnReset.onclick = reset;

connect();
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
