"""
Storico: le sessioni e i loro messaggi, su disco.

Perche' esiste: la conversazione viveva solo in RAM. Refresh del browser
e spariva; riavvio del server e spariva. Uno strumento su cui perdi il
lavoro a ogni ricarica non e' uno strumento.

SQLite e non JSON: si scrive un messaggio per volta senza riscrivere il
file, due turni sovrapposti non si corrompono, e leggere le ultime N
righe di una conversazione lunga non vuol dire caricarla tutta.

Le sessioni stanno accanto ai cataloghi, in
`~/AppData/Local/hermes/orchestra/`: stessa cartella, stessa logica --
dati di Orchestra che nessuno va a cercare in D:\\orchestra.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessioni (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo      TEXT    NOT NULL DEFAULT '',
    modello     TEXT    NOT NULL DEFAULT '',
    provider    TEXT    NOT NULL DEFAULT '',
    creata      REAL    NOT NULL,
    aggiornata  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS messaggi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sessione_id INTEGER NOT NULL REFERENCES sessioni(id) ON DELETE CASCADE,
    ruolo        TEXT NOT NULL,
    contenuto    TEXT NOT NULL DEFAULT '',
    nome         TEXT,
    tool_json    TEXT,
    token        INTEGER NOT NULL DEFAULT 0,
    creata       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messaggi_sessione
    ON messaggi(sessione_id, id);
"""


def percorso_db() -> str:
    """Lo stesso metodo dei cataloghi, così i dati stanno in un posto solo."""
    base = os.environ.get("ORCHESTRA_HOME")
    if not base:
        home = os.environ.get("HERMES_HOME") or os.path.expanduser("~")
        if os.name == "nt":
            se_hermes = home.rstrip("\\/").lower().endswith("hermes")
            base = (os.path.join(home, "orchestra") if se_hermes
                    else os.path.join(home, "AppData", "Local", "hermes", "orchestra"))
        else:
            base = os.path.join(home, ".orchestra")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "storico.db")


class Storico:
    """Unico punto di accesso ai dati. Thread-safe: il server HTTP è
    multithread e il turno gira in un thread suo."""

    def __init__(self, percorso: str | None = None) -> None:
        self.percorso = percorso or percorso_db()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.percorso, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def chiudi(self) -> None:
        with self._lock:
            self._conn.close()

    # -- sessioni ----------------------------------------------------------

    def nuova_sessione(self, modello: str = "", provider: str = "",
                       titolo: str = "") -> int:
        ora = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessioni (titolo, modello, provider, creata, aggiornata)"
                " VALUES (?, ?, ?, ?, ?)",
                (titolo, modello, provider, ora, ora))
            self._conn.commit()
            return int(cur.lastrowid)

    def elenco(self, limite: int = 100) -> list[dict[str, Any]]:
        """Le sessioni più recenti, col conto dei messaggi.

        Il conto serve a distinguere una chat vuota — aperta per sbaglio
        e mai usata — da una con dentro il lavoro. Senza, l'elenco
        mostra righe tutte uguali.
        """
        with self._lock:
            righe = self._conn.execute(
                """
                SELECT s.id, s.titolo, s.modello, s.provider,
                       s.creata, s.aggiornata,
                       (SELECT COUNT(*) FROM messaggi m
                         WHERE m.sessione_id = s.id AND m.ruolo IN ('user','assistant'))
                         AS n_messaggi
                  FROM sessioni s
                 ORDER BY s.aggiornata DESC
                 LIMIT ?
                """, (limite,)).fetchall()
        return [dict(r) for r in righe]

    def sessione(self, sessione_id: int) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM sessioni WHERE id = ?", (sessione_id,)).fetchone()
        return dict(r) if r else None

    def titolo_se_vuoto(self, sessione_id: int, testo: str) -> None:
        """Il titolo si prende dal primo messaggio, se non l'ha avuto.

        Una sessione si apre prima che l'utente scriva, quindi all'inizio
        non c'è niente da mettere come titolo. Il primo messaggio è la
        scelta naturale, e tagliato: un titolo lungo quanto il prompt non
        si legge in una lista.
        """
        with self._lock:
            s = self._conn.execute(
                "SELECT titolo FROM sessioni WHERE id = ?", (sessione_id,)).fetchone()
            if s is None or (s["titolo"] or "").strip():
                return
            pulito = " ".join((testo or "").split())
            titolo = pulito[:60] + ("…" if len(pulito) > 60 else "")
            self._conn.execute(
                "UPDATE sessioni SET titolo = ?, aggiornata = ? WHERE id = ?",
                (titolo, time.time(), sessione_id))
            self._conn.commit()

    def rinomina(self, sessione_id: int, titolo: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessioni SET titolo = ?, aggiornata = ? WHERE id = ?",
                (titolo.strip(), time.time(), sessione_id))
            self._conn.commit()

    def elimina(self, sessione_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messaggi WHERE sessione_id = ?",
                               (sessione_id,))
            self._conn.execute("DELETE FROM sessioni WHERE id = ?", (sessione_id,))
            self._conn.commit()

    def tocca(self, sessione_id: int, modello: str = "",
              provider: str = "") -> None:
        """Aggiorna il timestamp, e il modello se è cambiato.

        Serve all'ordinamento dell'elenco: una sessione riaperta deve
        risalire in cima, altrimenti la lista non rispecchia l'uso.
        """
        with self._lock:
            if modello or provider:
                self._conn.execute(
                    "UPDATE sessioni SET aggiornata = ?,"
                    " modello = COALESCE(NULLIF(?, ''), modello),"
                    " provider = COALESCE(NULLIF(?, ''), provider)"
                    " WHERE id = ?",
                    (time.time(), modello, provider, sessione_id))
            else:
                self._conn.execute(
                    "UPDATE sessioni SET aggiornata = ? WHERE id = ?",
                    (time.time(), sessione_id))
            self._conn.commit()

    # -- messaggi ----------------------------------------------------------

    def aggiungi_messaggio(self, sessione_id: int, ruolo: str, contenuto: str,
                           nome: str | None = None, tool_json: Any = None,
                           token: int = 0) -> int:
        """Salva un messaggio. Chiamato a fine turno, non a ogni token:
        un turno interrotto non deve lasciare metà risposta che al
        ricaricamento sembra una risposta completa."""
        dati = None
        if tool_json is not None:
            dati = json.dumps(tool_json, ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messaggi"
                " (sessione_id, ruolo, contenuto, nome, tool_json, token, creata)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sessione_id, ruolo, contenuto, nome, dati, token, time.time()))
            self._conn.execute(
                "UPDATE sessioni SET aggiornata = ? WHERE id = ?",
                (time.time(), sessione_id))
            self._conn.commit()
            return int(cur.lastrowid)

    def messaggi(self, sessione_id: int) -> list[dict[str, Any]]:
        with self._lock:
            righe = self._conn.execute(
                "SELECT id, ruolo, contenuto, nome, tool_json, token, creata"
                " FROM messaggi WHERE sessione_id = ? ORDER BY id", (sessione_id,)
            ).fetchall()
        fuori = []
        for r in righe:
            d = dict(r)
            if d.get("tool_json"):
                try:
                    d["tool"] = json.loads(d["tool_json"])
                except Exception:
                    d["tool"] = None
            fuori.append(d)
        return fuori

    def salva_turno(self, sessione_id: int, messaggi: list[dict[str, Any]],
                    modello: str = "", provider: str = "") -> None:
        """Salva una conversazione intera in un colpo.

        Usato quando la sessione viene ripresa e il suo stato in memoria
        è già completo: riscrivere tutto è più semplice che cercare quali
        righe mancano, e il numero di messaggi è nell'ordine delle
        centinaia, non dei milioni.
        """
        with self._lock:
            self._conn.execute("DELETE FROM messaggi WHERE sessione_id = ?",
                               (sessione_id,))
            for m in messaggi:
                tool_json = m.get("tool")
                dati = (json.dumps(tool_json, ensure_ascii=False)
                        if tool_json is not None else None)
                self._conn.execute(
                    "INSERT INTO messaggi"
                    " (sessione_id, ruolo, contenuto, nome, tool_json, token, creata)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sessione_id, m.get("ruolo", ""), m.get("contenuto", ""),
                     m.get("nome"), dati, m.get("token", 0), time.time()))
            self.tocca(sessione_id, modello, provider)


# Istanza condivisa. Il server ne ha uno solo, ma la sessione e la UI
# possono toccare il DB da thread diversi.
_istanza: Storico | None = None
_lock_istanza = threading.Lock()


def storico() -> Storico:
    global _istanza
    if _istanza is None:
        with _lock_istanza:
            if _istanza is None:
                _istanza = Storico()
    return _istanza