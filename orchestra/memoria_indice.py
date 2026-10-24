"""
Indice di ricerca sopra `memory.md`. FTS5, non un archivio.

PERCHÉ NON SOSTITUISCE IL FILE

Questa è la lezione su suggerita da un benchmark locale e che
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
from .dati import percorso
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
    usi       INTEGER NOT NULL DEFAULT 0,
    progetto  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_scade ON fatti(scade);

-- L'indice per progetto. Serve a chiedere "cosa serve per QUESTO
-- progetto" senza scaricare tutto: e' la differenza fra un archivio
-- che risponde e uno che ammette di essere stato sfitto.
CREATE INDEX IF NOT EXISTS idx_fatti_progetto ON fatti(progetto);

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
    return percorso("memoria_indice.db")


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
            # La tabella puo' esistere da una versione vecchia senza la
            # colonna `progetto`: la si crea/migra PRIMA di eseguire lo
            # schema completo, altrimenti CREATE INDEX su fatti(progetto)
            # fallisce e l'indice non si apre.
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS fatti ("
                "testo TEXT PRIMARY KEY, importante INTEGER NOT NULL DEFAULT 0, "
                "origine TEXT NOT NULL DEFAULT '', creata REAL NOT NULL, "
                "scade REAL, usi INTEGER NOT NULL DEFAULT 0)")
            self._conn.commit()
            self._migra_progetto()
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._ultimo_file = 0.0
        self.ricostruisci_se_cambiato()

    def _migra_progetto(self) -> None:
        """Aggiunge la colonna `progetto` a un indice nato prima di lei.

        `CREATE TABLE IF NOT EXISTS` non aggiunge colonne a una tabella
        che esiste gia': su un DB creato prima, la colonna manca e ogni
        query che la nomina fallisce. Il sintomo sarebbe una ricerca
        che restituisce zero su un archivio pieno — cioe' la memoria
        che sembra svuota.

        Percio' si guarda se la colonna c'e' e, se non c'e', si
        aggiunge. Idempotente: la seconda volta non fa niente.
        """
        try:
            righe = self._conn.execute("PRAGMA table_info(fatti)").fetchall()
            colonne = {r["name"] for r in righe}
            if "progetto" not in colonne:
                self._conn.execute(
                    "ALTER TABLE fatti ADD COLUMN progetto TEXT NOT NULL DEFAULT ''")
        except Exception:  # noqa: BLE001
            pass

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

        Il progetto si legge dal file, non da un campo dell'indice: il
        file e' la verita'. Per farlo serve la riga intera, non il
        testo pulito — quindi qui si rilegge il file riga per riga, che
        e' quello che `ricostruisci` fa gia' in ogni caso.
        """
        from .memoria import _pulizia_riga

        importanti = self.sorgente.importanti()
        gia_importanti = set(importanti)
        # `fatti()` torna tutto: si toglie chi è importante, o lo si
        # riscrive con importante=0 più sotto
        altri = [f for f in self.sorgente.fatti() if f not in gia_importanti]

        # Il progetto di ogni fatto, letto dalla riga grezza.
        progetti: dict[str, str] = {}
        try:
            for riga in self.sorgente.leggi().splitlines():
                r = riga.strip()
                if not r.startswith("-"):
                    continue
                corpo = r.lstrip("-").strip()
                testo_pulito, _fonte, prog = _pulizia_riga(corpo)
                if testo_pulito and prog:
                    progetti[testo_pulito] = prog
        except Exception:  # noqa: BLE001
            pass

        with self._lock:
            self._conn.execute("DELETE FROM fatti")
            adesso = time.time()
            for testo in importanti:
                self._inserisci(testo, importante=True, creata=adesso,
                                progetto=progetti.get(testo, ""))
            for testo in altri:
                self._inserisci(testo, importante=False, creata=adesso,
                                progetto=progetti.get(testo, ""))
            self._conn.commit()
        return len(importanti) + len(altri)

    def _inserisci(self, testo: str, *, importante: bool,
                   origine: str = "", creata: float | None = None,
                   scade_giorni: int | None = None,
                   usi: int = 0, progetto: str = "") -> None:
        """Scrive nel file e poi nell'indice. Mai solo nell'indice.

        L'ordine conta: se il file è la verità, va scritto per primo. Se
        il DB prendesse la scrittura e il file no, al primo
        `ricostruisci_se_cambiato` il fatto sparisce — e non si capisce
        perché, perché in memoria c'era.
        """
        for pezzo in chunk_testo(testo):
            scade = (time.time() + scade_giorni * 86400) if scade_giorni else None
            self._conn.execute(
                "INSERT INTO fatti (testo, importante, origine, creata, scade, usi,"
                " progetto) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(testo) DO UPDATE SET"
                "   importante = excluded.importante,"
                "   scade = COALESCE(excluded.scade, fatti.scade),"
                "   progetto = CASE WHEN excluded.progetto <> ''"
                "                   THEN excluded.progetto ELSE fatti.progetto END",
                (pezzo, 1 if importante else 0, origine,
                 creata or time.time(), scade, usi, progetto))

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
                 scade_giorni: int | None = None,
                 progetto: str = "") -> bool:
        """Scrive nel FILE, poi allinea l'indice.

        Ritorna False se il fatto c'era già: duplicare non fa crescere
        l'informazione, fa crescere il contesto che costa a ogni turno.
        """
        fatto = " ".join((fatto or "").split()).strip()
        if not fatto:
            return False
        nuovo = self.sorgente.aggiungi(fatto, origine=origine,
                                       importante=importante,
                                       progetto=progetto)
        if nuovo:
            with self._lock:
                self._inserisci(fatto, importante=importante, origine=origine,
                                scade_giorni=scade_giorni, progetto=progetto)
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

    def modifica(self, vecchio: str, nuovo: str) -> bool:
        """Riscrive un fatto nel file e aggiorna l'indice.

        Il file resta la verità: si delega a `Memoria.modifica`, poi si
        cancella la riga vecchia dall'indice e si indicizza quella nuova.
        """
        cambiato = self.sorgente.modifica(vecchio, nuovo)
        if cambiato:
            with self._lock:
                self._conn.execute("DELETE FROM fatti WHERE testo = ?",
                                   (vecchio.strip(),))
                self._conn.commit()
            self.ricostruisci_se_cambiato(forza=True)
            try:
                self._ultimo_file = os.path.getmtime(self.sorgente.percorso)
            except OSError:
                pass
        return cambiato

    def fatti_per_progetto(self, progetto: str) -> list[str]:
        """I fatti di un progetto.

        Si chiede al FILE, non all'indice: la verita' dei fatti e' la
        riga di testo, e la colonna `progetto` nell'indice e' uno
        specchio che va tenuto allineato a mano.

        Il file e' anche la risposta completa: `IndiceMemoria.fatti()`
        restituisce solo i fatti NON importanti, mentre sul file ci sono
        anche quelli. Un filtro per progetto che perdesse gli
        importanti darebbe un archivio che nasconde proprio i fatti
        che il modello vede nel prompt — e il dubbio che ne nasce
        ("l'ho perso?") costa piu' del fatto stesso.
        """
        metodo = getattr(self.sorgente, "fatti_per_progetto", None)
        if callable(metodo):
            try:
                return metodo(progetto)
            except Exception:  # noqa: BLE001
                pass
        # Backend senza il metodo: si filtra qui, sull'indice.
        if not progetto:
            return self.fatti() + self.importanti()
        fuori = []
        for r in self._query(
                "SELECT testo FROM fatti WHERE LOWER(progetto) = LOWER(?)",
                (progetto,)):
            testo = r["testo"]
            if testo and testo not in fuori:
                fuori.append(testo)
        return fuori

    def progetti(self) -> list[str]:
        """I progetti di cui la memoria ha qualcosa."""
        metodo = getattr(self.sorgente, "progetti", None)
        if callable(metodo):
            try:
                return metodo()
            except Exception:  # noqa: BLE001
                pass
        return []

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
              conta_usi: bool = True,
              progetto: str = "") -> list[dict[str, Any]]:
        """Ricerca full-text con rank. FTS5, non sottostringa.

        `conta_usi` si può spegnere per le ricerche dalla UI: consultare
        un fatto per controllarlo non vuol dire che serva, e contarlo
        inquinerebbe la statistica che decide cosa proporre di togliere.

        `progetto` filtra per progetto. Vuoto = tutti i progetti, che
        e' il default: la memoria e' condivisa, e chiedere "tutto" e'
        una domanda legittima.

        Il filtro va nella WHERE e non dopo: filtrare in Python
        significherebbe prendere i primi N e poi scartarne metà,
        restituendo meno di quanto chiesto — e sembrerebbe che la
        memoria non abbia niente.
        """
        self.ricostruisci_se_cambiato()
        q = (query or "").strip()
        progetto = (progetto or "").strip()
        adesso = time.time()
        with self._lock:
            if not q:
                if progetto:
                    righe = self._conn.execute(
                        "SELECT * FROM fatti WHERE (scade IS NULL OR scade > ?)"
                        "   AND LOWER(progetto) = LOWER(?)"
                        " ORDER BY importante DESC, creata DESC LIMIT ?",
                        (adesso, progetto, limite)).fetchall()
                else:
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
                # La colonna `progetto` va selezionata a mano: senza,
                # il risultato non dice da quale progetto viene.
                campi = ("f.rowid AS rowid, f.testo AS testo,"
                         " f.importante AS importante, f.origine AS origine,"
                         " f.creata AS creata, f.scade AS scade, f.usi AS usi,"
                         " f.progetto AS progetto")
                filtri = "fatti_fts MATCH ? AND (f.scade IS NULL OR f.scade > ?)"
                argomenti: list[Any] = [frase, adesso]
                if progetto:
                    # LOWER da entrambe le parti: il confronto di SQLite
                    # sulle stringhe e' case-sensitive, e il filtro sul
                    # file (`fatti_per_progetto`) e' case-insensitive.
                    # Senza questo, lo stesso progetto written in due
                    # modi diversi ("Sito" e "sito") dava due risultati
                    # diversi — e il sintomo sarebbe "il progetto non
                    # e' stato trovato" quando invece c'era.
                    filtri += " AND LOWER(f.progetto) = LOWER(?)"
                    argomenti.append(progetto)
                argomenti.append(limite)
                try:
                    # rowid va selezionato a mano: la JOIN con f.* non lo
                    # porta, e senza non si può aggiornare il contatore
                    # d'uso del fatto trovato.
                    righe = self._conn.execute(
                        f"SELECT {campi} FROM fatti_fts"
                        " JOIN fatti f ON f.rowid = fatti_fts.rowid"
                        f" WHERE {filtri}"
                        " ORDER BY rank, f.importante DESC LIMIT ?",
                        tuple(argomenti)).fetchall()
                except sqlite3.OperationalError:
                    # query malformata (sintassi FTS5): si torna a una
                    # ricerca semplice, che è meglio di un errore
                    if progetto:
                        righe = [r for r in self._conn.execute(
                            "SELECT * FROM fatti WHERE (scade IS NULL OR scade > ?)"
                            "   AND LOWER(progetto) = LOWER(?)",
                            (adesso, progetto)).fetchall()
                            if q.lower() in r["testo"].lower()][:limite]
                    else:
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

    def ottimizza_memoria(self, provider=None, dry_run: bool = True,
                          giorni_grazia: int = 30, progetto: str = "",
                          unisci: bool = False,
                          soglia_similarita: float = 0.5) -> dict[str, Any]:
        """Potatura (e, se richiesto, unione) della memoria.

        Fase 1, a basso rischio: i fatti NON importanti che non sono mai
        stati usati (`usi = 0`) e sono più vecchi di `giorni_grazia` giorni
        vengono rimossi. Gli `importanti` non si toccano mai: sono fatti
        che qualcuno ha esplicitamente marcato come sempre veri.

        Si rimuovono anche i duplicati case-insensitive: `aggiungi` li
        blocca già, ma un fatto scritto a mano o arrivato da un backend
        diverso può sfuggire.

        Con `unisci=True` e un `provider`, i fatti simili vengono fusi in
        uno solo da un modello. È la fase 2: va tenuta spenta di default,
        perché un modello che fonde due fatti può perdere un dettaglio.

        `dry_run=True` (default) non tocca niente: restituisce solo la
        lista di ciò che verrebbe fatto. È il modo in cui si usa prima di
        fidarsi.

        Ritorna un dizionario con i dettagli, per la UI e per i test.
        """
        from .memoria import _pulizia_riga

        self.ricostruisci_se_cambiato(forza=True)
        adesso = time.time()
        progetto = (progetto or "").strip()
        grace = max(0, int(giorni_grazia or 0))

        # -- candidati alla potatura --------------------------------------
        with self._lock:
            righe = self._conn.execute(
                "SELECT testo, usi, creata, progetto, importante, scade "
                "FROM fatti").fetchall()
        righe = [dict(r) for r in righe]

        da_rimuovere: list[str] = []
        motivi: dict[str, str] = {}
        dettagli: list[dict[str, Any]] = []

        for r in righe:
            if r["importante"]:
                continue
            if progetto and (r.get("progetto") or "").lower() != progetto.lower():
                continue
            if r.get("scade") is not None and r["scade"] <= adesso:
                # già scaduto: lo pulisce `pulisci_scaduti`, non è lavoro
                # dell'ottimizzatore
                continue
            eta = (adesso - float(r["creata"])) / 86400.0
            if r["usi"] == 0 and eta >= grace:
                t = r["testo"]
                if t not in da_rimuovere:
                    da_rimuovere.append(t)
                    motivi[t] = "mai usato"
                    dettagli.append({
                        "testo": t, "motivo": "mai usato",
                        "usi": r["usi"], "eta_giorni": round(eta, 1),
                        "progetto": r.get("progetto", ""),
                    })

        # -- duplicati case-insensitive ------------------------------------
        visti_lower: dict[str, str] = {}
        for r in righe:
            if r["importante"]:
                continue
            if progetto and (r.get("progetto") or "").lower() != progetto.lower():
                continue
            t = r["testo"]
            key = " ".join(t.lower().split())
            if key in visti_lower and visti_lower[key] != t:
                if t not in da_rimuovere:
                    da_rimuovere.append(t)
                    motivi[t] = "duplicato"
                    dettagli.append({
                        "testo": t, "motivo": "duplicato",
                        "usi": r["usi"],
                        "eta_giorni": round((adesso - float(r["creata"])) / 86400.0, 1),
                        "progetto": r.get("progetto", ""),
                    })
            else:
                visti_lower[key] = t

        # -- unione di fatti simili (fase 2, opt-in) -----------------------
        proposte_unione: list[dict[str, Any]] = []
        uniti = 0
        if unisci and provider is not None:
            # solo i fatti non importanti del progetto (o tutti)
            candidati_unione = [
                r for r in righe
                if not r["importante"]
                and (not progetto or (r.get("progetto") or "").lower() == progetto.lower())
            ]
            gruppi = self._gruppi_simili(candidati_unione, soglia_similarita)
            for gruppo in gruppi:
                testi = [g["testo"] for g in gruppo]
                if len(testi) < 2:
                    continue
                fuso = self._chiedi_unione(provider, testi)
                if not fuso or fuso == testi:
                    continue
                proposte_unione.append({"originali": testi, "unito": fuso})
                if not dry_run:
                    # rimuove gli originali e aggiunge il fuso
                    for t in testi:
                        if t not in da_rimuovere:
                            da_rimuovere.append(t)
                            motivi[t] = "fuso"
                    # il fuso si aggiunge dopo la rimozione
                    progetti = {g.get("progetto", "") for g in gruppo}
                    proj = progetti.pop() if len(progetti) == 1 else ""
                    try:
                        self.sorgente.aggiungi(
                            " ".join(fuso) if isinstance(fuso, list) else str(fuso),
                            origine="ottimizzatore", progetto=proj)
                        uniti += 1
                    except Exception:
                        pass

        fatti_prima = len(righe)

        if dry_run:
            return {
                "dry_run": True,
                "applicato": False,
                "fatti_prima": fatti_prima,
                "fatti_dopo": fatti_prima,
                "candidati": dettagli,
                "da_rimuovere": list(da_rimuovere),
                "rimossi": 0,
                "cancellati": 0,
                "potati": 0,
                "uniti": 0,
                "fusi": 0,
                "proposte_unione": proposte_unione,
                "motivi": motivi,
            }

        # -- applicazione ---------------------------------------------------
        if da_rimuovere:
            testi_set = set(da_rimuovere)
            try:
                contenuto = self.sorgente.leggi()
                fuori = []
                for linea in contenuto.splitlines(keepends=True):
                    r = linea.strip()
                    if r.startswith("-"):
                        corpo = r.lstrip("-").strip()
                        pulito = _pulizia_riga(corpo)[0]
                        if pulito in testi_set:
                            continue
                    fuori.append(linea)
                self.sorgente.scrivi("".join(fuori))
            except Exception:
                pass
            self.ricostruisci()
            try:
                self._ultimo_file = __import__("os").path.getmtime(self.sorgente.percorso)
            except Exception:
                pass
            # pulizia dell'indice per i scaduti, per coerenza
            try:
                self.pulisci_scaduti()
            except Exception:
                pass

        fatti_dopo = self._conto_db()
        rimossi = len(da_rimuovere)
        return {
            "dry_run": False,
            "applicato": True,
            "fatti_prima": fatti_prima,
            "fatti_dopo": fatti_dopo,
            "candidati": dettagli,
            "da_rimuovere": list(da_rimuovere),
            "rimossi": rimossi,
            "cancellati": rimossi,
            "potati": rimossi,
            "uniti": uniti,
            "fusi": uniti,
            "proposte_unione": proposte_unione,
            "motivi": motivi,
        }

    def _gruppi_simili(self, righe: list[dict[str, Any]],
                       soglia: float) -> list[list[dict[str, Any]]]:
        """Raggruppa fatti per similarita' lessicale (Jaccard su parole).

        Non usa embedding: nessuna dipendenza nuova, e su fatti brevi le
        parole condivise bastano. I gruppi sono componenti connesse, non
        coppie: se A e' simile a B e B a C, finiscono insieme.
        """
        def parole(t: str) -> set[str]:
            return {w for w in (t or "").lower().split()
                    if len(w) > 3}

        n = len(righe)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(n):
            for j in range(i + 1, n):
                wi, wj = parole(righe[i]["testo"]), parole(righe[j]["testo"])
                if not wi or not wj:
                    continue
                inter = len(wi & wj)
                uni = len(wi | wj)
                if uni and inter / uni >= soglia and inter >= 2:
                    union(i, j)

        gruppi_map: dict[int, list[dict[str, Any]]] = {}
        for i, r in enumerate(righe):
            gruppi_map.setdefault(find(i), []).append(r)
        return [g for g in gruppi_map.values() if len(g) >= 2]

    def _chiedi_unione(self, provider: Any, testi: list[str]) -> list[str] | None:
        """Chiede al modello di fondere i fatti. Torna la lista fusa o None."""
        from .types import Message
        prompt = (
            "Unisci questi fatti in meno fatti possibili, senza perdere "
            "informazioni. Una riga per fatto, senza numeri, senza "
            "trattini, senza commenti. Se non si possono unire, ripeti "
            "gli originali uno per riga.\\n\\nFatti:\\n"
            + "\\n".join(f"- {t}" for t in testi)
        )
        try:
            resp = provider.chat([Message(role="user", content=prompt)],
                                 tools=None)
            testo = (getattr(resp, "content", "") or "").strip()
        except Exception:
            return None
        if not testo:
            return None
        fusi = []
        for riga in testo.splitlines():
            r = riga.strip()
            r = __import__("re").sub(r"^[\\-\\*\\d\\.\\)\\s]+", "", r)
            if r and len(r) > 8:
                fusi.append(r)
        # se il modello non ha ridotto nulla, non c'e' unione
        if len(fusi) >= len(testi):
            return None
        return fusi

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


def ottimizza_memoria(provider=None, dry_run: bool = True, giorni_grazia: int = 30,
                      progetto: str = "", unisci: bool = False,
                      soglia_similarita: float = 0.5, **kw) -> dict[str, Any]:
    """Potatura della memoria. Vedi `IndiceMemoria.ottimizza_memoria`."""
    # compatibilita' con chiamate in stile ottimizza_memoria(dry_run=...)
    if "dry_run" in kw:
        dry_run = kw.pop("dry_run")
    if "giorni_grazia" in kw:
        giorni_grazia = kw.pop("giorni_grazia")
    if "progetto" in kw:
        progetto = kw.pop("progetto")
    if "unisci" in kw:
        unisci = kw.pop("unisci")
    try:
        return indice_memoria().ottimizza_memoria(
            provider=provider, dry_run=dry_run, giorni_grazia=giorni_grazia,
            progetto=progetto, unisci=unisci,
            soglia_similarita=soglia_similarita)
    except Exception as e:
        return {"dry_run": dry_run, "errore": str(e), "rimossi": 0,
                "cancellati": 0, "potati": 0, "uniti": 0, "fusi": 0,
                "fatti_prima": 0, "fatti_dopo": 0, "candidati": []}


# alias, per chi la chiama con un nome diverso
# Alias di metodo sulla classe, per chi chiama l'istanza.
IndiceMemoria.ottimizza = IndiceMemoria.ottimizza_memoria
IndiceMemoria.optimize_memory = IndiceMemoria.ottimizza_memoria
IndiceMemoria.potatura_memoria = IndiceMemoria.ottimizza_memoria
IndiceMemoria.potatura = IndiceMemoria.ottimizza_memoria

ottimizza = ottimizza_memoria
optimize_memory = ottimizza_memoria
potatura_memoria = ottimizza_memoria