"""Lavori durevoli: una coda che non muore insieme al processo.

PERCHE' ESISTE

Le code in memoria sono comode finche' il server resta acceso. Un lavoro
messo in coda, un riavvio, e la coda sparisce: il bot non sa piu' che
doveva fare quella cosa, e l'utente non lo scopre finche' non la aspetta.
Per un orchestratore e' il difetto peggiore, perche' colpisce proprio il
caso in cui lo si lascia lavorare da solo.

Qui il lavoro e' una riga SQLite. Lo stato, il testo, i tentativi e
l'ultimo errore stanno su disco; il filo che lo esegue e' solo il
consumatore. Se il processo muore, la riga resta.

LA REGOLA ONESTA SULLA RIPRESA

Un turno dell'agente non e' idempotente: puo' aver gia' scritto un file,
lanciato un comando, speso token. Per questo un lavoro trovato `in_corso`
a un riavvio NON viene rieseguito da solo: diventa `interrotto`, con il
motivo, e si riprova esplicitamente. I lavori ancora `in_attesa` invece
ripartono: non hanno ancora toccato niente.

L'unita' atomica e' il turno. Riprendere a meta' di una tool call
richiederebbe checkpoint dentro l'Agent e una semantica per ogni tool;
finche' non c'e', meglio dire "interrotto" che fingere una ripresa che
puo' duplicare gli effetti.

STATI

    in_attesa   in coda, non ancora iniziato
    in_corso    rivendicato da un consumatore
    completato  finito con un risultato
    fallito     finito con un errore
    interrotto  il processo e' morto mentre lo eseguiva
    annullato   fermato dall'utente

`in_attesa` e `in_corso` sono gli unici stati attivi e contano per il
tetto della coda. Gli altri sono terminali e restano come storico.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

from .dati import percorso as percorso_dati

_DB = "lavori.db"

STATI = ("in_attesa", "in_corso", "completato", "fallito",
         "interrotto", "annullato")
ATTIVI = ("in_attesa", "in_corso")
TERMINALI = ("completato", "fallito", "interrotto", "annullato")
RIPROVABILI = ("fallito", "interrotto")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lavori (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            TEXT    NOT NULL,
    chiave          TEXT    NOT NULL,
    titolo          TEXT    NOT NULL DEFAULT '',
    payload         TEXT    NOT NULL DEFAULT '{}',
    stato           TEXT    NOT NULL DEFAULT 'in_attesa',
    tentativi       INTEGER NOT NULL DEFAULT 0,
    max_tentativi   INTEGER NOT NULL DEFAULT 1,
    creato          REAL    NOT NULL,
    aggiornato      REAL    NOT NULL,
    avviato         REAL    NOT NULL DEFAULT 0,
    finito          REAL    NOT NULL DEFAULT 0,
    heartbeat       REAL    NOT NULL DEFAULT 0,
    errore          TEXT    NOT NULL DEFAULT '',
    risultato       TEXT    NOT NULL DEFAULT '',
    checkpoint      TEXT    NOT NULL DEFAULT '{}'
);

-- La ricerca del prossimo lavoro e' sempre per (tipo, chiave, stato):
-- e' l'ordine in cui il consumatore guarda la coda.
CREATE INDEX IF NOT EXISTS idx_lavori_coda
    ON lavori(tipo, chiave, stato, id);

-- Il riepilogo del pannello legge tutti i lavori di una chiave, dal
-- piu' recente. Senza indice, con anni di storico, diventa una scansione.
CREATE INDEX IF NOT EXISTS idx_lavori_chiave
    ON lavori(tipo, chiave, id);
"""


def percorso_db() -> str:
    return percorso_dati(_DB)


def _conn() -> sqlite3.Connection:
    """Una connessione pronta, con WAL e attesa sui lock.

    Connessione per operazione: i fili dei bot sono pochi e le scritture
    sono brevi. Condividere una connessione fra thread con SQLite e'
    possibile ma richiede piu' disciplina di quanta ne serva qui.
    `BEGIN IMMEDIATE` nelle transazioni e' quello che rende atomico il
    claim anche se due consumatori guardano la stessa coda.
    """
    conn = sqlite3.connect(percorso_db(), timeout=15.0,
                           isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def _tx() -> Iterator[sqlite3.Connection]:
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _testo(valore: Any, *, max_len: int = 0) -> str:
    out = str(valore or "").strip()
    return out[:max_len] if max_len > 0 else out


def _json_carica(testo: Any, default: Any) -> Any:
    try:
        valore = json.loads(str(testo or ""))
    except (TypeError, ValueError):
        return default
    return valore if isinstance(valore, type(default)) else default


def _json_scrive(valore: Any) -> str:
    return json.dumps(valore, ensure_ascii=False, default=str)


def _riga(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "tipo": str(r["tipo"]),
        "chiave": str(r["chiave"]),
        "titolo": str(r["titolo"] or ""),
        "payload": _json_carica(r["payload"], {}),
        "stato": str(r["stato"]),
        "tentativi": int(r["tentativi"] or 0),
        "max_tentativi": int(r["max_tentativi"] or 1),
        "creato": float(r["creato"] or 0.0),
        "aggiornato": float(r["aggiornato"] or 0.0),
        "avviato": float(r["avviato"] or 0.0),
        "finito": float(r["finito"] or 0.0),
        "heartbeat": float(r["heartbeat"] or 0.0),
        "errore": str(r["errore"] or ""),
        "risultato": str(r["risultato"] or ""),
        "checkpoint": _json_carica(r["checkpoint"], {}),
    }


def _voce(job: dict[str, Any]) -> dict[str, Any]:
    """La forma breve che serve al pannello, senza il payload intero."""
    testo = str((job.get("payload") or {}).get("testo") or "")
    checkpoint = job.get("checkpoint")
    worktree = (checkpoint.get("worktree")
                if isinstance(checkpoint, dict) else None)
    merge = checkpoint.get("merge") if isinstance(checkpoint, dict) else None
    return {
        "id": int(job["id"]),
        "stato": str(job["stato"]),
        "ok": job["stato"] == "completato",
        "testo": testo[:200],
        "risposta": str(job.get("risultato") or ""),
        "errore": str(job.get("errore") or ""),
        "tentativi": int(job.get("tentativi") or 0),
        "creato": float(job.get("creato") or 0.0),
        "finito": float(job.get("finito") or 0.0),
        # Il checkout isolato del lavoro, quando c'e'. La UI lo mostra
        # accanto all'esito: senza, l'utente non saprebbe dove sono
        # finiti i file che il bot ha scritto.
        "worktree": worktree if isinstance(worktree, dict) else None,
        # La proposta di merge del bot: l'utente la vede e decide. Un
        # lavoro senza proposta non mostra nessun pulsante.
        "merge": merge if isinstance(merge, dict) else None,
    }


def accoda(tipo: str, chiave: str, payload: dict[str, Any] | None = None,
           *, titolo: str = "", max_tentativi: int = 1,
           limite: int = 0) -> dict[str, Any]:
    """Mette un lavoro in coda e lo restituisce.

    `limite` comprende sia l'attesa sia quello in corso: e' il tetto che
    impedisce a un doppio clic di produrre una fila di turni a pagamento.
    Zero significa nessun tetto, per i chiamanti che lo gestiscono altrove.
    """
    tipo = _testo(tipo)
    chiave = _testo(chiave)
    if not tipo:
        raise ValueError("serve un tipo di lavoro")
    if not chiave:
        raise ValueError("serve una chiave per il lavoro")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("il payload di un lavoro deve essere un oggetto")
    try:
        max_tentativi = max(1, int(max_tentativi))
        limite = max(0, int(limite))
    except (TypeError, ValueError) as e:
        raise ValueError("tentativi o limite non validi") from e

    ora = time.time()
    with _tx() as conn:
        if limite:
            attivi = int(conn.execute(
                "SELECT COUNT(*) FROM lavori WHERE tipo = ? AND chiave = ?"
                " AND stato IN ('in_attesa', 'in_corso')",
                (tipo, chiave)).fetchone()[0])
            if attivi >= limite:
                raise RuntimeError(
                    f"troppi lavori in coda (max {limite}) per {chiave!r}")
        cur = conn.execute(
            "INSERT INTO lavori (tipo, chiave, titolo, payload, stato,"
            " max_tentativi, creato, aggiornato) VALUES (?, ?, ?, ?,"
            " 'in_attesa', ?, ?, ?)",
            (tipo, chiave, _testo(titolo, max_len=200),
             _json_scrive(payload or {}), max_tentativi, ora, ora))
        job_id = int(cur.lastrowid)
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (job_id,)).fetchone()
        return _riga(r)


def ottieni(lavoro_id: int | str) -> dict[str, Any] | None:
    try:
        ident = int(lavoro_id)
    except (TypeError, ValueError):
        return None
    conn = _conn()
    try:
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
    finally:
        conn.close()
    return _riga(r) if r else None


def prossimo(tipo: str, chiave: str) -> dict[str, Any] | None:
    """Prende in carico il lavoro piu' vecchio di quella coda.

    `BEGIN IMMEDIATE` + `UPDATE ... WHERE stato = 'in_attesa'` sono la
    parte importante: due processi possono chiamare questa funzione nello
    stesso istante, ma solo uno porta a casa la riga.
    """
    tipo = _testo(tipo)
    chiave = _testo(chiave)
    if not tipo or not chiave:
        return None
    ora = time.time()
    with _tx() as conn:
        r = conn.execute(
            "SELECT * FROM lavori WHERE tipo = ? AND chiave = ?"
            " AND stato = 'in_attesa' ORDER BY id LIMIT 1",
            (tipo, chiave)).fetchone()
        if r is None:
            return None
        cur = conn.execute(
            "UPDATE lavori SET stato = 'in_corso',"
            " tentativi = tentativi + 1, avviato = ?, aggiornato = ?,"
            " heartbeat = ? WHERE id = ? AND stato = 'in_attesa'",
            (ora, ora, ora, int(r["id"])))
        if cur.rowcount != 1:
            return None
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (int(r["id"]),)).fetchone()
        return _riga(r)


def completa(lavoro_id: int | str, risultato: str = "") -> dict[str, Any] | None:
    """Chiude un lavoro in corso. Non tocca un lavoro annullato."""
    ident = _id_valido(lavoro_id)
    if ident is None:
        return None
    ora = time.time()
    with _tx() as conn:
        cur = conn.execute(
            "UPDATE lavori SET stato = 'completato', risultato = ?,"
            " errore = '', finito = ?, aggiornato = ?, heartbeat = 0"
            " WHERE id = ? AND stato = 'in_corso'",
            (_testo(risultato, max_len=8000), ora, ora, ident))
        if cur.rowcount != 1:
            return None
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        return _riga(r)


def fallisci(lavoro_id: int | str, errore: str = "", *,
             riprova: bool = False) -> dict[str, Any] | None:
    """Chiude con un errore, oppure rimette in attesa se i tentativi restano.

    Il default `riprova=False` e' voluto: per un turno dell'agente un
    retry automatico puo' ripetere effetti gia' avvenuti. Chi sa che il
    lavoro e' idempotente lo chiede esplicitamente.
    """
    ident = _id_valido(lavoro_id)
    if ident is None:
        return None
    ora = time.time()
    with _tx() as conn:
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        if r is None:
            return None
        if str(r["stato"]) != "in_corso":
            return _riga(r)
        tentativi = int(r["tentativi"] or 0)
        massimo = int(r["max_tentativi"] or 1)
        if riprova and tentativi < massimo:
            cur = conn.execute(
                "UPDATE lavori SET stato = 'in_attesa', errore = ?,"
                " aggiornato = ?, heartbeat = 0, avviato = 0, finito = 0"
                " WHERE id = ? AND stato = 'in_corso'",
                (_testo(errore, max_len=2000), ora, ident))
        else:
            cur = conn.execute(
                "UPDATE lavori SET stato = 'fallito', errore = ?,"
                " finito = ?, aggiornato = ?, heartbeat = 0"
                " WHERE id = ? AND stato = 'in_corso'",
                (_testo(errore, max_len=2000), ora, ora, ident))
        if cur.rowcount != 1:
            return None
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        return _riga(r)


def interrompi_in_corso(tipo: str | None = None,
                        motivo: str = "interrotto dal riavvio") -> int:
    """Segna come interrotti i lavori che un processo non ha finito.

    Si chiama all'avvio, prima di riprendere le code. Non li rimette in
    attesa: un turno a meta' puo' aver gia' prodotto effetti. Il pannello
    li mostra e l'utente decide se riprovare.
    """
    ora = time.time()
    with _tx() as conn:
        if tipo:
            cur = conn.execute(
                "UPDATE lavori SET stato = 'interrotto', errore = ?,"
                " finito = ?, aggiornato = ?, heartbeat = 0"
                " WHERE stato = 'in_corso' AND tipo = ?",
                (_testo(motivo, max_len=2000), ora, ora, _testo(tipo)))
        else:
            cur = conn.execute(
                "UPDATE lavori SET stato = 'interrotto', errore = ?,"
                " finito = ?, aggiornato = ?, heartbeat = 0"
                " WHERE stato = 'in_corso'",
                (_testo(motivo, max_len=2000), ora, ora))
        return int(cur.rowcount or 0)


def riprova(lavoro_id: int | str) -> dict[str, Any] | None:
    """Rimette in coda un lavoro fallito o interrotto.

    Il tetto dei tentativi viene alzato di uno, altrimenti il claim
    successivo ripartirebbe gia' oltre il massimo e il pulsante
    "Riprova" non riproverebbe niente. La storia dei tentativi resta.
    """
    ident = _id_valido(lavoro_id)
    if ident is None:
        return None
    ora = time.time()
    with _tx() as conn:
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        if r is None or str(r["stato"]) not in RIPROVABILI:
            return None
        conn.execute(
            "UPDATE lavori SET stato = 'in_attesa', errore = '',"
            " risultato = '', avviato = 0, finito = 0, heartbeat = 0,"
            " aggiornato = ?, max_tentativi = CASE"
            " WHEN max_tentativi <= tentativi THEN tentativi + 1"
            " ELSE max_tentativi END WHERE id = ?",
            (ora, ident))
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        return _riga(r)


def annulla(lavoro_id: int | str) -> dict[str, Any] | None:
    """Annulla un lavoro in attesa o in corso.

    Per uno in corso il consumatore vede lo stato al prossimo heartbeat
    e chiama `Session.cancel`. Il lavoro resta `annullato` anche se il
    turno si chiude dopo: l'annullamento e' la volonta' dell'utente.
    """
    ident = _id_valido(lavoro_id)
    if ident is None:
        return None
    ora = time.time()
    with _tx() as conn:
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        if r is None or str(r["stato"]) not in ATTIVI:
            return None
        cur = conn.execute(
            "UPDATE lavori SET stato = 'annullato',"
            " errore = 'annullato dall''utente', finito = ?,"
            " aggiornato = ?, heartbeat = 0"
            " WHERE id = ? AND stato IN ('in_attesa', 'in_corso')",
            (ora, ora, ident))
        if cur.rowcount != 1:
            return None
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        return _riga(r)


def batti(lavoro_id: int | str) -> bool:
    """Aggiorna il segno di vita di un lavoro in corso."""
    ident = _id_valido(lavoro_id)
    if ident is None:
        return False
    ora = time.time()
    with _tx() as conn:
        cur = conn.execute(
            "UPDATE lavori SET heartbeat = ?, aggiornato = ?"
            " WHERE id = ? AND stato = 'in_corso'",
            (ora, ora, ident))
        return bool(cur.rowcount)


def stato(lavoro_id: int | str) -> str:
    ident = _id_valido(lavoro_id)
    if ident is None:
        return ""
    conn = _conn()
    try:
        r = conn.execute("SELECT stato FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
    finally:
        conn.close()
    return str(r["stato"]) if r else ""


def salva_checkpoint(lavoro_id: int | str,
                     dati: dict[str, Any]) -> dict[str, Any] | None:
    """Salva un punto di ripresa per i lavori che sanno ripartire.

    I turni dei bot non lo usano: il loro confine e' il turno intero.
    Esiste per i consumatori futuri (goal a passi, job di import) che
    possono davvero ricominciare da un passo invece che da capo.
    """
    ident = _id_valido(lavoro_id)
    if ident is None or not isinstance(dati, dict):
        return None
    ora = time.time()
    with _tx() as conn:
        cur = conn.execute(
            "UPDATE lavori SET checkpoint = ?, aggiornato = ?,"
            " heartbeat = ? WHERE id = ? AND stato = 'in_corso'",
            (_json_scrive(dati), ora, ora, ident))
        if cur.rowcount != 1:
            return None
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        return _riga(r)


def elenca(*, tipo: str | None = None, chiave: str | None = None,
           stato_filtro: str | None = None,
           limite: int = 50) -> list[dict[str, Any]]:
    try:
        limite = max(1, min(500, int(limite)))
    except (TypeError, ValueError):
        limite = 50
    conn = _conn()
    try:
        return _elenca_con(conn, tipo=tipo, chiave=chiave,
                           stato_filtro=stato_filtro, limite=limite)
    finally:
        conn.close()


def _elenca_con(conn: sqlite3.Connection, *, tipo: str | None,
                chiave: str | None, stato_filtro: str | None,
                limite: int) -> list[dict[str, Any]]:
    where: list[str] = []
    parametri: list[Any] = []
    if tipo:
        where.append("tipo = ?")
        parametri.append(_testo(tipo))
    if chiave:
        where.append("chiave = ?")
        parametri.append(_testo(chiave))
    if stato_filtro:
        where.append("stato = ?")
        parametri.append(_testo(stato_filtro))
    sql = "SELECT * FROM lavori"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    parametri.append(limite)
    return [_riga(r) for r in conn.execute(sql, parametri).fetchall()]


def riassunto(tipo: str, chiave: str) -> dict[str, Any]:
    """Conteggi e ultime voci per una coda, in una sola apertura del DB.

    La UI del pannello Bot chiama questa funzione per ogni bot: deve
    costare poco e non deve poter far cadere l'elenco se un lavoro e'
    vecchio o il payload e' stato scritto da una versione precedente.
    """
    tipo = _testo(tipo)
    chiave = _testo(chiave)
    vuoto = {
        "tipo": tipo, "chiave": chiave, "conteggi": {},
        "in_attesa": 0, "in_corso": 0, "completati": 0, "falliti": 0,
        "interrotti": 0, "annullati": 0,
        "in_corso_id": 0, "in_corso_testo": "",
        "in_corso_worktree": None,
        "ultimo": None, "riprovabile": None, "recenti": [],
    }
    if not tipo or not chiave:
        return vuoto
    conn = _conn()
    try:
        conteggi = {str(r["stato"]): int(r["n"]) for r in conn.execute(
            "SELECT stato, COUNT(*) AS n FROM lavori"
            " WHERE tipo = ? AND chiave = ? GROUP BY stato",
            (tipo, chiave)).fetchall()}
        recenti = _elenca_con(conn, tipo=tipo, chiave=chiave,
                              stato_filtro=None, limite=20)
        # `ultimo` e `riprovabile` NON si cercano nei venti `recenti`: se
        # davanti a un lavoro interrotto ci sono venti compiti completati,
        # il pulsante "Riprova" sparirebbe proprio quando serve. Sono due
        # query in piu' su un indice, non una scansione.
        in_corso = _primo_stato(conn, tipo, chiave, ("in_corso",))
        ultimo = _primo_stato(conn, tipo, chiave, TERMINALI)
        riprovabile = _primo_stato(conn, tipo, chiave, RIPROVABILI)
    finally:
        conn.close()
    return {
        "tipo": tipo,
        "chiave": chiave,
        "conteggi": conteggi,
        "in_attesa": conteggi.get("in_attesa", 0),
        "in_corso": conteggi.get("in_corso", 0),
        "completati": conteggi.get("completato", 0),
        "falliti": conteggi.get("fallito", 0),
        "interrotti": conteggi.get("interrotto", 0),
        "annullati": conteggi.get("annullato", 0),
        "in_corso_id": int(in_corso["id"]) if in_corso else 0,
        "in_corso_testo": (str((in_corso or {}).get("payload", {})
                               .get("testo") or "")[:200]),
        "in_corso_worktree": (((in_corso or {}).get("checkpoint") or {})
                              .get("worktree") if in_corso else None),
        "ultimo": _voce(ultimo) if ultimo else None,
        "riprovabile": _voce(riprovabile) if riprovabile else None,
        "recenti": [_voce(j) for j in recenti],
    }


def _primo_stato(conn: sqlite3.Connection, tipo: str, chiave: str,
                 stati: tuple[str, ...]) -> dict[str, Any] | None:
    """Il lavoro piu' recente fra quelli negli stati indicati."""
    if not stati:
        return None
    segnaposti = ",".join("?" for _ in stati)
    r = conn.execute(
        f"SELECT * FROM lavori WHERE tipo = ? AND chiave = ?"
        f" AND stato IN ({segnaposti}) ORDER BY id DESC LIMIT 1",
        (tipo, chiave, *stati)).fetchone()
    return _riga(r) if r else None


def chiavi_con_attesa(tipo: str) -> list[str]:
    tipo = _testo(tipo)
    if not tipo:
        return []
    conn = _conn()
    try:
        righe = conn.execute(
            "SELECT DISTINCT chiave FROM lavori"
            " WHERE tipo = ? AND stato = 'in_attesa' ORDER BY chiave",
            (tipo,)).fetchall()
    finally:
        conn.close()
    return [str(r["chiave"]) for r in righe]


def ha_in_attesa(tipo: str, chiave: str) -> bool:
    conn = _conn()
    try:
        r = conn.execute(
            "SELECT 1 FROM lavori WHERE tipo = ? AND chiave = ?"
            " AND stato = 'in_attesa' LIMIT 1",
            (_testo(tipo), _testo(chiave))).fetchone()
    finally:
        conn.close()
    return r is not None


def worktree_di(tipo: str, chiave: str) -> list[dict[str, Any]]:
    """Tutti i checkout registrati in una coda, senza limite di storico.

    Serve a chi deve ripulire davvero (eliminare un bot): `elenca` ha un
    tetto pensato per il pannello, e usarlo qui lascerebbe indietro i
    checkout dei lavori piu' vecchi — che a quel punto nessuno potrebbe
    piu' scartare, perche' la riga del lavoro e' sparita.
    """
    tipo = _testo(tipo)
    chiave = _testo(chiave)
    if not tipo or not chiave:
        return []
    conn = _conn()
    try:
        righe = conn.execute(
            "SELECT checkpoint FROM lavori WHERE tipo = ? AND chiave = ?",
            (tipo, chiave)).fetchall()
    finally:
        conn.close()
    fuori: list[dict[str, Any]] = []
    for r in righe:
        checkpoint = _json_carica(r["checkpoint"], {})
        info = checkpoint.get("worktree") if isinstance(checkpoint, dict) else None
        if isinstance(info, dict):
            fuori.append(info)
    return fuori


def elimina_chiave(tipo: str, chiave: str) -> int:
    """Toglie lo storico di una coda (usato quando sparisce il bot)."""
    with _tx() as conn:
        cur = conn.execute("DELETE FROM lavori WHERE tipo = ? AND chiave = ?",
                           (_testo(tipo), _testo(chiave)))
        return int(cur.rowcount or 0)


def aggiorna_checkpoint(lavoro_id: int | str,
                        dati: dict[str, Any]) -> dict[str, Any] | None:
    """Aggiunge dati al checkpoint anche a lavoro chiuso.

    `salva_checkpoint` scrive solo mentre il lavoro e' in corso, perche'
    un consumatore non deve poter riscrivere il punto di ripresa di un
    lavoro finito. Questo serve al caso opposto: annotare che il
    checkout isolato e' stato scartato dopo la chiusura, senza perdere
    gli altri campi.
    """
    ident = _id_valido(lavoro_id)
    if ident is None or not isinstance(dati, dict):
        return None
    ora = time.time()
    with _tx() as conn:
        r = conn.execute("SELECT checkpoint FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        if r is None:
            return None
        checkpoint = _json_carica(r["checkpoint"], {})
        checkpoint.update(dati)
        conn.execute(
            "UPDATE lavori SET checkpoint = ?, aggiornato = ? WHERE id = ?",
            (_json_scrive(checkpoint), ora, ident))
        r = conn.execute("SELECT * FROM lavori WHERE id = ?",
                         (ident,)).fetchone()
        return _riga(r)


def _id_valido(lavoro_id: int | str) -> int | None:
    try:
        ident = int(lavoro_id)
    except (TypeError, ValueError):
        return None
    return ident if ident > 0 else None
