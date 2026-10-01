"""Verificatori che eseguono il codice del modello.

Finora un task di codice si verificava guardando se il file conteneva
una parola e se una funzione restituiva un numero in un caso solo.
Tutti i modelli passavano: era una prova di esistenza, non di
capacita'.

Qui si esegue. Il file che il modello ha scritto viene compilato, la
funzione chiamata con argomenti noti, e il risultato confrontato con
quello atteso. Un modello scrive codice che sembra giusto e fallisce
sul caso limite: e' li' che i punteggi si separano.

Sul pericolo di eseguire codice ricevuto: si esegue in un processo
separato, con un timeout, e il file vive nella directory temporanea
del task. Non e' un sandbox, e non e' dichiarato tale — e' un
compito di valutazione, non un posto dove girare codice estraneo.
"""

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Callable

# Il wrapper gira come figlio: un loop infinito qui dentro bloccherebbe
# il benchmark per sempre, e un benchmark che si blocca sembra un
# crash. Il timeout e' il tetto, e il figlio muore con lui.
_WRAPPER = r"""
import json, sys, importlib.util
spec = importlib.util.spec_from_file_location("soluzione", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(json.dumps({"errore": f"import: {type(e).__name__}: {e}"}))
    raise SystemExit(0)
risultati = []
for chiamata in json.loads(sys.argv[2]):
    try:
        fn = getattr(mod, chiamata["nome"], None)
        if fn is None:
            risultati.append({"errore": f"manca {chiamata['nome']}"})
            continue
        risultati.append({"valore": fn(*chiamata.get("args", []))})
    except Exception as e:
        risultati.append({"errore": f"{type(e).__name__}: {e}"})
print(json.dumps({"risultati": risultati}, default=str))
"""


def esegui(path: str, chiamate: list[dict[str, Any]], timeout: float = 10.0) -> list[Any]:
    """Esegue il file e restituisce i valori, o un errore per chiamata."""
    if not os.path.exists(path):
        return [{"errore": f"il file {path} non esiste"}]
    d = tempfile.mkdtemp()
    w = os.path.join(d, "w.py")
    with open(w, "w", encoding="utf-8") as f:
        f.write(_WRAPPER)
    try:
        r = subprocess.run(
            [sys.executable, w, path, json.dumps(chiamate)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return [{"errore": f"non termina in {timeout:.0f}s"}]
    for riga in reversed((r.stdout or "").strip().split("\n")):
        if riga.strip().startswith("{"):
            try:
                return json.loads(riga)["risultati"]
            except (json.JSONDecodeError, KeyError):
                continue
    return [{"errore": (r.stderr or r.stdout or "nessun output")[-120:]}]


def _uguale(ottenuto: Any, atteso: Any) -> bool:
    """Confronto che sopporta i numeri come li pensa un essere umano.

    Un modello che restituisce 0.30000000000000004 invece di 0.3 ha
    ragione; uno che restituisce "3" invece di 3 no. Float e int si
    confrontano con una tolleranza, il resto no.
    """
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


def v_esegui(path: str, funzione: str, prove: list[tuple[list, Any]]) -> Callable:
    """Il file deve esportare `funzione` e rispondere bene a ogni prova.

    Ogni prova e' una coppia (argomenti, valore atteso), dove
    `argomenti` e' la lista di cio' che si passa alla funzione. Per una
    funzione che prende una lista, quindi, la prova e' `([[1, 2, 3]],
    2.0)`: la lista interna e' l'argomento, quella esterna e' la
    chiamata. Il doppio livello di parentesi sembra un dettaglio e non
    lo e' — scritto male chiama media(1, 2, 3) e fallisce per un
    motivo che non c'entra con la capacita' del modello.

    Tutte le prove devono passare: e' il punto della curva di
    difficolta', perche' il caso facile e' quello che tutti sanno fare.
    """
    chiamate = [{"nome": funzione, "args": list(a)} for a, _ in prove]
    attesi = [v for _, v in prove]

    def _verifica(work: str) -> tuple[bool, str]:
        reali = esegui(os.path.join(work, path), chiamate)
        # Un errore che riguarda il FILE non e' una prova fallita:
        # nessuna prova e' mai partita, e dire "1 prove su 4" fa
        # sembrare che il modello abbia sbagliato tre volte quando non
        # e' partito niente. Sono due fatti diversi e portano a due
        # domande diverse: il modello ha scritto il file, e l'hai
        # scritto bene?
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
