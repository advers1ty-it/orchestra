/* Verifica che i due selettori del servizio dicano la stessa cosa
   DAVVERO: li popoliamo, cambiamo servizio dal menu della chat, e
   controlliamo che anche quello delle Opzioni si allinei e che i modelli
   della chat vengano ricaricati per il servizio nuovo. */
const fs = require("fs");
const path = require("path");

const WEB = path.join(__dirname, "..", "orchestra", "web");
const ORDER = ["core.js", "panels.js", "main.js"];
void fs; void ORDER; void WEB;
const src = ORDER.map((f) => fs.readFileSync(path.join(WEB, f), "utf8")).join("\n;\n");

const OUT = { errori: [] };
(async function () {
  try {
    // 1) il pannello Opzioni viene riempito come all'avvio
    await disegnaProvider({ provider: "openrouter", chiavi: CHIAVI, motori: [] });
  } catch (e) { OUT.errori.push("disegnaProvider: " + e.message); }
})();

setTimeout(() => {
  const h = document.getElementById("provider-pick");
  const o = document.getElementById("opt-provider");
  OUT.header = { voci: h.options.map((x) => x.text), val: h.value, off: h.disabled };
  OUT.opzioni = { voci: o.options.map((x) => x.text), val: o.value, off: o.disabled };

  // 2) cambio servizio DAL MENU DELLA CHAT
  h.value = "groq";
  h.fire("change");
  setTimeout(() => {
    OUT.dopo = {
      header: h.value,
      opzioni: o.value,
      servizioBackend: globalThis.__servizioVisto || "",
      modelliChat: document.getElementById("model-pick").options.map((x) => x.text),
      nota: document.getElementById("provider-note").textContent,
    };
    console.log(JSON.stringify(OUT, null, 1));
  }, 300);
}, 300);

/* il fetch provider annota il servizio richiesto */
(function () {
  const f = globalThis.fetch;
  globalThis.fetch = async function (u, o) {
    if (String(u).startsWith("/api/provider") && o && o.body) {
      globalThis.__servizioVisto = JSON.parse(o.body).provider;
    }
    return f(u, o);
  };
})();
