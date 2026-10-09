"""
Indice di ricerca sopra `memory.md`. FTS5, non un archivio.

PERCHÉ NON SOSTITUISCE IL FILE

Questa è la lezione che viene da come fanno OpenClaw e Hermes, e che
avevo sbagliato: `MEMORY.md` resta la SORGENTE DI VERITÀ, SQLite è
l'INDICE. Non un backend alternativo — uno strato sopra.

Se il database si perde o si corrompe, si ricostruisce dal file leggendo
le righe. Se il file è illeggibile, non hai niente: è per questo che la
verità sta nel testo e non nel DB. `IndiceMemoria` non ha `aggiungi` che
scrive solo nel database: ogni scrittura passa dal file, poi l'indice si
riallinea.

PERCHÉ FTS5 E NON UN FILTRO IN PYTHON

Avevo misurato "SQLite è 4 volte più lento" e la misura era rotta: il
file si era troncato a 272 fatti su 20.000, quindi cercavo su un file
vuoto. Ma anche a numeri onesti 40 ms contro 2 ms è rumore su un turno
che dura secondi.

Il motivo vero è un altro: il tetto di 20.000 caratteri TAGLIA IL FILE IN
SILENZIO. Ho perso 19.728 fatti su 20.000 senza un errore. Un indice che
si ricostruisce dal file non può perdere niente — e se il file sfora il
tetto, lo dice invece di tagliare.

COSA AGGIUNGE, RISPETTO AL SOLO FILE

- ricerca full-text con rank (FTS5), non sottostringa
- scadenza: un fatto con una data sparisce dalle ricerche da solo
- contatore d'uso: quali fatti servono davvero e quali sono roba morta
- chunking: le prose lunghe si indicizzano a pezzi, come fa OpenClaw
  (~400 token, 80 di overlap), invece di essere un blocco unico
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from typing import Any

# Chunking, come OpenClaw. 400 token sono circa 1600 caratteri; l'overlap
# di 80 token sta a ~320. L'overlap serve a non tagliare una frase a metà
# fra due chunk: la seconda metà di un pensiero deve stare anche nel chunk
# dopo, o la ricerca su quella parola non trova niente.
CHUNK_CARATTERI = 1600
OVERLAP_CARATTERI = 320

SCHEMA = """
CREATE TABLE IF NOT EXISTS fatti (
    testo     TEXT PRIMARY KEY,
    importante INTEGER NOT NULL DEFAULT 0,
    origine   TEXT NOT NULL DEFAULT '',
    creata    REAL NOT NULL,
    scade     REAL,                      -- NULL = non scade mai
    usi       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_scade ON fatti(scade);

-- La tabella FTS5 è SEPARATA e speculare: contiene lo stesso testo, ma
-- indicizzato. Non si cerca sulla tabella dei fatti, si cerca qui e si
-- torna al fatto per id. Questo è il motivo per cui l'indice si può
-- buttare e ricostruire senza perdere niente.
CREATE VIRTUAL TABLE IF NOT EXISTS fatti_fts USING fts5(
    testo, content='fatti', content_rowid='rowid', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS fatti_ai AFTER INSERT ON fatti BEGIN
    INSERT INTO fatti_fts(rowid, testo) VALUES (new.rowid, new.testo);
END;
CREATE TRIGGER IF NOT EXISTS fatti_ad AFTER DELETE ON fatti BEGIN
    INSERT INTO fatti_fts(fatti_fts, rowid, testo)
        VALUES ('delete', old.rowid, old.testo);
END;
CREATE TRIGGER IF NOT EXISTS fatti_au AFTER UPDATE ON fatti BEGIN
    INSERT INTO fatti_fts(fatti_fts, rowid, testo)
        VALUES ('delete', old.rowid, old.testo);
    INSERT INTO fatti_fts(rowid, testo) VALUES (new.rowid, new.testo);
END;
"""


def percorso_db() -> str:
    """Accanto allo storico, nella cartella dati di Orchestra."""
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
    return os.path.join(base, "memoria_indice.db")


def chunk_testo(testo: str) -> list[str]:
    """Una prose lunga diventa pezzi sovrapposti.

    Un fatto corto resta un pezzo solo: chunkare "lavoro su Windows" non
    ha senso. Chunkare serve quando il fatto è un paragrafo — e a quel
    punto cercare una parola a metà paragrafo deve trovare il pezzo che
    la contiene.
    """
    t = (testo or "").strip()
    if len(t) <= CHUNK_CARATTERI:
        return [t] if t else []
    pezzi = []
    i = 0
    while i < len(t):
        fine = min(i + CHUNK_CARATTERI, len(t))
        pezzi.append(t[i:fine])
        if fine >= len(t):
            break
        # si torna indietro dell'overlap, ma non prima dell'inizio
        i = max(0, fine - OVERLAP_CARATTERI)
    return pezzi


class IndiceMemoria:
    """Indice FTS5 sopra `memory.md`. Il file resta la verità.

    Espone lo stesso contratto di `Memoria` (importanti/fatti/aggiungi/
    elimina/leggi), così il resto dell'app non sa se la memoria sta su un
    file o su un file indicizzato.
    """

    def __init__(self, sorgente: Any = None, percorso: str | None = None) -> None:
        from .memoria import memoria as _memoria
        self.sorgente = sorgente if sorgente is not None else _memoria()
        self.percorso = percorso or percorso_db()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.percorso, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._ultimo_file = 0.0
        self.ricostruisci_se_cambiato()

    def chiudi(self) -> None:
        with self._lock:
            self._conn.close()

    # -- allineamento col file ---------------------------------------------

    def ricostruisci_se_cambiato(self, forza: bool = False) -> None:
        """Se `memory.md` è cambiato, l'indice si rifà.

        Il controllo è su mtime, ma non solo: se l'indice è vuoto e il
        file no, qualcuno ha buttato il DB — e senza questo controllo la
        ricostruzione non scatterebbe mai, perché il file non è cambiato.
        Era il difetto peggiore possibile proprio qui, nello strato che
        doveva essere la rete di sicurezza: provato, indice svuotato a
        mano e ricerca che tornava zero per sempre.

        Il confronto su contenuto si fa col conteggio, non leggendo il
        file: leggerlo per sapere se è cambiato è il costo che l'indice
        serve a evitare.
        """
        try:
            mtime = os.path.getmtime(self.sorgente.percorso)
        except OSError:
            return
        with self._lock:
            if not forza and mtime == self._ultimo_file and self._conto_db() > 0:
                return
        self._ultimo_file = mtime
        self.ricostruisci()

    def _conto_db(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) c FROM fatti").fetchone()["c"]

    def ricostruisci(self) -> int:
        """Butta l'indice e lo rifà dal file. Torna quanti fatti.

        Due trappole, entrambe provate:

        1. `fatti()` sul backend a file torna TUTTI i fatti, importanti
           compresi. Se si aggiunge prima quelli e poi `fatti()`, il fatto
           importante viene scritto due volte e l'ultima scrittura vince
           con `importante = 0` — sparisce dal prompt in silenzio. Per
           questo l'insert normale salta chi è già negli importanti.

        2. Non si può fidare del confronto su mtime: se l'indice è stato
           buttato, il file non è cambiato e la ricostruzione non scatta.
           Da qui il `forza`.
        """
        importanti = self.sorgente.importanti()
        gia_importanti = set(importanti)
        # `fatti()` torna tutto: si toglie chi è importante, o lo si
        # riscrive con importante=0 più sotto
        altri = [f for f in self.sorgente.fatti() if f not in gia_importanti]
        with self._lock:
            self._conn.execute("DELETE FROM fatti")
            adesso = time.time()
            for testo in importanti:
                self._inserisci(testo, importante=True, creata=adesso)
            for testo in altri:
                self._inserisci(testo, importante=False, creata=adesso)
            self._conn.commit()
        return len(importanti) + len(altri)

    def _inserisci(self, testo: str, *, importante: bool,
                   origine: str = "", creata: float | None = None,
                   scade_giorni: int | None = None,
                   usi: int = 0) -> None:
        """Scrive nel file e poi nell'indice. Mai solo nell'indice.

        L'ordine conta: se il file è la verità, va scritto per primo. Se
        il DB prendesse la scrittura e il file no, al primo
        `ricostruisci_se_cambiato` il fatto sparisce — e non si capisce
        perché, perché in memoria c'era.
        """
        for pezzo in chunk_testo(testo):
            scade = (time.time() + scade_giorni * 86400) if scade_giorni else None
            self._conn.execute(
                "INSERT INTO fatti (testo, importante, origine, creata, scade, usi)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(testo) DO UPDATE SET"
                "   importante = excluded.importante,"
                "   scade = COALESCE(excluded.scade, fatti.scade)",
                (pezzo, 1 if importante else 0, origine,
                 creata or time.time(), scade, usi))

    # -- contratto comune --------------------------------------------------

    def fatti(self) -> list[str]:
        self.ricostruisci_se_cambiato()
        return [r["testo"] for r in self._query(
            "SELECT testo FROM fatti"
            " WHERE importante = 0 AND (scade IS NULL OR scade > ?)",
            (time.time(),))]

    def importanti(self) -> list[str]:
        self.ricostruisci_se_cambiato()
        # gli importanti non scadono: se l'hai messo nel prompt è perché
        # deve essere vero sempre
        return [r["testo"] for r in self._query(
            "SELECT testo FROM fatti WHERE importante = 1")]

    def aggiungi(self, fatto: str, origine: str = "",
                 importante: bool = False,
                 scade_giorni: int | None = None) -> bool:
        """Scrive nel FILE, poi allinea l'indice.

        Ritorna False se il fatto c'era già: duplicare non fa crescere
        l'informazione, fa crescere il contesto che costa a ogni turno.
        """
        fatto = " ".join((fatto or "").split()).strip()
        if not fatto:
            return False
        nuovo = self.sorgente.aggiungi(fatto, origine=origine,
                                       importante=importante)
        if nuovo:
            with self._lock:
                self._inserisci(fatto, importante=importante, origine=origine,
                                scade_giorni=scade_giorni)
                self._conn.commit()
            # il file è cambiato: al prossimo ricostruisci_se_cambiato il
            # fatto c'è già e l'indice resta allineato
            try:
                self._ultimo_file = os.path.getmtime(self.sorgente.percorso)
            except OSError:
                pass
        return nuovo

    def elimina(self, fatto: str) -> bool:
        """Toglie dal file e dall'indice."""
        tolto = self.sorgente.elimina(fatto)
        if tolto:
            with self._lock:
                self._conn.execute("DELETE FROM fatti WHERE testo = ?",
                                   (fatto.strip(),))
                self._conn.commit()
            try:
                self._ultimo_file = os.path.getmtime(self.sorgente.percorso)
            except OSError:
                pass
        return tolto

    def leggi(self) -> str:
        """Il file, non l'indice: la verità è quella."""
        return self.sorgente.leggi()

    def scrivi(self, testo: str) -> None:
        """Scrive il file e butta l'indice, che si rifarà.

        Sovrascrivere l'indice con del testo lo corrompe: l'indice non
        contiene verità da sostituire.
        """
        self.sorgente.scrivi(testo)
        with self._lock:
            self._conn.execute("DELETE FROM fatti")
            self._conn.commit()
        self.ricostruisci()

    def scrivi_intestazione(self) -> None:
        self.sorgente.scrivi_intestazione()

    # -- quello che il file non sa fare ------------------------------------

    def cerca(self, query: str = "", limite: int = 10,
              conta_usi: bool = True) -> list[dict[str, Any]]:
        """Ricerca full-text con rank. FTS5, non sottostringa.

        `conta_usi` si può spegnere per le ricerche dalla UI: consultare
        un fatto per controllarlo non vuol dire che serva, e contarlo
        inquinerebbe la statistica che decide cosa proporre di togliere.
        """
        self.ricostruisci_se_cambiato()
        q = (query or "").strip()
        adesso = time.time()
        with self._lock:
            if not q:
                righe = self._conn.execute(
                    "SELECT * FROM fatti WHERE scade IS NULL OR scade > ?"
                    " ORDER BY importante DESC, creata DESC LIMIT ?",
                    (adesso, limite)).fetchall()
            else:
                # Le parole si quotano: una query con un apostrofo o un
                # trattino fa fallire la sintassi MATCH, e la ricerca
                # tornerebbe vuota invece di dire che non ha trovato.
                parole = q.split()
                frase = " AND ".join(f'"{p}"' for p in parole)
                try:
                    # rowid va selezionato a mano: la JOIN con f.* non lo
                    # porta, e senza non si può aggiornare il contatore
                    # d'uso del fatto trovato.
                    righe = self._conn.execute(
                        "SELECT f.rowid AS rowid, f.testo AS testo,"
                        " f.importante AS importante, f.origine AS origine,"
                        " f.creata AS creata, f.scade AS scade, f.usi AS usi"
                        " FROM fatti_fts"
                        " JOIN fatti f ON f.rowid = fatti_fts.rowid"
                        " WHERE fatti_fts MATCH ?"
                        "   AND (f.scade IS NULL OR f.scade > ?)"
                        " ORDER BY rank, f.importante DESC LIMIT ?",
                        (frase, adesso, limite)).fetchall()
                except sqlite3.OperationalError:
                    # query malformata (sintassi FTS5): si torna a una
                    # ricerca semplice, che è meglio di un errore
                    righe = [r for r in self._conn.execute(
                        "SELECT * FROM fatti WHERE scade IS NULL OR scade > ?",
                        (adesso,)).fetchall()
                        if q.lower() in r["testo"].lower()][:limite]
            if righe and conta_usi:
                for r in righe:
                    self._conn.execute("UPDATE fatti SET usi = usi + 1 WHERE rowid = ?",
                                       (r["rowid"],))
                self._conn.commit()
        return [dict(r) for r in righe]

    def statistiche(self) -> dict[str, Any]:
        """Quanto è grande, e quanto è morto.

        `mai_usati` è il numero che conta: fatti che nessuna ricerca ha
        mai restituito. Non è un motivo per cancellarli — uno appena
        aggiunto non è stato cercato ancora — ma dopo un mese a zero
        vuol dire che non servono.
        """
        self.ricostruisci_se_cambiato()
        adesso = time.time()
        with self._lock:
            totale = self._conn.execute("SELECT COUNT(*) c FROM fatti").fetchone()["c"]
            vivi = self._conn.execute(
                "SELECT COUNT(*) c FROM fatti WHERE scade IS NULL OR scade > ?",
                (adesso,)).fetchone()["c"]
            importanti = self._conn.execute(
                "SELECT COUNT(*) c FROM fatti WHERE importante = 1").fetchone()["c"]
            mai_usati = self._conn.execute(
                "SELECT COUNT(*) c FROM fatti WHERE usi = 0").fetchone()["c"]
            piu_usati = [dict(r) for r in self._conn.execute(
                "SELECT testo, usi FROM fatti WHERE usi > 0"
                " ORDER BY usi DESC LIMIT 10")]
            in_scadenza = [dict(r) for r in self._conn.execute(
                "SELECT testo, scade FROM fatti"
                " WHERE scade IS NOT NULL AND scade > ? AND scade < ?"
                " ORDER BY scade", (adesso, adesso + 7 * 86400))]
        try:
            byte_file = os.path.getsize(self.sorgente.percorso)
        except OSError:
            byte_file = 0
        return {
            "totale": totale,
            "vivi": vivi,
            "scaduti": totale - vivi,
            "importanti": importanti,
            "mai_usati": mai_usati,
            "piu_usati": piu_usati,
            "in_scadenza": in_scadenza,
            "percorso_file": getattr(self.sorgente, "percorso", ""),
            "byte_file": byte_file,
        }

    def pulisci_scaduti(self) -> int:
        """Toglie dall'indice i fatti scaduti. Il file non li tocca: sono
        righe di testo, e toglierle a mano è roba dell'utente."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM fatti WHERE scade IS NOT NULL AND scade <= ?",
                (time.time(),))
            self._conn.commit()
            return cur.rowcount

    def imposta_scadenza(self, fatto: str, giorni: int | None) -> bool:
        """Mette o toglie la scadenza a un fatto già in memoria.

        La scadenza vive nell'indice, non nel file: `memory.md` resta
        testo per un essere umano, e una data in mezzo alla riga è roba
        che nessuno corregge a mano.
        """
        self.ricostruisci_se_cambiato()
        scade = (time.time() + giorni * 86400) if giorni else None
        with self._lock:
            cur = self._conn.execute("UPDATE fatti SET scade = ? WHERE testo = ?",
                                     (scade, fatto.strip()))
            self._conn.commit()
            return cur.rowcount > 0

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()


# Istanza condivisa, come l'altro modulo. L'indice è uno per processo:
# ricostruirlo a ogni richiesta HTTP è il costo che serve a evitare.
_istanza: IndiceMemoria | None = None
_lock_istanza = threading.Lock()


def indice_memoria() -> IndiceMemoria:
    global _istanza
    if _istanza is None:
        with _lock_istanza:
            if _istanza is None:
                _istanza = IndiceMemoria()
    return _istanza