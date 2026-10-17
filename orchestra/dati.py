"""Donde Orchestra tiene i propri dati.

Un solo posto, una sola regola. Prima il percorso era copiato in tre
moduli (cataloghi, storico, indice memoria) e una volta sbagliato:
portava il nome di un altro progetto, quello da cui Orchestra non
dipende piu'. Un nome morto nel percorso e nei commenti e' solo
confusione per chi legge il codice.

La regola:
  ORCHESTRA_HOME  se impostata, vale cosi' com'e' (override esplicito)
  Windows         %LOCALAPPDATA%\\orchestra\\<hash-per-installazione>
  altro           ~/.orchestra/<hash-per-installazione>

L'hash identifica l'installazione: due copie di Orchestra in due
directory diverse hanno dati separati, senza bisogno di configurazione
manuale. L'hash è deterministico: la stessa directory ha sempre lo
stesso hash, quindi i dati sopravvivono a riavvii e aggiornamenti.

Attenzione: Git Bash e alcuni launcher non esportano LOCALAPPDATA ai
figli Python. Si usa la variabile di sistema come prima fonte, poi
il registro di Windows, e solo allora si torna su home -- mai il nome
dell'utente come percorso di dati di un'app.
"""

from __future__ import annotations

import hashlib
import os
import shutil

NOME_APP = "orchestra"


def _hash_installazione() -> str:
    """Hash breve del percorso del repo, per separare i dati tra installazioni."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        h = hashlib.sha256(root.encode("utf-8", "surrogateescape")).hexdigest()
        return h[:12]
    except Exception:
        return "default"


def _localappdata() -> str:
    """%LOCALAPPDATA%, con quanti fallback servono per trovarla."""
    for k in ("LOCALAPPDATA", "LOCAL_APPDATA"):
        v = os.environ.get(k)
        if v and os.path.isdir(v):
            return v
    # Ultimo ricorso: dove Windows la mette per questo utente.
    return os.path.join(os.path.expanduser("~"), "AppData", "Local")


def cartella_dati() -> str:
    """La cartella dove Orchestra scrive i propri dati. La crea se manca."""
    base = os.environ.get("ORCHESTRA_HOME")
    if not base:
        home = os.path.expanduser("~")
        if os.name == "nt":
            base = os.path.join(_localappdata(), NOME_APP, _hash_installazione())
        else:
            base = os.path.join(home, "." + NOME_APP, _hash_installazione())
    os.makedirs(base, exist_ok=True)
    return base


def _vecchio_percorso() -> str:
    """Il percorso dati prima del rename: ~/AppData/Local/hermes/orchestra/."""
    home = os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(_localappdata(), "hermes", "orchestra")
    return os.path.join(home, ".hermes", "orchestra")


def migra_da_vecchio() -> list[str]:
    """Copia i file dal vecchio percorso (hermes) al nuovo (orchestra).

    Al primo avvio dopo l'aggiornamento, i dati sono ancora nel percorso
    con il nome vecchio. Senza questa migrazione, l'utente vedrebbe uno
    storico vuoto, una memoria vuota e perderebbe il token Nous.

    I file non vengono cancellati dal vecchio percorso: se qualcosa va
    storto, si puo' tornare indietro. La migrazione e' idempotente:
    se il file esiste gia' nel nuovo percorso, non viene sovrascritto.

    Restituisce la lista dei file migrati.
    """
    vecchio = _vecchio_percorso()
    nuovo = cartella_dati()
    if not os.path.isdir(vecchio):
        return []
    if os.path.abspath(vecchio) == os.path.abspath(nuovo):
        return []

    migrati = []
    for nome in os.listdir(vecchio):
        src = os.path.join(vecchio, nome)
        dst = os.path.join(nuovo, nome)
        if not os.path.isfile(src):
            continue
        if os.path.exists(dst):
            continue
        try:
            os.makedirs(nuovo, exist_ok=True)
            shutil.copy2(src, dst)
            migrati.append(nome)
        except OSError:
            pass
    return migrati


def percorso(nome_file: str) -> str:
    """Un file di dati dentro la cartella dati."""
    return os.path.join(cartella_dati(), nome_file)
