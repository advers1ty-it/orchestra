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
import json
import os
import re
import shutil
import time

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


def base_dati() -> str:
    """La cartella che contiene UNA SOTTOCARTELLA PER INSTALLAZIONE.

    Serve a elencarle tutte: l'hash identifica un'installazione ma non
    dice a quale percorso corrisponde, quindi senza questa cartella
    comune non ci sarebbe niente da elencare — solo da indovinare.

    Con ORCHESTRA_HOME impostata non esistono "altre" installazioni: il
    percorso e' esplicito, e si considera l'unica.
    """
    esplicita = os.environ.get("ORCHESTRA_HOME")
    if esplicita:
        return os.path.dirname(os.path.abspath(esplicita)) or os.path.abspath(esplicita)
    home = os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(_localappdata(), NOME_APP)
    return os.path.join(home, "." + NOME_APP)


def cartella_dati() -> str:
    """La cartella dove Orchestra scrive i propri dati. La crea se manca."""
    base = os.environ.get("ORCHESTRA_HOME")
    if not base:
        base = os.path.join(base_dati(), _hash_installazione())
    os.makedirs(base, exist_ok=True)
    return base


# File di stato che possono esistere nei percorsi vecchi e vanno ereditati.
# Whitelist chiusa: dalla cartella del pacchetto si prendono SOLO questi,
# mai il codice e mai il .env (le chiavi non si copiano fra installazioni).
FILE_STATO = {
    "memory.md", "memoria_config.json", "budget_global.json",
    "nous_auth.json", "goals.json", "cron.json", "token.txt",
    "storico.db", "storico.sqlite3", "memoria_indice.db",
    "catalog_groq.json", "catalog_nous.json", "catalog_openrouter.json",
}


def _percorsi_vecchi() -> list[str]:
    """Da dove ereditare i dati, in ordine di priorita'.

    1. La cartella del pacchetto (orchestra/orchestra/): e' dove le
       versioni prima dell'hash tenevano memoria, budget e token Nous.
    2. Il percorso legacy con il nome vecchio (hermes/orchestra).
    """
    pacchetto = os.path.dirname(os.path.abspath(__file__))
    return [pacchetto, _vecchio_percorso()]


def _dest_vuota(dst: str) -> bool:
    try:
        return os.path.getsize(dst) == 0
    except OSError:
        return True


def _vecchio_percorso() -> str:
    """Il percorso dati prima del rename: ~/AppData/Local/hermes/orchestra/."""
    home = os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(_localappdata(), "hermes", "orchestra")
    return os.path.join(home, ".hermes", "orchestra")


def migra_da_vecchio() -> list[str]:
    """Eredita i file di stato dai percorsi precedenti.

    Al primo avvio con la cartella hash, i dati sono ancora dove li
    tenevano le versioni vecchie (cartella del pacchetto, percorso con
    il nome vecchio). Senza questa migrazione, l'utente vedrebbe uno
    storico vuoto, una memoria vuota e perderebbe il token Nous.

    Regole sicure, in ordine:
    - la prima fonte che ha il file vince (pacchetto, poi legacy);
    - si copia se manca la destinazione, o se la destinazione e' un
      file vuoto e la fonte no (creato nuovo al posto di ereditato);
    - mai sovrascrivere una destinazione non vuota: due installazioni
      diverse hanno dati diversi di proposito, e un import non deve
      distruggere niente.

    I file non vengono cancellati dalle fonti: se qualcosa va storto,
    si puo' tornare indietro. Idempotente.

    Restituisce la lista dei file migrati.
    """
    nuovo = cartella_dati()
    migrati = []
    for vecchio in _percorsi_vecchi():
        if os.path.abspath(vecchio) == os.path.abspath(nuovo):
            continue
        if not os.path.isdir(vecchio):
            continue
        for nome in sorted(os.listdir(vecchio)):
            if nome not in FILE_STATO:
                continue
            src = os.path.join(vecchio, nome)
            dst = os.path.join(nuovo, nome)
            if not os.path.isfile(src):
                continue
            if os.path.exists(dst) and not _dest_vuota(dst):
                continue
            try:
                if os.path.getsize(src) == 0:
                    continue
                os.makedirs(nuovo, exist_ok=True)
                shutil.copy2(src, dst)
                migrati.append(nome)
            except OSError:
                pass
    return migrati


def percorso(nome_file: str) -> str:
    """Un file di dati dentro la cartella dati."""
    return os.path.join(cartella_dati(), nome_file)


# ---------------------------------------------------------------------------
# Quali installazioni esistono, e quale percorso corrisponde a ciascuna
# ---------------------------------------------------------------------------
#
# Il nome della cartella dati e' un hash del percorso dell'installazione:
# comodo per separare i dati, inutile per riconoscerli. "3f2a9c1b77de"
# non dice niente a nessuno, e l'utente con tre installazioni (quella in
# AppData, quella su D:, i server di prova) non puo' decidere quale
# salvare se non sa quale sta guardando.
#
# Percio' ogni cartella dati porta un `installazione.json` con il
# percorso scritto dentro. Non c'e' modo di ricavarlo dall'hash: si
# scrive quando l'app parte, ed e' l'unica cosa che rende leggibile
# l'elenco.

SEGNAPOSTO = "installazione.json"

# I file che solo una cartella dati ha. Servono a distinguere
# un'installazione da una cartella che per caso si trova li' accanto:
# sotto %LOCALAPPDATA%\orchestra finiscono anche una copia del codice,
# i test e perfino un Python — e "Salva tutti" non deve zippare 370 MB
# di node_modules perche' hanno un budget_global.json dentro.
NOMI_DATI = FILE_STATO | {
    "bots.db", "telegram.db", "lavori.db", "progetti.db",
    "memoria_indice.db", "permessi.json", "identita.json",
}


def _sembra_installazione(cartella: str) -> bool:
    """Vero se questa cartella e' una cartella dati di Orchestra.

    Due prove, e la seconda e' volutamente stretta: il segnaposto (che
    scrivono le versioni nuove), oppure un nome esadecimale di 12
    caratteri con almeno un file di dati (le installazioni vecchie,
    che il segnaposto non ce l'hanno). Una cartella di codice che
    contiene un budget_global.json ereditato non passa il secondo
    test, ed e' il motivo per cui il test sul nome c'e'.
    """
    if os.path.isfile(os.path.join(cartella, SEGNAPOSTO)):
        return True
    nome = os.path.basename(cartella.rstrip("\\/"))
    if not re.fullmatch(r"[0-9a-f]{12}", nome):
        return False
    try:
        nomi = set(os.listdir(cartella))
    except OSError:
        return False
    return bool(nomi & NOMI_DATI)


def _leggi_segnaposto(cartella: str) -> dict:
    try:
        with open(os.path.join(cartella, SEGNAPOSTO), "r", encoding="utf-8") as f:
            dati = json.load(f)
        return dati if isinstance(dati, dict) else {}
    except (OSError, ValueError):
        return {}


def registra_installazione(radice: str = "") -> bool:
    """Scrive il percorso di questa installazione nella sua cartella dati.

    Idempotente e silenzioso: se il segnaposto c'e' gia' e il percorso e'
    lo stesso, non tocca il disco. Scrive solo quando qualcosa cambia
    (primo avvio, o installazione spostata), perche' un file riscritto a
    ogni avvio e' un file che entra nei backup senza motivo.
    """
    cartella = cartella_dati()
    radice = os.path.abspath(radice or os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    precedente = _leggi_segnaposto(cartella)
    if str(precedente.get("percorso") or "") == radice:
        return False
    versione = ""
    try:
        from . import __version__ as _v

        versione = _v
    except Exception:  # noqa: BLE001 - il percorso conta piu' della versione
        pass
    dati = {
        "percorso": radice,
        "creato": precedente.get("creato") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "visto": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "versione": versione or precedente.get("versione") or "",
    }
    try:
        os.makedirs(cartella, exist_ok=True)
        with open(os.path.join(cartella, SEGNAPOSTO), "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def _misura(cartella: str) -> tuple[int, int, float]:
    """Quanti file, quanti byte, e quando e' stata toccata l'ultima volta."""
    file_n = 0
    byte = 0
    ultimo = 0.0
    for radice, _cartelle, nomi in os.walk(cartella):
        # La sottocartella `backup` contiene gli archivi: contarla
        # gonfierebbe la dimensione dei dati con il backup dei dati.
        if os.path.basename(radice) == "backup" and radice != cartella:
            _cartelle[:] = []
            continue
        for nome in nomi:
            pieno = os.path.join(radice, nome)
            try:
                info = os.stat(pieno)
            except OSError:
                continue
            file_n += 1
            byte += info.st_size
            ultimo = max(ultimo, info.st_mtime)
    return file_n, byte, ultimo


def _voce(cartella: str, corrente: bool) -> dict:
    dati = _leggi_segnaposto(cartella)
    file_n, byte, ultimo = _misura(cartella)
    return {
        "id": os.path.basename(cartella.rstrip("\\/")),
        "dati": cartella,
        "percorso": str(dati.get("percorso") or ""),
        "versione": str(dati.get("versione") or ""),
        "creato": str(dati.get("creato") or ""),
        "file": file_n,
        "byte": byte,
        "modificato": ultimo,
        "corrente": corrente,
    }


def installazioni() -> list[dict]:
    """Tutte le cartelle dati di questo utente, la corrente per prima.

    Con ORCHESTRA_HOME impostata non si elenca il resto: quel percorso e'
    una scelta esplicita, e mostrare installazioni estranee in un
    ambiente di test sarebbe rumore (o peggio, un backup fatto sul
    profilo sbagliato).
    """
    corrente = os.path.abspath(cartella_dati())
    if os.environ.get("ORCHESTRA_HOME"):
        return [_voce(corrente, True)]
    voci: list[dict] = []
    try:
        nomi = sorted(os.listdir(base_dati()))
    except OSError:
        nomi = []
    for nome in nomi:
        pieno = os.path.join(base_dati(), nome)
        if not os.path.isdir(pieno) or os.path.abspath(pieno) == corrente:
            continue
        if not _sembra_installazione(pieno):
            continue
        voci.append(_voce(pieno, False))
    voci.append(_voce(corrente, True))
    # Prima la corrente, poi le altre dalla piu' usata di recente: chi
    # apre l'elenco sta cercando la sua, non una a caso.
    voci.sort(key=lambda v: (not v["corrente"], -float(v.get("modificato") or 0)))
    return voci
