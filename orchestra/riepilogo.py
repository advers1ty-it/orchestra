"""Il riepilogo di fine turno: cosa e' cambiato, quanto e' costato.

PERCHE' ESISTE

`traccia.py` registra tutto, ma nessuno lo legge: la traccia serve a
capire dopo, e per aprire il dettaglio bisogna andarlo a cercare. Alla
fine di un turno lungo quello che manca e' una riga: e' andata, cosa ha
toccato, quanto e' costata.

Le tre domande a cui risponde sono quelle che si fanno davvero:

- "ha finito o si e' fermato?" — l'esito, tradotto dal codice interno in
  una parola che si capisce;
- "cosa ha toccato?" — i file del turno, con le righe aggiunte e tolte,
  presi dal checkpoint (gli stessi della vista diff);
- "quanto e' costato?" — token e dollari stimati.

Non e' un giudizio sul lavoro: non dice se il codice e' buono. Dice
cosa e' successo, che e' l'unica cosa che si puo' dire senza mentire.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_ULTIMO: dict[str, Any] = {}

_ESITI = {
    "": ("finito", "ok"),
    "complete": ("finito", "ok"),
    "troppi_errori_consecutivi": ("fermato: troppi errori di fila", "errore"),
    "gira_a_vuoto": ("fermato: stava ripetendo la stessa chiamata", "errore"),
    "budget_exceeded": ("fermato: budget esaurito", "errore"),
    "canceled_da_should_continue": ("annullato dall'utente", "annullato"),
    "canceled": ("annullato dall'utente", "annullato"),
    "solo_parole": ("fermato: aveva annunciato senza fare", "errore"),
    "annuncio_finale": ("finito, ma con un annuncio a vuoto", "avviso"),
    "troncato": ("fermato: risposta troncata dal tetto di token", "avviso"),
    "verifica_fallita": ("finito senza superare la verifica", "avviso"),
}


def esito_leggibile(codice: str) -> tuple[str, str]:
    """(testo per l'utente, gravita') da `stopped_because`."""
    codice = (codice or "").strip()
    if codice in _ESITI:
        return _ESITI[codice]
    if "cancel" in codice.lower() or "annull" in codice.lower():
        return ("annullato dall'utente", "annullato")
    if codice:
        # Un codice che non conosciamo si mostra com'e': meglio una
        # parola strana che un "finito" falso.
        return (codice.replace("_", " "), "avviso")
    return _ESITI[""]


def _durata(secondi: float) -> str:
    s = max(0, int(round(secondi or 0)))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _costo(usd: float) -> str:
    v = float(usd or 0)
    if v <= 0:
        return "n/d"
    if v < 0.01:
        return "< $0,01"
    return f"${v:.2f}"


def costruisci(*, stato: Any, modifiche: list[dict[str, Any]] | None = None,
               durata_s: float = 0.0, modello: str = "",
               traccia_id: int | None = None) -> dict[str, Any]:
    """Il riepilogo del turno, pronto per la UI e per l'API."""
    codice = str(getattr(stato, "stopped_because", "") or "")
    testo, gravita = esito_leggibile(codice)
    file: list[dict[str, Any]] = []
    visti: set[str] = set()
    for m in modifiche or []:
        percorso = str(m.get("percorso") or "?")
        # Lo stesso file toccato due volte e' una riga sola, con i totali:
        # elencarlo due volte fa sembrare il turno piu' grande di com'e'.
        if percorso in visti:
            for f in file:
                if f["percorso"] == percorso:
                    f["aggiunte"] += int(m.get("aggiunte") or 0)
                    f["tolte"] += int(m.get("tolte") or 0)
                    f["stato"] = m.get("stato") or f["stato"]
            continue
        visti.add(percorso)
        file.append({
            "percorso": percorso,
            "stato": m.get("stato") or "modificato",
            "aggiunte": int(m.get("aggiunte") or 0),
            "tolte": int(m.get("tolte") or 0),
        })
    token = int(getattr(stato, "total_tokens", 0) or 0)
    costo = float(getattr(stato, "total_cost_usd", 0.0) or 0.0)
    tool = int(getattr(stato, "tool_calls_made", 0) or 0)
    errori = int(getattr(stato, "tool_errors", 0) or 0)
    iterazioni = int(getattr(stato, "iterations", 0) or 0)

    pezzi = [testo, f"{_durata(durata_s)}"]
    if file:
        pezzi.append(f"{len(file)} file")
    if token:
        pezzi.append(f"{token:,} token".replace(",", "."))
    if costo:
        pezzi.append(_costo(costo))
    riga = " · ".join(pezzi)

    r: dict[str, Any] = {
        "esito": codice,
        "esito_testo": testo,
        "gravita": gravita,
        "durata_s": round(float(durata_s or 0), 1),
        "durata": _durata(durata_s),
        "iterazioni": iterazioni,
        "tool": tool,
        "errori": errori,
        "token": token,
        "costo_usd": round(costo, 6),
        "costo": _costo(costo),
        "modello": modello,
        "file": file,
        "n_file": len(file),
        "riga": riga,
        "traccia_id": traccia_id,
        "ts": time.time(),
    }
    with _LOCK:
        _ULTIMO.clear()
        _ULTIMO.update(r)
    return r


def ultimo() -> dict[str, Any]:
    """L'ultimo riepilogo, o {} se non c'e' ancora stato un turno."""
    with _LOCK:
        return dict(_ULTIMO)
