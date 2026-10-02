"""Verificatori che eseguono JavaScript con Node.

Senza esecuzione, un task di JavaScript si verifica guardando se il
file contiene una parola — e ogni modello passa. Il caso limite, che e'
dove la difficolta' sta, non si vede in un file: si vede quando lo
chiami con l'input che rompe l'algoritmo ovvio.

Node c'e' gia' in questo ambiente (lo usa il test del bundle
frontend), quindi non serve un interprete Python travestito: si
esegue JavaScript come JavaScript, che e' anche l'unico modo per
chiedere al modello il file che vuoi tu e non uno che ne assomiglia.

Come in `esegui` per Python: processo separato e tetto. Un ciclo
infinito dentro il verificatore bloccherebbe il benchmark e sembrerebbe
un crash — e un benchmark che sembra crashato si smette di guardare.
"""

import json
import os
import subprocess
from typing import Any, Callable

_WRAPPER = r"""
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
"""


def esegui_node(path: str, chiamate: list[dict[str, Any]], timeout: float = 15.0) -> list[Any]:
    """Esegue il file JS e restituisce i valori, o un errore per chiamata."""
    if not os.path.exists(path):
        return [{"errore": f"il file {path} non esiste"}]
    # Percorso ASSOLUTO: node non risolve un percorso relativo come
    # argomento, e fallisce con "Cannot find module" prima ancora di
    # guardare il file del modello. Il messaggio che ne risulta parla
    # di un modulo mancante che invece c'era, che e' il genere di
    # errore che fa perdere mezz'ora.
    d = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "_nodewrap"))
    try:
        os.makedirs(d, exist_ok=True)
        w = os.path.join(d, "wrap.js")
        with open(w, "w", encoding="utf-8") as f:
            f.write(_WRAPPER)
    except OSError as e:
        return [{"errore": f"non riesco a preparare il wrapper: {e}"}]
    try:
        r = subprocess.run(
            ["node", w, path, json.dumps(chiamate)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return [{"errore": "node non è installato: i task JavaScript non si verificano"}]
    except subprocess.TimeoutExpired:
        return [{"errore": f"non termina in {timeout:.0f}s"}]
    txt = (r.stdout or "").strip()
    if not txt:
        # node è morto prima di scrivere: un errore di sintassi, per
        # esempio. "risposta vuota" non dice niente, e il messaggio
        # del task deve poter distinguere questo da un modello che ha
        # sbagliato la logica: sono due problemi in due posti diversi.
        righe = [r.strip() for r in (r.stderr or "").split("\n") if r.strip()]
        return [{"errore": (righe[0] if righe else "nessun output")[-140:]}]
    try:
        dato = json.loads(txt)
    except json.JSONDecodeError:
        dato = {}
    # il wrapper scrive {errore: ...} quando il file non si carica, e
    # non un elenco di risultati. Preso per "risposta vuota" si
    # nascondevano gli errori di sintassi dietro una frase che sembra
    # un problema di rete.
    if "risultati" not in dato and "errore" in dato:
        return [{"errore": str(dato["errore"])[:140]}]
    if "risultati" not in dato:
        return [{"errore": "risposta vuota"}]
    try:
        return dato["risultati"]
    except json.JSONDecodeError:
        # vm puo' stampare roba insieme: si prende l'ultima riga JSON
        for riga in reversed(txt.split("\n")):
            if riga.strip().startswith("{"):
                try:
                    d2 = json.loads(riga)
                    return d2.get("risultati") or [{"errore": str(d2.get("errore", ""))[:140]}]
                except json.JSONDecodeError:
                    continue
        return [{"errore": txt[-140:]}]


def _uguale(ottenuto: Any, atteso: Any) -> bool:
    """Confronto che sopporta i numeri come li pensa un essere umano."""
    if isinstance(atteso, float) or isinstance(ottenuto, float):
        try:
            return abs(float(ottenuto) - float(atteso)) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(atteso, list) and isinstance(ottenuto, list):
        return len(atteso) == len(ottenuto) and all(
            _uguale(a, b) for a, b in zip(ottenuto, atteso))
    if isinstance(atteso, dict) and isinstance(ottenuto, dict):
        return atteso.keys() == ottenuto.keys() and all(
            _uguale(ottenuto[k], atteso[k]) for k in atteso)
    return ottenuto == atteso


def v_esegui_js(path: str, funzione: str, prove: list[tuple[list, Any]]) -> Callable:
    """Come `v_esegui`, per JavaScript. Stessa convenzione degli argomenti."""
    chiamate = [{"nome": funzione, "args": list(a)} for a, _ in prove]
    attesi = [v for _, v in prove]

    def _verifica(work: str) -> tuple[bool, str]:
        reali = esegui_node(os.path.join(work, path), chiamate)
        if len(reali) == 1 and "errore" in reali[0] and len(attesi) > 1:
            return False, "non eseguibile: " + str(reali[0]["errore"])[:140]
        if len(reali) != len(attesi):
            return False, f"eseguite {len(reali)} prove su {len(attesi)}"
        sbagli = []
        for (args, atteso), reale in zip(prove, reali):
            if "errore" in reale:
                sbagli.append(f"args={args} -> {reale['errore'][:60]}")
            elif not _uguale(reale["valore"], atteso):
                sbagli.append(f"args={args} -> {reale['valore']!r}, atteso {atteso!r}")
        if sbagli:
            return False, f"{len(sbagli)}/{len(attesi)} prove sbagliate: " + \
                           "; ".join(sbagli)[:200]
        return True, f"{len(attesi)}/{len(attesi)} prove"

    return _verifica


def node_disponibile() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
