"""Domande dell'agente all'utente, con una risposta libera.

PERCHE' ESISTE

I permessi hanno gia' un canale: una modale, quattro scelte, il tool
fermo. Ma le quattro scelte rispondono a "posso toccare questo file?",
non a "questo campo si chiama `nome` o `name`?" — e a quella domanda
non si risponde con un si' o un no.

Senza un canale, il modello ha due strade: indovinare, e scoprire dopo
tre file che aveva scelto l'ipotesi sbagliata, oppure fermarsi e
scrivere "mi serve sapere X" come testo, lasciando il turno finito. La
seconda e' onesta ma costosa: l'utente deve riformulare tutto, e il
contesto del lavoro in corso e' andato.

Qui il tool si ferma come per un permesso, la domanda arriva in chat, e
la risposta torna al modello dentro lo stesso turno.

COSA NON E'

Non e' una chat: una domanda per volta, testo libero, nessuna storia.
Se non c'e' nessuno a rispondere (CLI, benchmark, test) il tool lo
dice subito e il modello deve scegliere un'ipotesi e dichiararla,
invece di aspettare cinque minuti un utente che non esiste.

La scadenza e' la stessa dei permessi: cinque minuti, poi la domanda
muore. Una domanda lasciata aperta non deve tenere fermo un thread per
sempre.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

# Oltre questo una "domanda" non e' una domanda: e' il prompt di sistema
# incollato per sbaglio, e nella modale non si legge.
MAX_TESTO = 2000
MAX_OPZIONI = 6
MAX_OPZIONE = 200
# Quanto si aspetta una risposta. Lo stesso dei permessi: chi non
# risponde in cinque minuti non sta guardando, e il turno deve poter
# finire.
TIMEOUT = 300.0

_LOCK = threading.RLock()
_attesa: dict[str, dict[str, Any]] = {}
_risposte: dict[str, str] = {}
# Il canale per raggiungere la UI. Lo imposta la webapp: senza, il tool
# sa che non c'e' nessuno a cui chiedere e non aspetta.
_emetti: Callable[[dict[str, Any]], None] | None = None


def imposta_canale(fn: Callable[[dict[str, Any]], None] | None) -> None:
    global _emetti
    _emetti = fn


def canale_attivo() -> bool:
    return _emetti is not None


def crea(testo: str, opzioni: list[str] | None = None) -> dict[str, Any]:
    """Registra una domanda in attesa e restituisce il suo evento.

    Le opzioni sono suggerimenti, non una scelta obbligata: la UI le
    mostra come bottoni che riempiono il campo, e la risposta resta
    libera. Un elenco chiuso sarebbe un permesso travestito.
    """
    domanda = " ".join(str(testo or "").split()).strip()
    if not domanda:
        raise ValueError("la domanda e' vuota")
    if len(domanda) > MAX_TESTO:
        domanda = domanda[:MAX_TESTO].rstrip() + "…"
    pulite = []
    for o in (opzioni or [])[:MAX_OPZIONI]:
        testo_opzione = " ".join(str(o or "").split()).strip()
        if testo_opzione:
            pulite.append(testo_opzione[:MAX_OPZIONE])
    d: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "testo": domanda,
        "opzioni": pulite,
        "ts": time.time(),
    }
    with _LOCK:
        _attesa[d["id"]] = d
    return d


def invia(d: dict[str, Any]) -> bool:
    """Manda la domanda alla UI. False se non c'e' un canale o fallisce.

    Si emette FUORI dal lock: l'emit puo' fare I/O, e tenerlo fermo
    mentre un altro thread risponde e' il modo di trasformare una
    domanda in un blocco.
    """
    fn = _emetti
    if fn is None:
        return False
    try:
        fn(d)
    except Exception:  # noqa: BLE001 - un canale rotto non ferma il tool
        return False
    return True


def rispondi(domanda_id: str, testo: str) -> bool:
    """Registra la risposta. False se la domanda non e' piu' in attesa.

    Togliere la domanda dall'attesa QUI e' quello che rende un secondo
    clic innocuo: la prima risposta vince, la seconda trova il posto
    vuoto e non sovrascrive niente.
    """
    domanda_id = str(domanda_id or "").strip()
    risposta = str(testo or "").strip()
    if not domanda_id or not risposta:
        return False
    with _LOCK:
        if domanda_id not in _attesa:
            return False
        _attesa.pop(domanda_id, None)
        _risposte[domanda_id] = risposta[:MAX_TESTO]
    return True


def attendi(domanda_id: str, timeout: float = TIMEOUT) -> str | None:
    """Aspetta la risposta. None se scade o la domanda sparisce."""
    scadenza = time.monotonic() + timeout
    while True:
        with _LOCK:
            risposta = _risposte.pop(domanda_id, None)
            viva = domanda_id in _attesa
        if risposta is not None:
            return risposta
        if not viva:
            # annullata (o mai esistita): non c'e' niente da aspettare.
            return None
        if time.monotonic() >= scadenza:
            with _LOCK:
                _attesa.pop(domanda_id, None)
                _risposte.pop(domanda_id, None)
            return None
        time.sleep(0.05)


def annulla(domanda_id: str) -> bool:
    with _LOCK:
        cera = _attesa.pop(str(domanda_id or ""), None) is not None
        _risposte.pop(str(domanda_id or ""), None)
    return cera


def in_attesa() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_attesa.values())
