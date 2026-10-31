"""Traccia persistente dei turni: cosa è successo, consultabile dopo.

Il problema che risolve: l'agent emette ~25 tipi di evento per turno
(ragionamento, tool_start/end, compaction, fallback, verifica,
gira_a_vuoto...), ma sono EFFIMERI — passano nel bridge e spariscono. Se
domani chiedi "perché quel task ha sbagliato?", l'unica risposta oggi è
"rilancialo e guarda". Che costa token e, se il task non è deterministico,
non riproduce lo stesso errore.

Qui si salva ogni turno su disco (SQLite, come lo storico). Una riga per
turno con il riepilogo, e gli eventi dentro: puoi riaprire la sequenza
esatta — quale tool ha chiamato, con che argomenti, cosa è tornato,
perché il loop si è fermato — senza ripetere niente.

Il principio: si registra, non si giudica. Nessun modello che interpreta
la traccia; sono i fatti grezzi. L'interpretazione la fa chi guarda, con
gli eventi sotto gli occhi invece di un riassunto che potrebbe mentire.

Perché SQLite e non un file di testo per turno: la traccia si CONSULTA
(ultimi turni, un turno per id, quanti errori), e una query batte leggere
N file. Stesso motivo dello storico.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

# La traccia condivide il DB dello storico: un posto solo per "cos'è
# successo", non due file da tenere allineati. La tabella è separata.
_DB = "storico.sqlite3"

_LOCK = threading.Lock()


def _db() -> sqlite3.Connection:
    from .storico import percorso_db
    conn = sqlite3.connect(percorso_db())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracce (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sessione_id INTEGER,
            ts REAL,
            durata_s REAL,
            esito TEXT,
            iterazioni INTEGER,
            tool_chiamate INTEGER,
            errori INTEGER,
            token INTEGER,
            modello TEXT,
            evento_finale TEXT,
            n_eventi INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS traccia_eventi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            traccia_id INTEGER,
            seq INTEGER,
            ts REAL,
            tipo TEXT,
            dati TEXT
        )
    """)
    conn.commit()
    return conn


class RegistratoreTurno:
    """Accumula gli eventi di UN turno e li salva alla fine.

    Nasce all'inizio del turno, vive per la sua durata, si chiude nel
    `finally` del worker. Se il turno muore a metà, la traccia di quello
    che è successo FINO A LÌ resta — ed è spesso la parte interessante,
    perché è dove si è rotto.
    """

    def __init__(self, sessione_id: int | None = None) -> None:
        self.sessione_id = sessione_id
        self.ts_inizio = time.time()
        self.eventi: list[dict[str, Any]] = []
        self.riepilogo: dict[str, Any] = {}
        self._chiuso = False

    def registra(self, tipo: str, dati: dict[str, Any] | None = None) -> None:
        if self._chiuso:
            return
        # I chunk di streaming (`ragionamento`, `contenuto`) arrivano a
        # centinaia per turno: 282 eventi per 2 iterazioni, illeggibile.
        # Per la diagnosi servono gli eventi STRUTTURALI — tool, verifica,
        # fallback, compaction, gira_a_vuoto — non ogni token. Questi due
        # li conto (quanto ha ragionato prima di rispondere è informazione)
        # ma non li accumulo uno a uno.
        if tipo in ("ragionamento", "contenuto"):
            self._contatore_stream = getattr(self, "_contatore_stream", 0) + 1
            return
        self.eventi.append({
            "ts": time.time(),
            "tipo": tipo,
            "dati": dati or {},
        })

    def imposta_riepilogo(self, **campi: Any) -> None:
        self.riepilogo.update(campi)

    def salva(self) -> int | None:
        """Scrive la traccia su disco. Torna l'id, o None se non si può.

        Silenziosa per scelta: un errore del DB non deve far cadere un
        turno che è già riuscito. La traccia è un strumento di diagnosi,
        non parte del risultato.
        """
        if self._chiuso:
            return self._id
        self._chiuso = True
        if not self.eventi:
            return None
        r = self.riepilogo
        try:
            with _LOCK:
                conn = _db()
                cur = conn.execute(
                    "INSERT INTO tracce (sessione_id, ts, durata_s, esito, "
                    "iterazioni, tool_chiamate, errori, token, modello, "
                    "evento_finale, n_eventi) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (self.sessione_id, self.ts_inizio,
                     time.time() - self.ts_inizio,
                     r.get("esito", ""),
                     r.get("iterazioni", 0),
                     r.get("tool_chiamate", 0),
                     r.get("errori", 0),
                     r.get("token", 0),
                     r.get("modello", ""),
                     r.get("evento_finale", ""),
                     len(self.eventi)))
                traccia_id = cur.lastrowid
                conn.executemany(
                    "INSERT INTO traccia_eventi (traccia_id, seq, ts, tipo, dati) "
                    "VALUES (?,?,?,?,?)",
                    [(traccia_id, i, e["ts"], e["tipo"],
                      json.dumps(e["dati"], ensure_ascii=False, default=str))
                     for i, e in enumerate(self.eventi)])
                conn.commit()
                conn.close()
            self._id = traccia_id
            return traccia_id
        except Exception:
            return None


def ultime(limite: int = 30, *, esito: str | None = None,
           solo_errori: bool = False) -> list[dict[str, Any]]:
    """Le tracce recenti, per la lista in UI.

    I filtri stanno QUI, non nel client: la lista e' tagliata dal
    `LIMIT`, e filtrare dopo aver letto 50 righe su 5000 non trova le
    tracce vecchie che interessano. "Perche' quel task e' fallito" e'
    spesso una domanda su un turno di ieri, non sull'ultimo.
    """
    try:
        limite = max(1, min(int(limite or 30), 500))
    except (TypeError, ValueError):
        limite = 30
    dove: list[str] = []
    parametri: list[Any] = []
    if esito:
        dove.append("esito = ?")
        parametri.append(str(esito))
    if solo_errori:
        dove.append("errori > 0")
    sql = (
        "SELECT id, sessione_id, ts, durata_s, esito, iterazioni, "
        "tool_chiamate, errori, token, modello, evento_finale, n_eventi "
        "FROM tracce"
        + (" WHERE " + " AND ".join(dove) if dove else "")
        + " ORDER BY ts DESC LIMIT ?"
    )
    try:
        with _LOCK:
            conn = _db()
            righe = conn.execute(sql, (*parametri, limite)).fetchall()
            conn.close()
        chiavi = ["id", "sessione_id", "ts", "durata_s", "esito",
                  "iterazioni", "tool_chiamate", "errori", "token",
                  "modello", "evento_finale", "n_eventi"]
        return [dict(zip(chiavi, r)) for r in righe]
    except Exception:
        return []


def apri(traccia_id: int) -> dict[str, Any] | None:
    """Una traccia completa, con tutti i suoi eventi in ordine."""
    try:
        with _LOCK:
            conn = _db()
            testa = conn.execute(
                "SELECT id, sessione_id, ts, durata_s, esito, iterazioni, "
                "tool_chiamate, errori, token, modello, evento_finale, n_eventi "
                "FROM tracce WHERE id = ?", (traccia_id,)).fetchone()
            if not testa:
                conn.close()
                return None
            eventi = conn.execute(
                "SELECT seq, ts, tipo, dati FROM traccia_eventi "
                "WHERE traccia_id = ? ORDER BY seq", (traccia_id,)).fetchall()
            conn.close()
        chiavi = ["id", "sessione_id", "ts", "durata_s", "esito",
                  "iterazioni", "tool_chiamate", "errori", "token",
                  "modello", "evento_finale", "n_eventi"]
        return {
            "riepilogo": dict(zip(chiavi, testa)),
            "eventi": [
                {"seq": s, "ts": t, "tipo": ti,
                 "dati": json.loads(d) if d else {}}
                for s, t, ti, d in eventi
            ],
        }
    except Exception:
        return None
