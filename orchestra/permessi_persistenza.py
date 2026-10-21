"""Dove stanno i permessi che non devono sparire.

"Sempre" e "mai" sono decisioni dell'utente che valgono oltre la
sessione: se l'utente ha premuto "sempre", il riavvio del server non puo'
far finta che non sia mai successo. Idem per "mai": un "no" che sparisce
e' un "no" che non vale.

Il file e' un JSON nella cartella dati dell'installazione (la stessa di
goals.json e del budget): due copie di Orchestra in due cartelle diverse
hanno permessi separati, senza configurazione.

Perche' un file e non un database: sono poche righe, si leggono a occhio,
e un file che si puo' ispezionare e' un file che si puo' correggere a
mano quando qualcosa va storto. La scrittura e' atomica (tmp + replace),
perche' un file troncato a meta' dalla corrente farebbe perdere tutti i
permessi di colpo — peggio del bug che si sta correggendo.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .dati import percorso as _percorso_dati

NOME_FILE = "permessi.json"

# Se il file non si puo' leggere o scrivere, il gate continua a funzionare
# in memoria: un problema di disco non deve trasformarsi in "nessuno puo'
# piu' lavorare". Il permesso si perde, ma il server resta in piedi.
_lock = threading.Lock()


def _path() -> str:
    return _percorso_dati(NOME_FILE)


def carica() -> dict[str, list[str]]:
    """Legge i permessi salvati. Un file rotto non blocca niente."""
    vuoto = {"sempre": [], "negati": []}
    try:
        with open(_path(), encoding="utf-8") as f:
            dati = json.load(f)
    except FileNotFoundError:
        return vuoto
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # File corrotto: meglio perderli che non partire. Il gate
        # riparte vuoto e chiede di nuovo, che e' il default sicuro.
        return vuoto
    if not isinstance(dati, dict):
        return vuoto
    out: dict[str, list[str]] = {}
    for sezione in ("sempre", "negati"):
        valori = dati.get(sezione)
        if not isinstance(valori, list):
            valori = []
        out[sezione] = [str(v) for v in valori if isinstance(v, (str, bytes))]
    return out


def salva(sempre: set[str] | list[str], negati: set[str] | list[str]) -> None:
    """Scrive i permessi. Fallisce in silenzio: e' un salvataggio."""
    dati = {
        "sempre": sorted(sempre),
        "negati": sorted(negati),
    }
    with _lock:
        path = _path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dati, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            # Se la scrittura fallisce, il permesso vale comunque per
            # questa sessione: siamo in memoria, non su disco.
            pass


def percorso_file() -> str:
    """Dove sta il file. Per i test e per i messaggi di errore."""
    return _path()
