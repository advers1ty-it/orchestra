"""
Storico: le sessioni e i loro messaggi, su disco.

Perche' esiste: la conversazione viveva solo in RAM. Refresh del browser
e spariva; riavvio del server e spariva. Uno strumento su cui perdi il
lavoro a ogni ricarica non e' uno strumento.

SQLite e non JSON: si scrive un messaggio per volta senza riscrivere il
file, due turni sovrapposti non si corrompono, e leggere le ultime N
righe di una conversazione lunga non vuol dire caricarla tutta.

Le sessioni stanno accanto ai cataloghi, in
`%LOCALAPPDATA%\\orchestra` (vedi `dati.py`): stessa cartella,
dati di Orchestra che nessuno va a cercare in D:\\orchestra.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from . import redazione
from .dati import percorso

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessioni (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo      TEXT    NOT NULL DEFAULT '',
    modello     TEXT    NOT NULL DEFAULT '',
    provider    TEXT    NOT NULL DEFAULT '',
    bot         TEXT    NOT NULL DEFAULT '',
    -- Il progetto a cui appartiene la conversazione. Vuoto = nessun
    -- progetto (le chat nate prima di questa colonna restano qui, e
    -- valgono per chiunque invece di sparire dal filtro).
    progetto    TEXT    NOT NULL DEFAULT '',
    creata      REAL    NOT NULL,
    aggiornata  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS messaggi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sessione_id INTEGER NOT NULL REFERENCES sessioni(id) ON DELETE CASCADE,
    ruolo        TEXT NOT NULL,
    -- Identita' stabile: lo storico e' append-only, e senza uid due
    -- salvataggi dello stesso turno potrebbero duplicare le righe.
    uid         TEXT NOT NULL DEFAULT '',
    contenuto    TEXT NOT NULL DEFAULT '',
    ragionamento TEXT NOT NULL DEFAULT '',
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
    return percorso("storico.db")


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
            # Migrazione: DB vecchi senza la colonna `ragionamento`. ALTER
            # fallisce se la colonna esiste già, e va bene: il try la ignora.
            try:
                self._conn.execute(
                    "ALTER TABLE messaggi ADD COLUMN ragionamento TEXT "
                    "NOT NULL DEFAULT ''")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migrazione: i DB creati prima dei bot non hanno la colonna.
            # Default vuoto = conversazione dell'agente principale, che e'
            # il caso di tutte le righe gia' scritte.
            try:
                self._conn.execute(
                    "ALTER TABLE sessioni ADD COLUMN bot TEXT "
                    "NOT NULL DEFAULT ''")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migrazione: le conversazioni ora sanno a che progetto
            # appartengono. Le righe gia' scritte restano con '', e
            # vengono trattate come "senza progetto": visibili col
            # progetto attivo invece di sparire dalla cronologia.
            try:
                self._conn.execute(
                    "ALTER TABLE sessioni ADD COLUMN progetto TEXT "
                    "NOT NULL DEFAULT ''")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            # Migrazione: le righe scritte prima dello storico append-only
            # non hanno un uid. Se ne assegna uno a ciascuna, cosi' una
            # conversazione riaperta non viene reinserita da capo al primo
            # salvataggio (e il vecchio `salva_turno` non le cancella piu').
            try:
                self._conn.execute(
                    "ALTER TABLE messaggi ADD COLUMN uid TEXT "
                    "NOT NULL DEFAULT ''")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            self._conn.execute(
                "UPDATE messaggi SET uid = lower(hex(randomblob(16)))"
                " WHERE uid = ''")
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_messaggi_uid"
                " ON messaggi(sessione_id, uid)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessioni_progetto"
                " ON sessioni(progetto)")
            self._conn.commit()

    def chiudi(self) -> None:
        with self._lock:
            self._conn.close()

    # -- sessioni ----------------------------------------------------------

    def nuova_sessione(self, modello: str = "", provider: str = "",
                       titolo: str = "", bot: str = "",
                       progetto: str = "") -> int:
        progetto = (progetto or "").strip()
        ora = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessioni (titolo, modello, provider, bot,"
                " progetto, creata, aggiornata)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (titolo, modello, provider, bot, progetto, ora, ora))
            self._conn.commit()
            return int(cur.lastrowid)

    def imposta_progetto(self, sessione_id: int, progetto: str) -> bool:
        """Lega una conversazione al progetto indicato.

        Si usa alla creazione (col progetto attivo), quando l'utente
        cambia progetto a chat aperta, e aprendo una conversazione che
        un progetto ce l'aveva gia'.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessioni SET progetto = ? WHERE id = ?",
                ((progetto or "").strip(), sessione_id))
            self._conn.commit()
            return cur.rowcount > 0

    def elenco(self, limite: int = 100, bot: str | None = None,
               progetto: str = "") -> list[dict[str, Any]]:
        """Le sessioni più recenti, col conto dei messaggi.

        Il conto serve a distinguere una chat vuota — aperta per sbaglio
        e mai usata — da una con dentro il lavoro. Senza, l'elenco
        mostra righe tutte uguali.

        `bot` filtra per identita'. None = tutte le conversazioni (la
        cronologia completa), stringa = solo quelle di quel bot (quella
        che serve quando il bot si riapre). La distinzione conta: la
        cronologia dell'utente non deve sparire perche' un bot ha una
        chat sua.

        `progetto` filtra per progetto. Vuoto = nessun filtro (tutte).
        Quando c'e', entrano anche le conversazioni SENZA progetto:
        sono quelle nate prima di questa colonna, e nasconderle su ogni
        progetto sarebbe far sparire la cronologia di chi aggiorna.
        """
        criteri: list[str] = []
        parametri: list[Any] = []
        if bot is not None:
            criteri.append("s.bot = ?")
            parametri.append(bot)
        if progetto:
            criteri.append("(LOWER(s.progetto) = LOWER(?) OR s.progetto = '')")
            parametri.append(progetto.strip())
        where = ("WHERE " + " AND ".join(criteri)) if criteri else ""
        parametri.append(limite)
        with self._lock:
            righe = self._conn.execute(
                f"""
                SELECT s.id, s.titolo, s.modello, s.provider, s.bot,
                       s.progetto, s.creata, s.aggiornata,
                       (SELECT COUNT(*) FROM messaggi m
                         WHERE m.sessione_id = s.id AND m.ruolo IN ('user','assistant'))
                         AS n_messaggi
                  FROM sessioni s
                  {where}
                 ORDER BY s.aggiornata DESC
                 LIMIT ?
                """, tuple(parametri)).fetchall()
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
        # Il contenuto arriva dal modello, dai tool e (nel caso peggiore)
        # dall'utente che incolla una chiave per farsela controllare.
        # Lo storico e' su disco, indicizzato full-text e finisce nei
        # backup: si redige alla porta, non solo a monte.
        contenuto = redazione.redigi(contenuto)
        if nome:
            nome = redazione.redigi(nome)
        dati = None
        if tool_json is not None:
            dati = json.dumps(redazione.redigi_dati(tool_json), ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messaggi"
                " (sessione_id, ruolo, uid, contenuto, nome, tool_json, token, creata)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sessione_id, ruolo, uuid.uuid4().hex, contenuto, nome,
                 dati, token, time.time()))
            self._conn.execute(
                "UPDATE sessioni SET aggiornata = ? WHERE id = ?",
                (time.time(), sessione_id))
            self._conn.commit()
            return int(cur.lastrowid)

    def messaggi(self, sessione_id: int) -> list[dict[str, Any]]:
        with self._lock:
            righe = self._conn.execute(
                "SELECT id, sessione_id, uid, ruolo, contenuto, ragionamento,"
                " nome, tool_json, token, creata"
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

    def cerca(self, query: str, limite: int = 20,
              progetto: str = "") -> list[dict[str, Any]]:
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

        `progetto` restringe ai fatti di quel progetto, e include le
        conversazioni senza progetto (legacy): un filtro che fa sparire
        il passato non e' un filtro, e' una perdita.
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
        filtro = (" AND (LOWER(s.progetto) = LOWER(?) OR s.progetto = '')"
                  if progetto else "")
        tetto = max(1, min(int(limite or 20), 50))
        with self._lock:
            try:
                parametri: tuple[Any, ...] = ((frase, progetto.strip(), tetto)
                                              if progetto else (frase, tetto))
                righe = self._conn.execute(
                    "SELECT m.id AS msg_id, m.ruolo, m.contenuto,"
                    "       m.creata, s.id AS sessione_id, s.titolo,"
                    "       s.aggiornata, s.modello, s.progetto"
                    " FROM messaggi_fts"
                    " JOIN messaggi m ON m.id = messaggi_fts.rowid"
                    " JOIN sessioni s ON s.id = m.sessione_id"
                    " WHERE messaggi_fts MATCH ?"
                    + filtro +
                    " ORDER BY rank, m.creata DESC LIMIT ?",
                    parametri).fetchall()
            except Exception:
                # indice FTS mancante o DB vecchio: si torna al filtro su
                # contenuto, che è quello che faceva prima. Meglio lento che
                # muto.
                parametri = ((f"%{q.lower()}%", progetto.strip(), tetto)
                             if progetto else (f"%{q.lower()}%", tetto))
                righe = self._conn.execute(
                    "SELECT m.id AS msg_id, m.ruolo, m.contenuto, m.creata,"
                    "       s.id AS sessione_id, s.titolo, s.aggiornata,"
                    "       s.modello, s.progetto"
                    " FROM messaggi m JOIN sessioni s ON s.id = m.sessione_id"
                    " WHERE LOWER(m.contenuto) LIKE ?"
                    + filtro +
                    " ORDER BY m.creata DESC LIMIT ?",
                    parametri).fetchall()
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
        """Aggiunge i messaggi nuovi, senza riscrivere quelli gia' salvati.

        Lo storico e' append-only: gli id delle righe esistenti non devono
        cambiare, perche' la cronologia e' anche il bersaglio dei link e
        della ricerca. `uid` rende l'inserimento idempotente; l'intero
        blocco e' una transazione, quindi un errore a meta' non lascia un
        turno mezzo scritto.
        """
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                for m in messaggi:
                    tool_json = m.get("tool")
                    dati = (json.dumps(redazione.redigi_dati(tool_json),
                                       ensure_ascii=False)
                            if tool_json is not None else None)
                    uid = str(m.get("uid") or uuid.uuid4().hex)
                    self._conn.execute(
                        "INSERT OR IGNORE INTO messaggi"
                        " (sessione_id, ruolo, uid, contenuto, ragionamento,"
                        " nome, tool_json, token, creata)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (sessione_id, m.get("ruolo", ""), uid,
                         redazione.redigi(m.get("contenuto", "") or ""),
                         redazione.redigi(m.get("ragionamento", "") or ""),
                         m.get("nome"), dati,
                         m.get("token", 0), time.time()))
                self._conn.execute(
                    "UPDATE sessioni SET aggiornata = ?,"
                    " modello = COALESCE(NULLIF(?, ''), modello),"
                    " provider = COALESCE(NULLIF(?, ''), provider)"
                    " WHERE id = ?",
                    (time.time(), modello, provider, sessione_id))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise


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