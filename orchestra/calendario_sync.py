"""Sincronizzazione del calendario: i calendari remoti, in sola lettura.

PERCHE' UN ABBONAMENTO E NON UN'APP OAUTH

Un accesso a Google Calendar o Outlook "vero" vuole un'applicazione
registrata, un client id, un client secret, un browser, un token che scade
e un rinnovo: quattro cose che l'utente non puo' fare dalla chat, e che
rendono la sincronizzazione una configurazione da mezz'ora. Tutti i
calendari pero' sanno esportare un indirizzo `.ics` privato (Google:
"indirizzo segreto in formato iCal"; Outlook: "pubblica calendario";
iCloud e Nextcloud lo hanno nativo). Quello e' un abbonamento: si legge,
non si scrive, e non serve nessuna credenziale oltre alla URL.

Quindi qui si scarica un `.ics` remoto, si tiene una copia locale, e le
letture la uniscono al calendario di Orchestra. La scrittura resta dove
sta: nel file locale. Un evento che viene da fuori e' marcato come tale e
non si cancella da qui — cancellarlo qui vorrebbe dire credere di averlo
cancellato anche di la', che non e' vero.

NIENTE DI SPECIALE NELLE RICHIESTE

Si usa `urllib` con If-None-Match e If-Modified-Since: la seconda
sincronizzazione di un calendario che non e' cambiato non scarica un byte,
e non c'e' un polling di fondo che consuma rete mentre l'utente dorme.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import calendario as cal
from .dati import cartella_dati, percorso

_DB = "calendario_sync.db"
CARTELLA = "calendario_fonti"

# Un calendario e' testo: 8 MB sono gia' un decennio di appuntamenti. Il
# tetto c'e' perche' una URL sbagliata puo' restituire un film.
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = 20
MAX_FONTI = 25

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS fonti (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL UNIQUE,
    url       TEXT NOT NULL,
    attiva    INTEGER NOT NULL DEFAULT 1,
    etag      TEXT NOT NULL DEFAULT '',
    modificato TEXT NOT NULL DEFAULT '',
    ultima    REAL NOT NULL DEFAULT 0,
    esito     TEXT NOT NULL DEFAULT '',
    eventi    INTEGER NOT NULL DEFAULT 0
);
"""


def percorso_db() -> str:
    return percorso(_DB)


def cartella_cache() -> str:
    return os.path.join(cartella_dati(), CARTELLA)


def _db() -> sqlite3.Connection:
    cartella_dati()
    conn = sqlite3.connect(percorso_db(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _cache_di(identificativo: int) -> str:
    return os.path.join(cartella_cache(), f"fonte-{identificativo}.ics")


def _riga(r: sqlite3.Row) -> dict[str, Any]:
    identificativo = int(r["id"])
    cache = _cache_di(identificativo)
    return {
        "id": identificativo,
        "nome": r["nome"] or "",
        "url": r["url"] or "",
        "attiva": bool(r["attiva"]),
        "etag": r["etag"] or "",
        "modificato": r["modificato"] or "",
        "ultima": float(r["ultima"] or 0),
        "esito": r["esito"] or "",
        "eventi": int(r["eventi"] or 0),
        "cache": cache,
        "scaricato": os.path.exists(cache),
    }


def _url_pulito(url: str) -> str:
    """Un indirizzo che si puo' scaricare, o un errore che spiega."""
    grezzo = (url or "").strip()
    if not grezzo:
        raise ValueError("serve l'indirizzo del calendario (un link .ics)")
    if len(grezzo) > 2000:
        raise ValueError("indirizzo troppo lungo (massimo 2000 caratteri)")
    if grezzo.lower().startswith("webcal://"):
        grezzo = "https://" + grezzo[len("webcal://"):]
    pezzi = urllib.parse.urlsplit(grezzo)
    if pezzi.scheme.lower() not in ("http", "https"):
        raise ValueError(
            f"indirizzo non supportato: '{pezzi.scheme or grezzo}'. Serve "
            f"http:// o https:// (webcal:// diventa https).")
    if not pezzi.netloc:
        raise ValueError(f"indirizzo incompleto: '{grezzo}'")
    if pezzi.username or pezzi.password:
        raise ValueError(
            "l'indirizzo non deve contenere utente e password: usa il "
            "link \"segreto\" che il calendario genera per la sola lettura")
    return urllib.parse.urlunsplit(pezzi)


def _butta_cache(identificativo: int) -> None:
    try:
        os.unlink(_cache_di(identificativo))
    except OSError:
        pass


def fonti() -> list[dict[str, Any]]:
    conn = _db()
    try:
        return [_riga(r) for r in
                conn.execute("SELECT * FROM fonti ORDER BY nome").fetchall()]
    finally:
        conn.close()


def _trova(nome: str) -> dict[str, Any] | None:
    cercato = " ".join(str(nome or "").split()).strip().lower()
    if not cercato:
        return None
    for fonte in fonti():
        if fonte["nome"].lower() == cercato or str(fonte["id"]) == cercato:
            return fonte
    return None


def aggiungi_fonte(nome: str, url: str, *, attiva: bool = True) -> dict[str, Any]:
    """Aggiunge (o corregge) una fonte. Stesso nome = aggiorna, non duplica."""
    nome = " ".join(str(nome or "").split()).strip()
    if not nome:
        raise ValueError("serve un nome per la fonte (per esempio 'lavoro')")
    if len(nome) > 60:
        raise ValueError("nome troppo lungo (massimo 60 caratteri)")
    pulito = _url_pulito(url)
    conn = _db()
    try:
        riga = conn.execute("SELECT * FROM fonti WHERE nome = ?",
                            (nome,)).fetchone()
        nuova = riga is None
        if nuova:
            quante = conn.execute("SELECT COUNT(*) FROM fonti").fetchone()[0]
            if quante >= MAX_FONTI:
                raise ValueError(f"troppe fonti: {quante} (massimo {MAX_FONTI})")
            conn.execute("INSERT INTO fonti (nome, url, attiva) VALUES (?, ?, ?)",
                         (nome, pulito, int(bool(attiva))))
        else:
            if (riga["url"] or "") != pulito:
                # Indirizzo nuovo: la copia vecchia non descrive piu' questa
                # fonte, e tenerla vorrebbe dire mostrare eventi di un altro
                # calendario sotto il nome di questo.
                _butta_cache(int(riga["id"]))
            conn.execute(
                "UPDATE fonti SET url = ?, attiva = ?, etag = '', "
                "modificato = '', esito = '' WHERE id = ?",
                (pulito, int(bool(attiva)), int(riga["id"])))
        conn.commit()
        fonte = _riga(conn.execute("SELECT * FROM fonti WHERE nome = ?",
                                   (nome,)).fetchone())
    finally:
        conn.close()
    fonte["nuova"] = nuova
    return fonte


def elimina_fonte(nome: str) -> bool:
    fonte = _trova(nome)
    if fonte is None:
        return False
    conn = _db()
    try:
        conn.execute("DELETE FROM fonti WHERE id = ?", (fonte["id"],))
        conn.commit()
    finally:
        conn.close()
    _butta_cache(fonte["id"])
    return True


def _salva_cache(identificativo: int, testo: str) -> str:
    cartella = cartella_cache()
    os.makedirs(cartella, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(dir=cartella, suffix=".ics")
    os.close(fd)
    try:
        with open(temporaneo, "w", encoding="utf-8", newline="") as f:
            f.write(testo)
        os.replace(temporaneo, _cache_di(identificativo))
    except Exception:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise
    return _cache_di(identificativo)


def _eventi_ics(testo: str) -> int:
    return testo.upper().count("BEGIN:VEVENT")


def _registra_esito(identificativo: int, esito: str, *,
                    etag: str | None = None,
                    modificato: str | None = None,
                    eventi: int | None = None,
                    toccata: bool = True) -> None:
    campi = ["esito = ?"]
    valori: list[Any] = [esito]
    if toccata:
        campi.append("ultima = ?")
        valori.append(time.time())
    if etag is not None:
        campi.append("etag = ?")
        valori.append(etag)
    if modificato is not None:
        campi.append("modificato = ?")
        valori.append(modificato)
    if eventi is not None:
        campi.append("eventi = ?")
        valori.append(eventi)
    valori.append(identificativo)
    conn = _db()
    try:
        conn.execute(f"UPDATE fonti SET {', '.join(campi)} WHERE id = ?",
                     valori)
        conn.commit()
    finally:
        conn.close()


def _scarica(fonte: dict[str, Any]) -> dict[str, Any]:
    richiesta = urllib.request.Request(fonte["url"], headers={
        "User-Agent": "Orchestra/calendario",
        "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.5",
    })
    if fonte.get("etag"):
        richiesta.add_header("If-None-Match", fonte["etag"])
    if fonte.get("modificato"):
        richiesta.add_header("If-Modified-Since", fonte["modificato"])
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            dati = risposta.read(MAX_BYTES + 1)
            if len(dati) > MAX_BYTES:
                raise ValueError(
                    f"il calendario supera {MAX_BYTES // (1024 * 1024)} MB: "
                    f"non e' un file di appuntamenti")
            testo = dati.decode("utf-8", errors="replace").lstrip("\ufeff").lstrip()
            if "BEGIN:VCALENDAR" not in testo.upper():
                raise ValueError(
                    "l'indirizzo non restituisce un calendario .ics (manca "
                    "BEGIN:VCALENDAR). Un link di una pagina web non e' un "
                    "abbonamento: serve il link iCal che il calendario "
                    "genera nelle impostazioni.")
            eventi = _eventi_ics(testo)
            _salva_cache(fonte["id"], testo)
            etag = risposta.headers.get("ETag") or ""
            modificato = risposta.headers.get("Last-Modified") or ""
    except urllib.error.HTTPError as e:
        if e.code == 304:
            _registra_esito(fonte["id"], "non modificato dall'ultima volta")
            return {**fonte, "ok": True, "nuovo": False,
                    "esito": "non modificato dall'ultima volta",
                    "eventi": fonte.get("eventi", 0)}
        esito = (f"errore: il server ha risposto {e.code} "
                 f"({e.reason}). Se il link e' privato, controlla di averlo "
                 f"copiato intero.")
        _registra_esito(fonte["id"], esito)
        return {**fonte, "ok": False, "esito": esito}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        motivo = getattr(e, "reason", e)
        esito = (f"errore: non raggiungibile ({motivo}). La copia locale "
                 f"resta quella di prima.")
        _registra_esito(fonte["id"], esito)
        return {**fonte, "ok": False, "esito": esito}
    except ValueError as e:
        esito = f"errore: {e}"
        _registra_esito(fonte["id"], esito)
        return {**fonte, "ok": False, "esito": esito}
    _registra_esito(fonte["id"], f"{eventi} eventi", etag=etag,
                    modificato=modificato, eventi=eventi)
    return {**fonte, "ok": True, "nuovo": True, "etag": etag,
            "modificato": modificato, "eventi": eventi,
            "esito": f"{eventi} eventi"}


def sincronizza(nome: str = "") -> list[dict[str, Any]]:
    """Scarica le fonti attive (o quella indicata) e torna l'esito di ognuna."""
    with _LOCK:
        if (nome or "").strip():
            fonte = _trova(nome)
            if fonte is None:
                raise ValueError(f"nessuna fonte chiamata '{nome}'")
            elenco = [fonte]
        else:
            elenco = fonti()
        risultati = []
        for fonte in elenco:
            if not fonte["attiva"]:
                risultati.append({**fonte, "ok": False,
                                  "esito": "disattiva: non scaricata"})
                continue
            risultati.append(_scarica(fonte))
        return risultati


def eventi_remoti(da: dt.datetime, a: dt.datetime,
                  fonte: str = "") -> list[dict[str, Any]]:
    """Gli eventi remoti nella finestra, dai file gia' scaricati.

    Non tocca la rete: sincronizzare e' una cosa che si chiede, non un
    effetto collaterale di una domanda su domani.
    """
    cercata = (fonte or "").strip().lower()
    fuori: list[dict[str, Any]] = []
    for voce in fonti():
        if not voce["attiva"]:
            continue
        if cercata and voce["nome"].lower() != cercata:
            continue
        if not os.path.exists(voce["cache"]):
            continue
        for evento in cal.eventi(da, a, file=voce["cache"]):
            evento["fonte"] = voce["nome"]
            evento["remoto"] = True
            fuori.append(evento)
    fuori.sort(key=lambda e: (e["inizio"], e["titolo"]))
    return fuori


def stato() -> str:
    """Una riga per fonte, leggibile, con quello che e' successo l'ultima volta."""
    elenco = fonti()
    if not elenco:
        return ("Nessun calendario sincronizzato. Per aggiungerne uno serve "
                "l'indirizzo iCal (per Google: impostazioni del calendario, "
                "\"indirizzo segreto in formato iCal\").")
    righe = []
    for voce in elenco:
        quando = (dt.datetime.fromtimestamp(voce["ultima"]).strftime(
            "%Y-%m-%d %H:%M") if voce["ultima"] else "mai")
        riga = f"  {voce['nome']} · {voce['url']}"
        riga += f" · {'attiva' if voce['attiva'] else 'disattiva'}"
        riga += f" · sincronizzata: {quando}"
        if voce["scaricato"]:
            riga += f" · {voce['eventi']} eventi in copia locale"
        if voce["esito"]:
            riga += f" · {voce['esito']}"
        righe.append(riga)
    return "Calendari sincronizzati (" + str(len(elenco)) + "):\n" + \
           "\n".join(righe)
