"""I progetti: una cartella, e tutto quello che ci accade dentro.

COSA E' UN PROGETTO

Un progetto e' una cartella con un nome. Non una metafora: il posto
dove l'agente scrive, il posto da cui legge, il posto dove il confine
di sicurezza si sposta. "Il sito del ristorante" e' D:\\lavori\\sito e
non un'etichetta su una cartella generica.

PERCHE' ESISTE

Prima l'agente lavorava sempre nella stessa cartella, quella da cui
era partito: ORCHESTRA_ROOT. Chi faceva piu' di un progetto non
aveva modo di tenere le cose separate — le note del sito del
ristorante finivano accanto a quelle dell'app per parrucchieri, e i
file di uno si sovrascrivevano con quelli dell'altro.

TRE PEZZI, TRE PROBLEMI DIVERSI

1. LA CARTELLA. Il confine si sposta con il progetto. Il tool
   `read_file` con un percorso relativo deve leggere DENTRO il progetto
   attivo, non dentro la cartella di installazione.

2. LA MEMORIA. Ogni fatto che nasce da un turno porta il nome del
   progetto, e la ricerca puo' chiedere "solo i fatti di questo
   progetto". La memoria resta un archivio solo — non una copia per
   progetto — ma i fatti sanno di dove vengono.

3. LA CRONOLOGIA. Le conversazioni, le tracce e i file toccati
   appartengono a un progetto. "Apri il sito del ristorante" deve
   mostrare quello che e' successo li', non tutto.

IL RICONOSCIMENTO DELL'INTENTO

L'utente scrive "oggi lavoriamo al sito ristorante" e Orchestra deve
capire quale progetto intendere. Il riconoscimento ha due regole, e
nessuna delle due e' negoziabile.

La prima: serve l'INTENZIONE. Il nome del progetto da solo non
basta. "Il ristorante era bello" parla del ristorante, non chiede di
lavorare sul sito del ristorante — e spostare la cartella su quella
frase significa che da lì in poi l'agente scrive dentro quel
progetto, senza che nessuno lo abbia chiesto.

La seconda: se il match non e' chiaro si chiede, non si indovina. Un
agente che scrive nel progetto sbagliato fa un danno che l'utente
scopre dopo, e il danno e' nel suo progetto.

E' in italiano e in inglese: chi scrive a un agente scrive in
inglese mette' meta' delle volte, e un riconoscimento che capisce
una sola lingua costringe a scrivere nella lingua giusta per ottenere
che l'agente lavori nella cartella giusta.

LA ROOT PER SESSIONE

Il thread del turno e' un thread suo, e i tool ci girano dentro. La
root del thread corrente e' la root che vale per quel turno: si puo'
cosi' avere due sessioni aperte su due progetti diversi, e ognuna
lavora nella sua cartella. Il figlio della delega eredita la root
del padre — un figlio che scrive altrove sarebbe un bug, non una
scelta.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from typing import Any

from .dati import percorso as percorso_dati

# Il DB dei progetti e' SEPARATO dallo storico. Lo storico contiene
# le conversazioni e le tracce: sono dati di una sessione e non
# cambiano quando l'utente registra un progetto nuovo. Mescolarli
# significa che la migrazione di una tabella rischia di toccare
# l'altra, e un DB che non si puo' riparare da solo e' un DB che
# perde dati.
_DB = "progetti.db"

_LOCK = threading.RLock()

# Il progetto attivo per thread. `threading.local` perche' il server
# HTTP crea un thread per richiesta e il turno gira in un thread suo:
# un attributo normale sarebbe condiviso da tutti e due i turni
# finirebbero nella stessa cartella.
_LOCALE = threading.local()


# --------------------------------------------------------------------------
# Il DB


def percorso_db() -> str:
    return percorso_dati(_DB)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(percorso_db(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # La colonna degli alias e' arrivata dopo la creazione della
    # tabella: SQLite non ha "ADD COLUMN IF NOT EXISTS", quindi si
    # prova e si ignora l'errore quando la colonna c'e' gia'. Il
    # "duplicate column name" E' l'errore che dice "sta tutto bene".
    try:
        conn.execute("ALTER TABLE progetti ADD COLUMN alias TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS progetti (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL,
    percorso    TEXT    NOT NULL,
    note        TEXT    NOT NULL DEFAULT '',
    creato      REAL    NOT NULL,
    aggiornata  REAL    NOT NULL,
    ultimo_use  REAL    NOT NULL DEFAULT 0
);

-- Gli alias: altri nomi per lo stesso progetto. "Sito Ristorante"
-- si chiama anche "restaurant site", o solo "restaurant", o "menu".
--
-- Servono perche' i nomi non si possono tradurre da soli: se il
-- progetto si chiama "Sito Ristorante", il testo inglese "restaurant
-- site" non contiene nessuna parola del nome, e il riconoscimento
-- non puo' tirare a indovinare. L'alias e' l'informazione che
-- manca, e la da' l'utente.
--
-- La colonna si aggiunge con un ALTER a parte, perche' SQLite non
-- ha "ADD COLUMN IF NOT EXISTS" e il comando deve poter girare
-- anche quando la colonna c'e' gia'.

-- Il nome e' univoco: due progetti con lo stesso nome non
-- possono esistere, o l'utente non saprebbe quale aprire. La
-- ricerca dei nomi e' case-insensitive anche su Windows, dove
-- "Sito" e "sito" sono la stessa cartella.
CREATE UNIQUE INDEX IF NOT EXISTS idx_progetti_nome
    ON progetti (LOWER(nome));

-- I file toccati: cosa e' stato creato o modificato, e quando.
-- Non e' git: e' quello che Orchestra ha fatto in quel progetto,
-- e serve a una domanda diversa ("cosa ha toccato l'agente in
-- questa conversazione"), che git status non risponde.
CREATE TABLE IF NOT EXISTS file_toccati (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    progetto    TEXT    NOT NULL DEFAULT '',
    sessione_id INTEGER,
    path        TEXT    NOT NULL,
    azione      TEXT    NOT NULL DEFAULT 'modificato',
    ts          REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_toccati_progetto
    ON file_toccati (progetto, ts DESC);
"""


# --------------------------------------------------------------------------
# I progetti


def _norm(nome: str) -> str:
    return (nome or "").strip().lower()


def _normalizza_alias(alias: str | list[str]) -> list[str]:
    """Gli alias come lista pulita, senza duplicati.

    Accetta una stringa separata da virgole o una lista: l'utente
    scrive "restaurant site, menu" e il codice lo usa come lista.
    """
    if isinstance(alias, (list, tuple)):
        parti = list(alias)
    else:
        parti = str(alias or "").split(",")
    out: list[str] = []
    for p in parti:
        p = (str(p or "")).strip().lower()
        if p and p not in out:
            out.append(p)
    return out


def alias_di(riga: dict[str, Any]) -> list[str]:
    """Gli alias di un progetto, come lista."""
    return _normalizza_alias(str(riga.get("alias") or ""))


def registra(nome: str, percorso_progetto: str, note: str = "",
             alias: str | None = None) -> dict[str, Any]:
    """Registra un progetto, o aggiorna quello che c'e' gia' col nome.

    Aggiornare invece di duplicare e' la scelta che rende il comando
    "oggi lavoriamo al sito ristorante" usabile per sempre: il nome
    resta, il percorso cambia se la cartella e' stata spostata, e
    non si accumulano due progetti con lo stesso nome che l'utente
    non sa distinguere.

    Gli ALIAS sono gli altri nomi dello stesso progetto: "restaurant
    site", "menu", "sito". Servono perche' il riconoscimento non
    puo' tradurre da solo un nome italiano in uno inglese, e senza
    alias l'inglese semplicemente non funziona.

    Sono separati da virgola. Se un alias c'e' gia' non viene
    duplicato.

    Il None e' diverso dalla stringa vuota, ed e' una distinzione che
    conta: None vuol dire "non toccare gli alias", stringa vuota
    vuol dire "cancella tutti". Senza questa distinzione, cambiare
    il percorso di un progetto (che si fa quando la cartella e'
    stata spostata) azzererebbe gli alias — e nessuno se ne
    accorgerebbe, perche' l'alias non si vede da nessuna parte
    finche' non smette di funzionare.
    """
    nome = (nome or "").strip()
    percorso_progetto = os.path.abspath(os.path.expanduser(percorso_progetto or ""))
    if not nome:
        raise ValueError("il progetto ha bisogno di un nome")
    if not percorso_progetto:
        raise ValueError("il progetto ha bisogno di un percorso")
    alias_txt = (None if alias is None
                 else ",".join(_normalizza_alias(alias)))
    ora = time.time()
    with _LOCK:
        conn = _db()
        try:
            riga = conn.execute(
                "SELECT id FROM progetti WHERE LOWER(nome) = ?",
                (_norm(nome),)).fetchone()
            if riga:
                if alias_txt is None:
                    # Gli alias non li tocciamo: si cambia solo il
                    # percorso.
                    conn.execute(
                        "UPDATE progetti SET percorso = ?, note = ?,"
                        " aggiornata = ? WHERE id = ?",
                        (percorso_progetto, note or "", ora, int(riga["id"])))
                else:
                    conn.execute(
                        "UPDATE progetti SET percorso = ?, note = ?, alias = ?,"
                        " aggiornata = ? WHERE id = ?",
                        (percorso_progetto, note or "", alias_txt, ora,
                         int(riga["id"])))
                progetto_id = int(riga["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO progetti (nome, percorso, note, creato,"
                    " aggiornata, ultimo_use, alias) VALUES (?,?,?,?,?,0,?)",
                    (nome, percorso_progetto, note or "", ora, ora,
                     alias_txt or ""))
                progetto_id = int(cur.lastrowid)
            conn.commit()
        finally:
            conn.close()
    return percorso_progetto


def percorso_di(nome: str) -> str:
    """Il percorso del progetto con quel nome, o "" se non esiste."""
    with _LOCK:
        conn = _db()
        try:
            r = conn.execute(
                "SELECT percorso FROM progetti WHERE LOWER(nome) = ?",
                (_norm(nome),)).fetchone()
            return str(r["percorso"]) if r else ""
        finally:
            conn.close()


def tutti() -> list[dict[str, Any]]:
    """Tutti i progetti, con quanti file hanno toccato."""
    with _LOCK:
        conn = _db()
        try:
            righe = conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM file_toccati f
                         WHERE LOWER(f.progetto) = LOWER(p.nome))
                         AS n_file
                  FROM progetti p
                 ORDER BY LOWER(p.nome)
                """).fetchall()
            return [dict(r) for r in righe]
        finally:
            conn.close()


def per_nome(nome: str) -> dict[str, Any] | None:
    with _LOCK:
        conn = _db()
        try:
            r = conn.execute(
                "SELECT * FROM progetti WHERE LOWER(nome) = ?",
                (_norm(nome),)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()


def elimina(nome: str) -> bool:
    """Cancella il progetto. I fatti di memoria restano: cancellare
    un progetto non deve cancellare quello che l'agente ha imparato
    su di esso — e i fatti senza progetto sono comunque utili per
    ogni progetto."""
    with _LOCK:
        conn = _db()
        try:
            cur = conn.execute("DELETE FROM progetti WHERE LOWER(nome) = ?",
                               (_norm(nome),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def tocca(nome: str) -> None:
    """Segna il progetto come usato adesso: serve a ordinare l'elenco."""
    if not nome:
        return
    with _LOCK:
        conn = _db()
        try:
            conn.execute(
                "UPDATE progetti SET ultimo_use = ?, aggiornata = ?"
                " WHERE LOWER(nome) = ?",
                (time.time(), time.time(), _norm(nome)))
            conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------
# I file toccati


def registra_file(progetto: str, path: str, azione: str = "modificato",
                   sessione_id: int | None = None) -> None:
    """Segna un file come toccato.

    Silenziosa per scelta: la traccia dei file e' un aiuto, e un
    errore nel registrare non deve far fallire il tool che stava
    scrivendo il file. Sarebbe il caso peggiore: il file e' scritto,
    e l'errore dice che non e' stato scritto.
    """
    if not path:
        return
    try:
        with _LOCK:
            conn = _db()
            try:
                conn.execute(
                    "INSERT INTO file_toccati (progetto, sessione_id, path,"
                    " azione, ts) VALUES (?,?,?,?,?)",
                    (progetto or "", sessione_id, str(path), azione,
                     time.time()))
                conn.commit()
            finally:
                conn.close()
    except Exception:  # noqa: BLE001
        pass


def file_toccati(progetto: str = "", limite: int = 200) -> list[dict[str, Any]]:
    """I file toccati, i piu' recenti prima.

    Con `progetto` vuoto vengono tutti i file di tutti i progetti:
    e' la vista "cosa ha fatto Orchestra" senza filtri.
    """
    with _LOCK:
        conn = _db()
        try:
            if progetto:
                righe = conn.execute(
                    "SELECT * FROM file_toccati WHERE LOWER(progetto) = ?"
                    " ORDER BY ts DESC LIMIT ?",
                    (_norm(progetto), limite)).fetchall()
            else:
                righe = conn.execute(
                    "SELECT * FROM file_toccati ORDER BY ts DESC LIMIT ?",
                    (limite,)).fetchall()
            return [dict(r) for r in righe]
        finally:
            conn.close()


# --------------------------------------------------------------------------
# La root per sessione


def _root_sessione() -> str:
    """La root del thread corrente, o "" se non ne ha una.

    Il thread del turno e' un thread suo, e il thread della richiesta
    HTTP e' un altro: e' esattamente per questo che la root sta in un
    `threading.local`. Con un attributo normale, due richieste
    contemporanee si scriverebbero l'una nella cartella dell'altra.
    """
    return getattr(_LOCALE, "root", "") or ""


def _set_root_sessione(percorso_progetto: str,
                       nome_progetto: str = "") -> None:
    _LOCALE.root = percorso_progetto or ""
    _LOCALE.nome = nome_progetto or ""


def _root_progetto() -> str:
    """Il NOME del progetto attivo, o "" se non c'e'.

    E' il nome e non il percorso perche' e' il nome quello che
    etichetta i fatti di memoria: due progetti con lo stesso nome
    sono lo stesso progetto, e il percorso puo' cambiare senza che
    la memoria debba cambiare con lui.
    """
    return getattr(_LOCALE, "nome", "") or ""


# --------------------------------------------------------------------------
# Il riconoscimento dell'intento


# I VERBI D'INTENZIONE: le parole che dicono 'adesso lavoriamo su
# X'. Sono la condizione NECESSARIA per spostare la cartella, e non
# un semplice aiuto al match.
#
# Perche' sono necessari: senza, 'il ristorante era bello' sposta
# Orchestra nella cartella del sito del ristorante, e da quel momento
# ci scrive dentro. E' il caso peggiore di tutto il meccanismo: non
# un'etichetta sbagliata, ma file scritti nella cartella sbagliata,
# e l'utente lo scopre guardando i file.
#
# Le frasi sono scelte per la forma, non per un vocabolario: 'lavoro
# sul sito' e 'lavoriamo al sito' sono la stessa intenzione con
# preposizioni diverse, e un elenco di parole sezionerebbe i due casi
# perche' la preposizione cambia.
#
# 'voglio continuare col parrucchieri' conta: e' la forma piu'
# comune di 'torniamo a lavorare su X' quando non hai detto 'oggi'.
_VERBI_INTENZIONE = (
    # lavorare
    "lavoro", "lavoriamo", "lavoreremo", "lavora", "lavorate", "lavorano",
    # prendere in mano, occuparsi
    "occupo", "occupiamo", "occupiamoci", "prendo", "prendiamo",
    "mi occupo", "ci occupiamo",
    # spostarsi
    "passo", "passiamo", "passa", "torno", "torniamo", "torna",
    "vado", "andiamo", "vai",
    # proseguire, continuare
    "proseguo", "proseguiamo", "continuo", "continuiamo", "continua",
    "riprendo", "riprendiamo",
    # aprire
    "apro", "apriamo", "apri",
    # cambiare
    "cambio", "cambiamo", "cambia",
    # le frasi con la preposizione: e' la forma piu' comune
    "voglio continuare", "voglio lavorare", "voglio riprendere",
    "voglio proseguire", "voglio cambiare", "voglio passare",
    "voglio tornare", "voglio occuparmi", "voglio andare",
    "passo a", "passiamo a", "torno a", "torniamo a",
    "vado a", "vado su", "lavoro su", "lavoriamo su",
    "lavoro a", "lavoriamo a", "lavoro al", "lavoriamo al",
    "lavoro nel", "lavoriamo nel", "lavoro sul", "lavoriamo sul",
    "mi occupo di", "occupiamoci di", "cambio a", "cambiamo a",
    "proseguo con", "proseguiamo con", "prosegui con",
    # -- inglese --
    # L'inglese non e' un extra: chi scrive a un agente scrive in
    # inglese mette' meta' delle volte, e un riconoscimento che
    # capisce solo l'italiano costringe a scrivere nella lingua giusta
    # per ottenere che l'agente lavori nella cartella giusta.
    #
    # Ma con una differenza: in inglese il verbo nudo NON basta.
    # "work" da solo e' come "lavoro" in italiano — pero' in inglese
    # "the work was great" e' una frase normale, e metterebbe
    # Orchestra nella cartella del progetto. Le frasi con la
    # preposizione sono quelle che dicono davvero "su questo".
    "work on", "working on", "work with", "working with",
    "let's work on", "lets work on", "i work on", "im working on",
    "switch to", "switching to", "move to", "moving to",
    "go to", "going to", "head to", "head back to",
    "back to", "continue on", "continuing on", "resume", "resuming",
    "pick up", "picking up", "open", "opening", "start with",
    "starting with", "i want to continue", "i want to work",
    "i want to resume", "i want to switch", "i want to move",
    "i want to go", "let's continue", "lets continue",
    "i'll work on", "ill work on", "we should work on",
)


def _ha_intenzione(parole: list[str]) -> bool:
    """Il testo dice 'adesso lavoriamo su qualcosa'?

    Non basta una parola qualsiasi: si cercano le FRASI, e una
    frase conta solo se e' intera. 'voglio' da solo non basta —
    'voglio mangiare al ristorante' non e' un cambio di progetto —
    ma 'voglio continuare' sì.

    Le frasi contengono 'voglio' perche' e' la forma in cui si dice
    'torniamo a lavorare su X' senza dire 'oggi': e' la piu'
    comune, e toglierla renderebbe il riconoscimento rigido sul
    solo linguaggio di lavoro.
    """
    testo = ' '.join(parole)
    for frase in _VERBI_INTENZIONE:
        if "'" in frase:
            # Le frasi con l'apostrofo si cercano in forma COMPATTA:
            # "let's work on" e' diventato "let s work on" dai
            # token, e "let s work on" non contiene "let's work on".
            # La forma compatta ("letsworkon") la contiene.
            if frase.replace("'", "").replace(" ", "") in "".join(parole):
                return True
        elif " " in frase:
            if frase in testo:
                return True
        elif frase in parole:
            return True
    return False


def _tokens(testo: str) -> list[str]:
    """Le parole del testo, minuscole, senza la punteggiatura.

    I nomi dei progetti contengono spazi ("sito ristorante"), quindi
    la ricerca non puo' essere per parola singola: si prova anche
    la sequenza di parole consecutive.

    L'apostrofo diventa uno SPAZIO, non resta un carattere:
    "let's" deve diventare "let s" e non "let s" con l'apostrofo
    in mezzo, altrimenti le frasi inglesi non si trovano mai. E
    "l'intento" diventa "l intento", che e' la stessa cosa: in
    italiano l'apostrofo e' solo un segno.

    Con l'inglese pero' una contrazione come "i'm" diventa "i m",
    e "i m working on X" non e' "im working on X": per questo la
    ricerca delle frasi prova anche la versione SENZA spazi.
    """
    testo = (testo or "").lower()
    testo = re.sub(r"[^\w\s]", " ", testo, flags=re.UNICODE)
    return [w for w in testo.split() if w]


def riconosci(testo: str) -> tuple[str, str]:
    """Cerca un progetto nel testo. Torna (nome, "") o ("", "").

    Il secondo valore e' il motivo per cui NON ha trovato, quando il
    testo nomina piu' di un progetto: e' il caso in cui chiedere e'
    l'unica cosa giusta da fare, e il motivo serve a spiegare la
    domanda.

    Non riconosce niente se il testo non nomina un progetto: "ciao,
    come stai" non deve girare il progetto. E non riconosce niente
    se il nome appare dentro una parola piu' lunga ("ristorante" dentro
    "ristorantino" non e' un match).

    E non riconosce niente se il testo NON HA INTENZIONE. Il nome
    del progetto da solo non basta: "il ristorante era bello" parla
    del ristorante, non chiede di lavorare sul sito del ristorante.
    Spostare la cartella su quella frase significa che da lì in poi
    l'agente scrive dentro il progetto del ristorante — e l'utente
    non l'ha chiesto, e forse non se ne accorge.

    La regola e' semplice: il progetto si sposta SOLO se il testo
    nomina un progetto E dice che adesso ci si lavora. Il nome da
    solo, senza intenzione, non sposta niente.
    """
    parole = _tokens(testo)
    if not parole:
        return "", ""
    if not _ha_intenzione(parole):
        return "", ""
    trovati: list[str] = []
    for p in progetti_noti():
        nome = str(p.get("nome") or "")
        if not nome:
            continue
        nome_low = nome.lower()
        parole_nome = nome_low.split()
        if _corrisponde(parole, nome_low, parole_nome, alias_di(p)):
            if nome not in trovati:
                trovati.append(nome)
    if not trovati:
        return "", ""
    if len(trovati) == 1:
        return trovati[0], ""
    return "", ("il testo nomina piu' progetti: "
                + ", ".join(sorted(trovati)))


def _corrisponde(parole: list[str], nome_low: str,
                  parole_nome: list[str],
                  alias: list[str] | None = None) -> bool:
    """Il testo nomina questo progetto?

    Tre modi, in ordine di confidenza:
    - il nome intero, parola per parola ("sito ristorante")
    - il nome come parola singola ("ristorante" per "Sito Ristorante")
    - una parola distintiva del nome, che deve essere lunga abbastanza
      da non essere una parola qualsiasi ("parrucchieri" per
      "App Parrucchieri", ma non "app" che e' troppo generico)

    E gli ALIAS: i nomi che il progetto ha in un'altra lingua o
    in un'altra forma. Sono la risposta al problema che i nomi non
    si possono tradurre da soli: un progetto chiamato "Sito
    Ristorante" non si riconosce in "restaurant site", e non si puo'
    sapere che quel progetto e' quello.

    L'alias e' quello che sa l'utente, e puo' essere piu' di uno:
    "restaurant site", "restaurant", "menu". Senza di lui, l'inglese
    non funziona — e non funziona perche' manca un'informazione,
    non perche' il riconoscimento e' fatto male.
    """
    if not parole_nome:
        return False
    # il nome intero, consecutively
    n = len(parole_nome)
    for i in range(len(parole) - n + 1):
        if parole[i:i + n] == parole_nome:
            return True
    # il nome come una parola
    if len(parole_nome) == 1 and parole_nome[0] in parole:
        return True
    # una parola distintiva: lunga, e presente nel testo
    for w in parole_nome:
        if len(w) >= 5 and w in parole:
            return True
    # Gli alias: stessa logica del nome, ma sull'insieme delle
    # parole che formano l'alias.
    for a in (alias or []):
        parole_alias = a.lower().split()
        if not parole_alias:
            continue
        m = len(parole_alias)
        for i in range(len(parole) - m + 1):
            if parole[i:i + m] == parole_alias:
                return True
        # una parola sola dell'alias, se e' abbastanza distintiva
        for w in parole_alias:
            if len(w) >= 5 and w in parole:
                return True
    return False


def progetti_noti() -> list[dict[str, Any]]:
    """I progetti registrati, in forma ridotta per il riconoscimento."""
    try:
        return tutti()
    except Exception:  # noqa: BLE001
        return []
