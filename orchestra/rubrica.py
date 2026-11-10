"""Rubrica: i contatti, in un database nella cartella dati.

PERCHE' NON SI USA LA POSTA COME RUBRICA

La casella sa chi ti ha scritto, non chi conosci: un cliente che non ti ha
ancora mandato niente non esiste, un fornitore esiste solo dentro la
vecchia conversazione. E cercare "l'email di Mario" in 4.000 messaggi e'
una cosa che l'agente fa, costa token e ogni tanto sbaglia.

Qui invece c'e' un elenco solo: nome, email, telefono, azienda, note. E'
la stessa forma che serve a un'azienda (il fornitore, il commercialista)
e a una casa (il dentista, l'idraulico): cambia il contenuto, non la
struttura.

NIENTE DOPPIONI

`aggiungi` cerca prima per email: un contatto che esiste gia' viene
AGGIORNATO, non duplicato. E' quello che serve quando l'agente rilegge un
biglietto da visita o reincontra un cliente, e senza questa regola dopo
sei mesi la rubrica ha tre "Mario Rossi" e nessuno sa quale sia quello
giusto.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from typing import Any

from .dati import cartella_dati, percorso

_DB = "rubrica.db"
_LOCK = threading.RLock()

# Quanti contatti si restituiscono al massimo: una ricerca larga ("a")
# non deve riempire il contesto del modello.
MAX_RISULTATI = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS contatti (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL DEFAULT '',
    email     TEXT NOT NULL DEFAULT '',
    telefono  TEXT NOT NULL DEFAULT '',
    azienda   TEXT NOT NULL DEFAULT '',
    note      TEXT NOT NULL DEFAULT '',
    creato    REAL NOT NULL,
    aggiornato REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS contatti_email ON contatti(email);
CREATE INDEX IF NOT EXISTS contatti_nome ON contatti(nome);
"""

CAMPI = ("nome", "email", "telefono", "azienda", "note")


def percorso_db() -> str:
    return percorso(_DB)


def _db() -> sqlite3.Connection:
    cartella_dati()
    conn = sqlite3.connect(percorso_db(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _riga(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "nome": r["nome"] or "",
        "email": r["email"] or "",
        "telefono": r["telefono"] or "",
        "azienda": r["azienda"] or "",
        "note": r["note"] or "",
        "creato": float(r["creato"] or 0),
        "aggiornato": float(r["aggiornato"] or 0),
    }


def _norm(valore: Any) -> str:
    return " ".join(str(valore or "").split()).strip()


def _solo_cifre(valore: str) -> str:
    return re.sub(r"\D", "", valore or "")


def tutti(limite: int = 200) -> list[dict[str, Any]]:
    with _LOCK, _db() as conn:
        righe = conn.execute(
            "SELECT * FROM contatti ORDER BY LOWER(nome) LIMIT ?",
            (max(1, int(limite)),)).fetchall()
    return [_riga(r) for r in righe]


def cerca(testo: str = "", limite: int = MAX_RISULTATI) -> list[dict[str, Any]]:
    """I contatti che contengono il testo in un campo qualsiasi.

    Con i numeri si cerca anche in forma di sole cifre: "+39 333 123" e
    "333123" sono lo stesso telefono, e chi cerca non deve indovinare in
    che modo e' stato scritto in rubrica.
    """
    limite = max(1, min(int(limite or MAX_RISULTATI), MAX_RISULTATI))
    testo = _norm(testo)
    with _LOCK, _db() as conn:
        if not testo:
            righe = conn.execute(
                "SELECT * FROM contatti ORDER BY LOWER(nome) LIMIT ?",
                (limite,)).fetchall()
            return [_riga(r) for r in righe]
        ago = f"%{testo.lower()}%"
        righe = conn.execute(
            "SELECT * FROM contatti WHERE LOWER(nome) LIKE ? "
            "OR LOWER(email) LIKE ? OR LOWER(telefono) LIKE ? "
            "OR LOWER(azienda) LIKE ? OR LOWER(note) LIKE ? "
            "ORDER BY LOWER(nome) LIMIT ?",
            (ago, ago, ago, ago, ago, limite)).fetchall()
        fuori = [_riga(r) for r in righe]
        cifre = _solo_cifre(testo)
        if cifre and len(cifre) >= 3 and len(fuori) < limite:
            visti = {c["id"] for c in fuori}
            for riga in conn.execute("SELECT * FROM contatti").fetchall():
                contatto = _riga(riga)
                if contatto["id"] in visti:
                    continue
                if cifre in _solo_cifre(contatto["telefono"]):
                    fuori.append(contatto)
                    if len(fuori) >= limite:
                        break
    return fuori


def per_id(contatto_id: int | str) -> dict[str, Any] | None:
    try:
        ident = int(contatto_id)
    except (TypeError, ValueError):
        return None
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT * FROM contatti WHERE id = ?",
                         (ident,)).fetchone()
    return _riga(r) if r else None


def _per_email(email: str) -> dict[str, Any] | None:
    email = _norm(email).lower()
    if not email:
        return None
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT * FROM contatti WHERE LOWER(email) = ? "
                         "ORDER BY id LIMIT 1", (email,)).fetchone()
    return _riga(r) if r else None


def aggiungi(nome: str = "", email: str = "", telefono: str = "",
             azienda: str = "", note: str = "") -> dict[str, Any]:
    """Crea un contatto, o aggiorna quello che ha la stessa email.

    Torna il contatto salvato piu' `aggiornato`: True se esisteva gia'.
    Un contatto senza ne' nome ne' email ne' telefono non e' un contatto,
    e' una riga vuota: si rifiuta invece di riempire la rubrica di niente.
    """
    campi = {
        "nome": _norm(nome), "email": _norm(email),
        "telefono": _norm(telefono), "azienda": _norm(azienda),
        "note": str(note or "").strip(),
    }
    if not any(campi[c] for c in ("nome", "email", "telefono")):
        raise ValueError("serve almeno un nome, un'email o un telefono")
    ora = time.time()
    esistente = _per_email(campi["email"])
    with _LOCK, _db() as conn:
        if esistente:
            # Si aggiorna solo quello che e' arrivato: reinserire un
            # contatto con la sola email non deve cancellare il telefono
            # che era gia' scritto.
            nuovi = {k: v for k, v in campi.items() if v}
            if nuovi:
                assegnazioni = ", ".join(f"{k} = ?" for k in nuovi)
                conn.execute(
                    f"UPDATE contatti SET {assegnazioni}, aggiornato = ? "
                    f"WHERE id = ?",
                    (*nuovi.values(), ora, esistente["id"]))
                conn.commit()
            salvato = per_id(esistente["id"]) or esistente
            return {**salvato, "aggiornato": True}
        cur = conn.execute(
            "INSERT INTO contatti (nome, email, telefono, azienda, note,"
            " creato, aggiornato) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campi["nome"], campi["email"], campi["telefono"], campi["azienda"],
             campi["note"], ora, ora))
        conn.commit()
        nuovo_id = int(cur.lastrowid)
    return {**(per_id(nuovo_id) or {"id": nuovo_id, **campi}),
            "aggiornato": False}


def modifica(contatto_id: int | str, **campi: Any) -> dict[str, Any] | None:
    """Cambia i campi indicati. None se l'id non esiste."""
    attuale = per_id(contatto_id)
    if attuale is None:
        return None
    nuovi = {}
    for chiave in CAMPI:
        if chiave in campi and campi[chiave] is not None:
            valore = str(campi[chiave])
            nuovi[chiave] = valore.strip() if chiave == "note" else _norm(valore)
    if not nuovi:
        return attuale
    assegnazioni = ", ".join(f"{k} = ?" for k in nuovi)
    with _LOCK, _db() as conn:
        conn.execute(f"UPDATE contatti SET {assegnazioni}, aggiornato = ? "
                     f"WHERE id = ?",
                     (*nuovi.values(), time.time(), int(attuale["id"])))
        conn.commit()
    return per_id(attuale["id"])


def elimina(contatto_id: int | str) -> bool:
    try:
        ident = int(contatto_id)
    except (TypeError, ValueError):
        return False
    with _LOCK, _db() as conn:
        cur = conn.execute("DELETE FROM contatti WHERE id = ?", (ident,))
        conn.commit()
        return cur.rowcount > 0


def conta() -> int:
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT COUNT(*) AS n FROM contatti").fetchone()
    return int(r["n"] if r else 0)


def formatta(contatto: dict[str, Any]) -> str:
    """Una riga per il modello: cosa serve per decidere, non tutta la scheda."""
    pezzi = [f"#{contatto['id']}", contatto["nome"] or "(senza nome)"]
    if contatto["azienda"]:
        pezzi.append(contatto["azienda"])
    if contatto["email"]:
        pezzi.append(contatto["email"])
    if contatto["telefono"]:
        pezzi.append(contatto["telefono"])
    riga = " · ".join(pezzi)
    if contatto["note"]:
        nota = contatto["note"].strip().replace("\n", " ")
        riga += f" — {nota[:120]}"
    return riga
