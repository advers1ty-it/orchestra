/* Il menu deve tornare indietro quando il cambio fallisce.
   Non letto nel sorgente: il bundle viene eseguito con un DOM finto, il
   cambio viene davvero tentato, il server risponde con un errore, e si
   guarda che cosa resta nei due menu.

   Perche' importa: se il menu resta sul valore nuovo dopo un rifiuto,
   mostra un modello (o un servizio) che l'agente non sta usando. La
   divergenza si scopre alla prima risposta, e sembra un errore di rete.

   Questo file viene accodato dopo il bundle: le funzioni e i const del
   bundle sono nello stesso script, ed e' per questo che qui si possono
   chiamare disegnaProvider/caricaModelli direttamente. */
const OUT = { errori: [], passi: {} };
const attesa = (ms) => new Promise((r) => setTimeout(r, ms));

const baseFetch = globalThis.fetch;
globalThis.fetch = async function (u, o) {
  if (String(u).startsWith("/api/modelli")) {
    // Due modelli, uno free e uno no: serve un secondo valore su cui
    // spostare il menu, altrimenti "torna indietro" non si distingue
    // da "non si e' mosso".
    return { ok: true, status: 200, json: async () => ({
      provider: "openrouter",
      modelli: [
        { id: "openrouter/x1", short: "x1", free: true, context: 8000, scores: {} },
        { id: "openrouter/x2", short: "x2", free: false, context: 32000, scores: {} },
      ],
    }) };
  }
  if (u === "/api/model") {
    OUT.passi.modelloChiesto = JSON.parse((o && o.body) || "{}").model;
    return { ok: false, status: 400,
             json: async () => ({ error: "modello non disponibile" }) };
  }
  if (u === "/api/provider") {
    OUT.passi.servizioChiesto = JSON.parse((o && o.body) || "{}").provider;
    // Come un 409 vero: il server dice anche qual e' lo stato reale,
    // ed e' quello che il menu deve mostrare.
    return { ok: false, status: 409, json: async () => ({
      error: "agente occupato",
      stato: { provider: "openrouter", chiavi: CHIAVI, motori: [] },
    }) };
  }
  return baseFetch(u, o);
};

(async function () {
  try {
    await disegnaProvider({ provider: "openrouter", chiavi: CHIAVI, motori: [] });
    await caricaModelli("openrouter", null);
    await attesa(50);

    const sel = document.getElementById("opt-model");
    const msg = document.getElementById("opt-provider-msg");
    OUT.passi.modelloIniziale = sel.value;
    sel.value = "openrouter/x2";
    sel.fire("change");
    await attesa(500);
    OUT.passi.modelloDopo = sel.value;
    OUT.passi.modelloMsg = msg.textContent;
    OUT.passi.modelloClasse = msg.className;

    const h = document.getElementById("provider-pick");
    const o = document.getElementById("opt-provider");
    OUT.passi.servizioPrima = [h.value, o.value];
    h.value = "groq";
    h.fire("change");
    await attesa(500);
    OUT.passi.servizioDopo = [h.value, o.value];
    OUT.passi.servizioMsg = msg.textContent;
    OUT.passi.servizioClasse = msg.className;
  } catch (e) {
    OUT.errori.push(e && e.message ? e.message : String(e));
  }
  console.log(JSON.stringify(OUT));
  process.exit(0);
})();

// Un errore non gestito del bundle non deve spegnere il probe prima
// che stampi: qui interessa cosa e' rimasto nel DOM, non il rumore.
process.on("unhandledRejection", (e) => {
  OUT.errori.push("reiezione non gestita: " + (e && e.message ? e.message : e));
});
