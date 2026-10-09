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

-- Indice di ricerca sul CONTENUTO, non solo per sessione. Senza, l'unico
-- modo di trovare "quella cosa che avevamo detto" era aprire le
-- conversazioni una a una — e lo storico su disco serviva a conservare,
-- non a ritrovare.
--
-- Speculare, come nella memoria: la tabella FTS5 copia `contenuto` e si
-- può buttare e ricostruire da `messaggi` senza perdere niente.
CREATE VIRTUAL TABLE IF NOT EXISTS messaggi_fts USING fts5(
    contenuto, content='messaggi', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS messaggi_ai AFTER INSERT ON messaggi BEGIN
    INSERT INTO messaggi_fts(rowid, contenuto) VALUES (new.id, new.contenuto);
END;
CREATE TRIGGER IF NOT EXISTS messaggi_ad AFTER DELETE ON messaggi BEGIN
    INSERT INTO messaggi_fts(messaggi_fts, rowid, contenuto)
        VALUES ('delete', old.id, old.contenuto);
END;
CREATE TRIGGER IF NOT EXISTS messaggi_au AFTER UPDATE ON messaggi BEGIN
    INSERT INTO messaggi_fts(messaggi_fts, rowid, contenuto)
        VALUES ('delete', old.id, old.contenuto);
    INSERT INTO messaggi_fts(rowid, contenuto) VALUES (new.id, new.contenuto);
END;
"""


def _frammento(testo: str, parola: str, intorno: int = 180) -> str:
    """Il pezzo di messaggio intorno alla parola cercata.

    Un messaggio lungo restituito per intero è rumore: la parte che serve
    sta dove la parola appare, e il resto spinge fuori gli altri risultati.
    Se la parola non c'è (ricerca per sottostringa su più parole), si prende
    l'inizio, che è dove di solito sta il senso.
    """
    t = " ".join((testo or "").split())
    if len(t) <= intorno * 2:
        return t
    i = t.lower().find((parola or "").lower())
    if i < 0:
        return t[:intorno * 2] + "…"
    a = max(0, i - intorno)
    b = min(len(t), i + intorno)
    return ("…" if a > 0 else "") + t[a:b] + ("…" if b < len(t) else "")


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

    def cerca(self, query: str, limite: int = 20) -> list[dict[str, Any]]:
        """Cerca nel contenuto delle conversazioni passate.

        FTS5, non sottostringa. Ma il risultato non è la riga nuda: un
        frammento senza sapere di quale conversazione è non si può riaprire,
        e ritrovare una cosa che non si può riaprire è un modo raffinato di
        perderla. Per questo ogni risultato porta il titolo e l'id della
        sessione.

        Se l'indice è vuoto e i messaggi no, l'indice si rifà da sé. Un DB
        creato prima che l'FTS esistesse ha i messaggi e l'indice vuoto:
        senza questa riga la ricerca tornerebbe zero per sempre, e chi
        aggiorna non ha modo di sapere che deve ricostruire a mano.

        Le parole si quotano: una query con un apostrofo fa fallire la
        sintassi MATCH, e la ricerca tornerebbe vuota invece di dire che
        non ha trovato niente.
        """
        q = (query or "").strip()
        if not q:
            return []
        with self._lock:
            self._ripara_fts_se_vuoto()
        parole = [p for p in q.split() if p]
        if not parole:
            return []
        frase = " AND ".join(f'"{p}"' for p in parole)
        with self._lock:
            try:
                righe = self._conn.execute(
                    "SELECT m.id AS msg_id, m.ruolo, m.contenuto,"
                    "       m.creata, s.id AS sessione_id, s.titolo,"
                    "       s.aggiornata, s.modello"
                    " FROM messaggi_fts"
                    " JOIN messaggi m ON m.id = messaggi_fts.rowid"
                    " JOIN sessioni s ON s.id = m.sessione_id"
                    " WHERE messaggi_fts MATCH ?"
                    " ORDER BY rank, m.creata DESC LIMIT ?",
                    (frase, max(1, min(int(limite or 20), 50)))).fetchall()
            except Exception:
                # indice FTS mancante o DB vecchio: si torna al filtro su
                # contenuto, che è quello che faceva prima. Meglio lento che
                # muto.
                righe = self._conn.execute(
                    "SELECT m.id AS msg_id, m.ruolo, m.contenuto, m.creata,"
                    "       s.id AS sessione_id, s.titolo, s.aggiornata, s.modello"
                    " FROM messaggi m JOIN sessioni s ON s.id = m.sessione_id"
                    " WHERE LOWER(m.contenuto) LIKE ?"
                    " ORDER BY m.creata DESC LIMIT ?",
                    (f"%{q.lower()}%", max(1, min(int(limite or 20), 50)))).fetchall()
        fuori = []
        for r in righe:
            d = dict(r)
            testo = (d.get("contenuto") or "").strip()
            # Il frammento è tagliato intorno alla prima parola cercata:
            # un messaggio lungo restituito per intero è rumore, e la parte
            # che serve sta dove la parola appare.
            d["frammento"] = _frammento(testo, parole[0])
            fuori.append(d)
        return fuori

    def _ripara_fts_se_vuoto(self) -> None:
        """Se l'indice FTS è vuoto e i messaggi no, lo rifà.

        Da chiamare col lock già preso. Un DB nato prima che l'FTS
        esistesse ha i messaggi e l'indice vuoto: senza, la ricerca
        tornerebbe zero per sempre e non ci sarebbe modo di accorgersene.
        """
        try:
            n_fts = self._conn.execute(
                "SELECT COUNT(*) c FROM messaggi_fts").fetchone()["c"]
            n_msg = self._conn.execute(
                "SELECT COUNT(*) c FROM messaggi").fetchone()["c"]
            if n_fts == 0 and n_msg > 0:
                self._conn.execute(
                    "INSERT INTO messaggi_fts(messaggi_fts) VALUES ('rebuild')")
                self._conn.commit()
        except Exception:
            pass

    def ricostruisci_fts(self) -> int:
        """Rifa l'indice di ricerca dai messaggi. Torna quanti."""
        with self._lock:
            self._conn.execute("INSERT INTO messaggi_fts(messaggi_fts)"
                               " VALUES ('rebuild')")
            self._conn.commit()
            n = self._conn.execute("SELECT COUNT(*) c FROM messaggi").fetchone()["c"]
        return n

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