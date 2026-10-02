
// Gira davvero con node, dentro vm non funzionerebbe: vm non ha
// require, e un file del modello che lo usa morirebbe con
// "require is not defined" prima di arrivare al suo codice. Non si
// puo' simulare Node dentro una vm.
//
// Il file del modello non viene toccato: resta quello che ha
// scritto, con i suoi import e i suoi require.
const path = require('path');
const target = path.resolve(process.argv[2]);
const chiamate = JSON.parse(process.argv[3]);

(async () => {
  let mod;
  try {
    mod = require(target);
  } catch (e) {
    mod = null;
    if (e && (e.code === 'ERR_REQUIRE_ESM' ||
              /Cannot use import statement/.test(e.message))) {
      // e' un modulo ES: si importa dinamicamente
      try {
        mod = await import('file://' + target);
      } catch (e2) {
        process.stdout.write(JSON.stringify({ errore: 'caricamento: ' + e2.message }));
        return;
      }
    } else {
      process.stdout.write(JSON.stringify({ errore: 'caricamento: ' + e.message }));
      return;
    }
  }
  const out = [];
  for (const c of chiamate) {
    let fn = mod && (mod[c.nome] || mod.default);
    if (typeof fn !== 'function' && typeof mod === 'function') fn = mod;
    if (typeof fn !== 'function') {
      // NOTA DI SICUREZZA, e non un riflesso: qui si esegue codice
      // scritto dal modello. E' esattamente il compito del
      // verificatore — un benchmark che non eseguisse il codice non
      // misurerebbe niente, e su Python vale la stessa cosa da quando
      // esegui() importa il file del modello in un processo figlio.
      //
      // Il contenuto non e' un input esterno da sanitizzare: e' un
      // artefatto del benchmark, prodotto dal modello che si sta
      // valutando, ed e' eseguito in un processo separato con un tetto
      // di tempo. Il file non viene riscritto ne' corretto: se il
      // modello scrive codice che non gira, il task fallisce.
      try {
        const fs2 = require('fs');
        const src = fs2.readFileSync(target, 'utf8');
        // Una dichiarazione `function nome()` dentro il corpo di new
        // Function è una LOCALE: non finisce sull'oggetto passato come
        // argomento. Per raggiungerla bisogna farla restituire, e il
        // nome lo sappiamo già — è quello che il task cerca.
        const corpo = src + '\n;return (typeof ' + c.nome +
                       " !== 'undefined') ? " + c.nome + ' : null;';
        // eslint-disable-next-line no-new-func
        const f = new Function('exports', 'module', 'require', corpo);
        const ambito = {};
        fn = f(ambito, { exports: ambito }, require);
      } catch (e) {
        fn = null;
      }
    }
    if (typeof fn !== 'function') {
      out.push({ errore: 'manca ' + c.nome });
      continue;
    }
    try {
      const v = await fn.apply(null, c.args || []);
      // NaN e Infinity diventano null con JSON.stringify, e allora un
      // modello che risponde NaN invece di null — l'errore esatto che
      // il task vuole prendere — passerebbe indistinguibile. Si
      // controlla prima, e si scrive come stringa: la verifica deve
      // poter dire "NaN" invece di "null".
      if (typeof v === 'number' && !Number.isFinite(v)) {
        out.push({ valore: String(v) });
      } else {
        out.push({ valore: v === undefined ? null : v });
      }
    } catch (e) {
      out.push({ errore: e.message });
    }
  }
  process.stdout.write(JSON.stringify({ risultati: out }));
})();
