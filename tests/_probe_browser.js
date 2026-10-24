/* Prova vera: Chrome headless via DevTools Protocol.
   Apre la pagina servita dal server, clicca i bottoni dei tre modali e
   legge lo stile CALCOLATO e il rettangolo: jsdom non fa layout, quindi
   un modale che si "apre" ma resta invisibile li' non si vede. */
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const URL_APP = process.argv[2] || "http://127.0.0.1:8737/";
const PORT = 9333;
const profilo = fs.mkdtempSync(path.join(os.tmpdir(), "orch-cdp-"));

const chrome = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=" + PORT, "--user-data-dir=" + profilo,
  "--window-size=1400,900", "about:blank",
], { stdio: "ignore" });

const attendi = (ms) => new Promise((r) => setTimeout(r, ms));

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => res(d));
    }).on("error", rej);
  });
}

(async () => {
  // aspetta che il browser esponga il debugger
  let ws = null;
  for (let i = 0; i < 40; i++) {
    try {
      // Il websocket del BROWSER non ha Runtime.evaluate: serve il
      // target della PAGINA, che sta in /json/list.
      const lista = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`));
      const pag = lista.find((t) => t.type === "page");
      ws = pag && pag.webSocketDebuggerUrl;
      if (ws) break;
    } catch (e) { /* non ancora pronto */ }
    await attendi(250);
  }
  if (!ws) { console.log("@@OUT@@{\"errore\":\"chrome non risponde\"}"); process.exit(1); }

  const socket = new WebSocket(ws);
  let id = 0;
  const attesa = new Map();
  const eventi = [];
  socket.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && attesa.has(m.id)) { attesa.get(m.id)(m); attesa.delete(m.id); }
    else if (m.method) eventi.push(m);
  });
  await new Promise((r) => socket.addEventListener("open", r));

  const invia = (method, params) => new Promise((r) => {
    const i = ++id;
    attesa.set(i, r);
    socket.send(JSON.stringify({ id: i, method, params: params || {} }));
  });

  await invia("Page.enable");
  await invia("Runtime.enable");
  await invia("Page.navigate", { url: URL_APP });
  await attendi(2500);

  const SCRIPT = `
(async () => {
  const out = { errori: [], console: [] };
  const att = (ms) => new Promise(r => setTimeout(r, ms));
  const info = (id) => {
    const el = document.getElementById(id);
    if (!el) return "MANCA";
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return { hidden: el.hidden, classe: el.className, display: cs.display,
             visibility: cs.visibility, opacity: cs.opacity, zIndex: cs.zIndex,
             rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
             genitore: el.parentElement ? el.parentElement.tagName + "." + el.parentElement.className : "?" };
  };
  // apri la sidebar come farebbe l'utente: il bottone vero, non la funzione
  const bs = document.getElementById("btn-side");
  if (bs) { bs.click(); await att(400); }
  // la barra degli obiettivi: era anche lei dentro #onboard
  const gb = document.getElementById("goal-bar");
  if (gb) { gb.hidden = false; }
  await att(200);
  out.goalBar = gb ? (() => { const cs = getComputedStyle(gb); const r = gb.getBoundingClientRect();
    return { display: cs.display, visibility: cs.visibility,
             rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
             genitore: gb.parentElement.tagName }; })() : "MANCA";
  const ob = document.getElementById("onboard");
  out.onboard = ob ? { hidden: ob.hidden, display: getComputedStyle(ob).display } : "MANCA";
  await att(200);
  const side = document.getElementById("sidebar");
  out.sidebar = side ? { hidden: side.hidden, classe: side.className,
                         rect: (r => [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)])(side.getBoundingClientRect()) } : "MANCA";

  // 1. memoria
  const bm = document.getElementById("side-mem-tutti");
  out.bottoneMemoria = bm ? { visibile: bm.getBoundingClientRect().height > 0,
                              rect: (r => [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)])(bm.getBoundingClientRect()) } : "MANCA";
  if (bm) { bm.click(); await att(400); }
  out.memModal = info("mem-modal");

  // 2. progetti
  const bp = document.getElementById("side-progetti-gestisci");
  if (bp) { bp.click(); await att(400); }
  out.progettiModal = info("progetti-modal");

  // 3. tracce
  try { if (typeof caricaSideTracce === "function") await caricaSideTracce(); } catch (e) { out.errori.push("tracce: " + e); }
  await att(400);
  const lista = document.getElementById("side-tracce");
  out.righeTracce = lista ? lista.children.length : -1;
  const btn = lista && lista.children[0] ? lista.children[0].querySelector("button") : null;
  if (btn) { btn.click(); await att(500); }
  out.tracciaModal = info("traccia-modal");

  const diag = document.getElementById("diag");
  out.diag = diag ? diag.textContent.slice(0, 300) : "(nessuno)";
  return JSON.stringify(out);
})()
`;

  const r = await invia("Runtime.evaluate", {
    expression: SCRIPT, awaitPromise: true, returnByValue: true,
  });
  const valore = r.result && r.result.result && r.result.result.value;
  const errs = eventi.filter((e) => e.method === "Runtime.exceptionThrown")
    .map((e) => e.params.exceptionDetails.text + " " +
                (e.params.exceptionDetails.exception && e.params.exceptionDetails.exception.description || "").slice(0, 200));

  console.log("@@OUT@@" + (valore || JSON.stringify({ errore: "nessun valore", r })));
  if (errs.length) console.log("@@ECCEZIONI@@" + JSON.stringify(errs, null, 2));

  socket.close();
  chrome.kill();
  process.exit(0);
})();
