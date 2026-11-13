"""Il ponte verso Telegram: un bot di Orchestra che risponde in chat.

CHE COSA E' UN BOT TELEGRAM, QUI

Non e' un secondo agente: e' un telefono. Il bot di Orchestra resta
quello che e' (la sua persona, il suo modello, il suo progetto, la sua
policy), e questa e' la porta da cui gli si scrive quando non si e'
davanti al computer. La risposta che arriva su Telegram e' la stessa che
si sarebbe letta nella finestra: lo stesso turno, gli stessi tool, gli
stessi permessi.

PERCHE' UNA CHAT SOLA, E PERCHE' IL CODICE

Un bot Telegram con un token e' raggiungibile da chiunque conosca il suo
nome utente. Se l'agente dietro ha accesso alla shell e ai file, "un
messaggio da chiunque" e' un esecutore remoto con le nostre chiavi. Per
questo il primo messaggio da una chat non e' una richiesta: e' una
richiesta di collegamento, e vale solo con un codice che compare nella
finestra di Orchestra — cioe' solo per chi ha gia' accesso alla
macchina. Il codice e' a uso singolo, scade, e vive in memoria: un
codice letto ieri da uno screenshot non apre niente oggi.

PERCHE' IL POLLING E NON IL WEBHOOK

Un webhook vuole un indirizzo pubblico, un certificato e una porta
aperta: tre cose che un'app installata sul portatile di casa non ha.
`getUpdates` funziona da dietro un NAT e non chiede niente a nessuno.
Costa una richiesta ogni 25 secondi per bot collegato, ed e' il
compromesso giusto per quello che deve fare.

L'ARRETRATO NON SI RIGIOCA

Al primo giro si chiede l'ultimo aggiornamento (`offset=-1`) e si parte
da dopo: senza, riaprendo Orchestra dopo un giorno si rivedrebbero tutti
i messaggi di quel giorno, e l'agente li eseguirebbe una seconda volta.
Un'app che rifa' il lavoro di ieri appena la riapri e' peggio di una che
non risponde.

LA CHIAVE

Il token di BotFather e' una credenziale: sta in un database nella
cartella dati dell'utente, non nel `.env` (che e' uno per installazione,
mentre qui i bot sono tanti) e non nei log.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .dati import FILE_STATO, percorso as percorso_dati

BASE = "https://api.telegram.org"
_DB = "telegram.db"
_LOCK = threading.RLock()

# La forma di un token di BotFather: cifre, due punti, poi la parte
# opaca. Si controlla PRIMA di chiamare la rete: un token palesemente
# sbagliato non merita un giro di 5 secondi per sentirsi dire da
# Telegram "unauthorized", che non spiega dove si e' sbagliato.
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")

# Senza 0/O e 1/I/L: il codice si legge da uno schermo e si ricopia a
# mano sul telefono, e confondere due caratteri simili e' l'unico errore
# che questa procedura puo' ancora avere.
ALFABETO = "abcdefghjkmnpqrstuvwxyz23456789"
LUNGHEZZA_CODICE = 8
SCADENZA_CODICE = 600.0

# Il limite vero di Telegram e' 4096 caratteri. Si taglia a 4000 per
# avere spazio per l'indicatore di pezzo "(2/3)" senza sforare.
MAX_TESTO = 4000

ATTESA_POLLING = 25
INTERVALLO_ERRORE = 10.0

# Un turno lungo non deve lasciare l'utente davanti a un puntino che
# scrive: il messaggio di stato si aggiorna, ma non a ogni evento.
# Telegram limita le modifiche per chat, e un aggiornamento ogni token
# servirebbe solo a far buttare via tutti gli altri.
PRIMO_AVVISO = 1.5
INTERVALLO_PROGRESSO = 2.5

# Le azioni (un tool che parte) sono un'altra cosa dal pensiero: sono
# quello che uno vuole vedere, e ognuna resta in chat come messaggio
# suo. Due limiti tengono la chat leggibile: non piu' di una raffica
# al secondo, e un tetto per turno — oltre, la cronaca diventa un muro
# e la risposta finisce fuori schermo.
INTERVALLO_AZIONE = 1.0
MAX_AZIONI = 20

# Un album (tre foto mandate insieme) non e' un messaggio: sono tre
# aggiornamenti separati che Telegram consegna a pochi decimi l'uno
# dall'altro, e l'unica cosa che li lega e' lo stesso `media_group_id`.
# Trattare il primo come la richiesta vuol dire far partire un turno con una
# foto mentre le altre due sono ancora per strada, e l'agente chiede all'utente
# una foto che ha gia' mandato. Si aspetta un attimo l'ultima: il timer si
# riarma a ogni pezzo, quindi parte da sola quando il gruppo e' finito.
ATTESA_ALBUM = 1.5

# Il tetto del Bot API per `getFile`. Oltre, il file non si scarica
# nemmeno: dirlo prima evita un errore di rete che sembra un guasto.
MASSIMO_FILE = 20 * 1024 * 1024

# I comandi che il ponte sa consegnare a chi gestisce la sessione: la
# chat non entra nel merito, ma deve sapere cosa e' un comando suo e
# cosa e' un errore di battitura.
COMANDI_AGENTE = ("stato", "steer", "stop", "nuova", "modello",
                  "reasoning", "ragionamento", "obiettivo", "consiglio",
                  "aggiorna", "update", "riavvia", "restart")

# Il menu che Telegram mostra quando si preme "/". E' del BOT, non
# dell'app: un bot usato prima con un'altra applicazione si porta dietro
# i suoi comandi finche' qualcuno non li sostituisce. Orchestra non lo
# faceva, quindi chi cambiava app trovava il menu vecchio — e sembrava
# che quei comandi esistessero ancora.
COMANDI_MENU = (
    ("start", "Collega questa chat"),
    ("aiuto", "La lista dei comandi"),
    ("stato", "Modello, turno e collegamento"),
    ("steer", "Guida il turno in corso"),
    ("stop", "Ferma il turno"),
    ("nuova", "Nuova conversazione"),
    ("modello", "Scegli il modello"),
    ("reasoning", "Ragionamento: livello e mostra/nascondi"),
    ("obiettivo", "Crea un obiettivo, o elenca quelli aperti"),
    ("consiglio", "Chi mettere al tavolo per una decisione"),
    ("aggiorna", "Aggiorna e riavvia il server"),
    ("riavvia", "Riavvia il server"),
    ("scollega", "Stacca questa chat"),
)

# Il tetto del Bot API per un file in INVIO: oltre, Telegram risponde
# 413 e il file non arriva. E' piu' alto di quello del download perche'
# sono due limiti diversi, e confonderli farebbe rifiutare file che ci
# stanno benissimo.
MASSIMO_INVIO = 50 * 1024 * 1024
# Un turno che scrive venti file non deve trasformare la chat in un
# archivio: si mandano i primi, e si dice che ci sono gli altri.
MASSIMO_FILE_PER_TURNO = 5
# Le sole immagini che sendPhoto accetta. Un gif o un webp come "foto"
# vengono rifiutati da Telegram, quindi passano come documento.
FOTO = (".jpg", ".jpeg", ".png")
MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
    ".zip": "application/zip", ".mp3": "audio/mpeg", ".mp4": "video/mp4",
    ".csv": "text/csv", ".md": "text/markdown", ".txt": "text/plain",
}


def _tipo_mime(nome: str) -> str:
    """Il tipo del file, dalla sua estensione. Generico va bene."""
    return MIME.get(os.path.splitext(nome or "")[1].lower(),
                    "application/octet-stream")

GUIDA = (
    "Quello che scrivi qui e' una richiesta all'agente: stesso bot, "
    "stessi tool, stessa policy della finestra.\n\n"
    "Comandi:\n"
    "/stato - modello, turno in corso, collegamento\n"
    "/steer <testo> - guida il turno in corso (mentre lavora, un "
    "messaggio normale fa lo stesso)\n"
    "/stop - ferma il turno in corso\n"
    "/nuova - nuova conversazione\n"
    "/aggiorna (o /update) - scarica l'ultima release e riavvia il server\n"
    "/riavvia (o /restart) - riavvia il server senza aggiornare\n"
    "/modello - il modello in uso, e il menu per cambiarlo (prima il "
    "servizio, poi il modello: un tocco)\n"
    "/modello <nome> - cambia il modello scrivendone il nome\n"
    "/reasoning (o /ragionamento) - senza argomento apre i pulsanti: "
    "livello e mostra/nascondi in chat, col segno su quello che vale "
    "adesso. on/off lo dicono esplicitamente, senza aprire niente\n"
    "/reasoning <livello> - quanto ragiona il modello: none, minimal, "
    "low, medium, high, xhigh, max, oppure auto per lasciare decidere "
    "a Orchestra. Vale per TUTTE le sessioni e resta dopo il riavvio "
    "(la vista in chat, invece, e' solo di questo bot)\n"
    "/obiettivo <testo> - avvia un obiettivo in autonomia (come il "
    "pannello Obiettivo). Senza testo, elenca quelli aperti\n"
    "/consiglio <decisione> - chi metterei al tavolo e perche', in una "
    "riga per seat\n"
    "/scollega - stacca questa chat\n"
    "/aiuto (o /guida) - questa lista\n\n"
    "Foto e documenti li leggo, i vocali li trascrivo se il motore "
    "vocale e' installato: il pulsante Dipendenze in Opzioni, il "
    "componente si chiama faster-whisper.\n\n"
    "Se un tool chiede un permesso, se l'agente ha una domanda o se "
    "propone un piano, il messaggio arriva qui con i pulsanti: si "
    "risponde toccando, o scrivendo la risposta.\n"
    "Se il turno produce un file (un PDF, un'immagine, un foglio) te lo "
    "allego alla risposta."
)


class ErroreTelegram(RuntimeError):
    """La chiamata all'API non e' riuscita, e il messaggio dice perche'."""

    def __init__(self, messaggio: str, codice: int | None = None) -> None:
        super().__init__(messaggio)
        self.codice = codice


class ErroreAllegato(RuntimeError):
    """Un file arrivato male: il testo dell'errore si mostra in chat."""


# Cosa sa arrivare da Telegram, e cosa se ne fa. Le foto sono un array di
# versioni della stessa immagine (Telegram le prepara in piu' misure): si
# prende la piu' grande, perche' quella piccola e' un francobollo che il
# modello legge peggio.
TIPI_ALLEGATO = {
    "photo": "foto",
    "voice": "voce",
    "audio": "audio",
    "document": "documento",
    "video": "video",
}

# Cosa si dice all'agente di una foto senza didascalia. E' una costante
# perche' serve due volte: come predefinito, e per riconoscerlo quando le
# foto sono tante e una didascalia vera c'e' gia' — tre righe uguali
# sotto la stessa richiesta non aggiungono niente.
TESTO_FOTO = "Guarda questa immagine."

NOME_PREDEFINITO = {
    "foto": "foto.jpg",
    "voce": "vocale.oga",
    "audio": "audio.mp3",
    "documento": "documento",
    "video": "video.mp4",
}


def allegato_da(messaggio: dict[str, Any]) -> dict[str, Any] | None:
    """Il file dentro un messaggio, se c'e': tipo, id, nome, didascalia.

    Restituisce None per un messaggio di solo testo. E' una funzione a
    se' perche' e' la parte che si puo' sbagliare in silenzio: un array
    di foto vuoto, un campo che manca, una didascalia assente. Il resto
    del ponte riceve un dizionario gia' pulito.
    """
    if not isinstance(messaggio, dict):
        return None
    didascalia = (messaggio.get("caption") or "").strip()

    for campo, tipo in TIPI_ALLEGATO.items():
        voci = messaggio.get(campo)
        if isinstance(voci, list):
            # Solo `photo` e' una lista: le altre misure sono dizionari.
            voci = [v for v in voci if isinstance(v, dict) and v.get("file_id")]
            if not voci:
                continue
            voce = max(voci, key=lambda v: int(v.get("file_size") or
                                               v.get("width") or 0))
        elif isinstance(voci, dict):
            voce = voci
        else:
            continue
        file_id = voce.get("file_id") or ""
        if not file_id:
            continue
        nome = (voce.get("file_name") or "").strip()
        nome = nome or NOME_PREDEFINITO.get(tipo, "file")
        return {
            "tipo": tipo,
            "file_id": str(file_id),
            "nome": nome,
            "dimensione": int(voce.get("file_size") or 0),
            "didascalia": didascalia,
        }
    return None


# ===================================================================
#  Dove si salvano i collegamenti
# ===================================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram (
    bot_id      INTEGER PRIMARY KEY,
    token       TEXT NOT NULL DEFAULT '',
    username    TEXT NOT NULL DEFAULT '',
    chat_id     TEXT NOT NULL DEFAULT '',
    chat_nome   TEXT NOT NULL DEFAULT '',
    ragionamento INTEGER NOT NULL DEFAULT 0,
    creato      REAL NOT NULL,
    aggiornato  REAL NOT NULL
);
"""


def percorso_db() -> str:
    return percorso_dati(_DB)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(percorso_db(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Le righe create prima che si salvasse il nome utente non ce l'hanno:
    # `CREATE TABLE IF NOT EXISTS` non tocca una tabella che esiste gia',
    # e la migrazione idempotente e' il modo che usa anche `bots._db`.
    try:
        conn.execute("ALTER TABLE telegram ADD COLUMN username TEXT NOT NULL "
                     "DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # Stessa cosa per l'interruttore del ragionamento: chi ha gia' il
    # database non lo ricrea di certo, e una colonna assente farebbe
    # fallire ogni lettura dei collegamenti.
    try:
        conn.execute("ALTER TABLE telegram ADD COLUMN ragionamento INTEGER "
                     "NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


def _riga(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "bot_id": int(r["bot_id"]),
        "token": r["token"] or "",
        "username": r["username"] or "",
        "chat_id": r["chat_id"] or "",
        "chat_nome": r["chat_nome"] or "",
        "ragionamento": bool(r["ragionamento"]),
    }


def tutti() -> list[dict[str, Any]]:
    with _LOCK, _db() as conn:
        return [_riga(r) for r in conn.execute(
            "SELECT * FROM telegram ORDER BY bot_id")]


def token_di(bot_id: int | str) -> str:
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT token FROM telegram WHERE bot_id = ?",
                         (int(bot_id),)).fetchone()
    return (r["token"] if r else "") or ""


def ragionamento(bot_id: int | str) -> bool:
    """Se il ragionamento dell'agente va mostrato in chat.

    Falso e' il comportamento di sempre: in chat si vede cosa fa l'agente
    e cosa risponde, non come ci e' arrivato. E' una scelta per bot e
    resta scritta: chi la accende per capire un turno strano non deve
    riaccenderla al messaggio dopo.
    """
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT ragionamento FROM telegram WHERE bot_id = ?",
                         (int(bot_id),)).fetchone()
    return bool(r and r["ragionamento"])


def imposta_ragionamento(bot_id: int | str, acceso: bool) -> bool:
    """Accende o spegne il ragionamento. False = chat non collegata.

    False non e' un errore da nascondere: senza un collegamento non c'e'
    una riga da aggiornare, e rispondere "fatto" lo stesso vorrebbe dire
    promettere un'impostazione che al prossimo turno non c'e'.
    """
    with _LOCK, _db() as conn:
        cur = conn.execute(
            "UPDATE telegram SET ragionamento = ?, aggiornato = ? "
            "WHERE bot_id = ?",
            (1 if acceso else 0, time.time(), int(bot_id)))
        conn.commit()
        return cur.rowcount > 0


def chat_di(bot_id: int | str) -> tuple[str, str]:
    """La chat collegata: (id, nome). Vuoti se non c'e'."""
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT chat_id, chat_nome FROM telegram "
                         "WHERE bot_id = ?", (int(bot_id),)).fetchone()
    if not r:
        return "", ""
    return (r["chat_id"] or "", r["chat_nome"] or "")


def stato(bot_id: int | str) -> dict[str, Any]:
    """Quello che il pannello deve mostrare, in una riga sola.

    `username` e' il nome utente del bot su Telegram, salvato quando il
    token e' stato verificato: serve a costruire il link `t.me/...`.
    Vuoto vuol dire "non ancora verificato".
    """
    with _LOCK, _db() as conn:
        r = conn.execute("SELECT * FROM telegram WHERE bot_id = ?",
                         (int(bot_id),)).fetchone()
    if not r:
        return {"bot_id": int(bot_id), "token": False, "collegato": False,
                "chat": "", "username": ""}
    riga = _riga(r)
    return {
        "bot_id": riga["bot_id"],
        "token": bool(riga["token"]),
        "collegato": bool(riga["chat_id"]),
        "chat": riga["chat_nome"] or riga["chat_id"],
        "username": riga["username"],
    }


def imposta_username(bot_id: int | str, username: str) -> dict[str, Any]:
    """Il nome utente del bot su Telegram, letto da `getMe`.

    Si salva insieme al token perche' senza non si puo' costruire il
    link da mettere nel QR, e ricavarlo a ogni disegno del pannello
    vorrebbe dire una chiamata di rete per aprire una schermata.
    """
    with _LOCK, _db() as conn:
        conn.execute("UPDATE telegram SET username = ? WHERE bot_id = ?",
                     ((username or "").lstrip("@"), int(bot_id)))
        conn.commit()
    return stato(bot_id)


def salva_token(bot_id: int | str, token: str) -> dict[str, Any]:
    """Salva (o toglie) il token di un bot.

    Un token vuoto non e' un errore: e' "scollega questo bot da
    Telegram", e deve essere possibile senza cancellare il bot.
    """
    testo = (token or "").strip()
    if testo and not TOKEN_RE.match(testo):
        raise ValueError(
            "questo non sembra un token di Telegram: sono due numeri "
            "separati da ':' e una parte lunga. Si copia da @BotFather.")
    ora = time.time()
    with _LOCK, _db() as conn:
        if not testo:
            conn.execute("DELETE FROM telegram WHERE bot_id = ?",
                         (int(bot_id),))
            conn.commit()
            return stato(bot_id)
        conn.execute(
            "INSERT INTO telegram (bot_id, token, creato, aggiornato) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(bot_id) DO UPDATE SET "
            "token = excluded.token, aggiornato = excluded.aggiornato",
            (int(bot_id), testo, ora, ora))
        conn.commit()
    return stato(bot_id)


def imposta_chat(bot_id: int | str, chat_id: str | int,
                 nome: str = "") -> dict[str, Any]:
    """Lega questa chat al bot. Una chat alla volta: la nuova sostituisce."""
    with _LOCK, _db() as conn:
        conn.execute("UPDATE telegram SET chat_id = ?, chat_nome = ?, "
                     "aggiornato = ? WHERE bot_id = ?",
                     (str(chat_id), (nome or "").strip(), time.time(),
                      int(bot_id)))
        conn.commit()
    return stato(bot_id)


def dimentica_chat(bot_id: int | str) -> dict[str, Any]:
    with _LOCK, _db() as conn:
        conn.execute("UPDATE telegram SET chat_id = '', chat_nome = '', "
                     "aggiornato = ? WHERE bot_id = ?",
                     (time.time(), int(bot_id)))
        conn.commit()
    return stato(bot_id)


def pulisci(bot_validi: list[int] | None = None) -> int:
    """Toglie i collegamenti dei bot che non esistono piu'.

    Cancellare un bot dal pannello non deve lasciare un token orfano in
    un database: un token dimenticato e' un bot ancora vivo su Telegram
    che continua a rispondere a una chat che nessuno guarda.
    """
    if bot_validi is None:
        from . import bots as bots_mod

        # L'agente principale (id 0) non e' nella tabella dei bot, ma il
        # suo token e' un collegamento vivo come gli altri: senza questa
        # riga, la prima pulizia dopo il riavvio lo cancellerebbe.
        bot_validi = [int(b["id"]) for b in bots_mod.tutti()]
        bot_validi.append(int(bots_mod.BASE_ID))
    with _LOCK, _db() as conn:
        righe = [int(r["bot_id"]) for r in conn.execute(
            "SELECT bot_id FROM telegram")]
        orfani = [b for b in righe if b not in set(bot_validi)]
        for b in orfani:
            conn.execute("DELETE FROM telegram WHERE bot_id = ?", (b,))
        conn.commit()
    return len(orfani)


# ===================================================================
#  I codici di collegamento
# ===================================================================
_CODICI: dict[int, tuple[str, float]] = {}


def nuovo_codice(bot_id: int | str,
                 secondi: float = SCADENZA_CODICE) -> dict[str, Any]:
    """Un codice nuovo per questo bot, e la scadenza.

    Uno solo per bot: due codici vivi insieme vorrebbero dire due
    possibilita' di collegarsi, e non c'e' nessun motivo di averne due.
    """
    codice = "".join(secrets.choice(ALFABETO)
                     for _ in range(LUNGHEZZA_CODICE))
    scade = time.time() + max(30.0, float(secondi))
    with _LOCK:
        _CODICI[int(bot_id)] = (codice, scade)
    return {"codice": codice, "scade": scade}


def codice_in_corso(bot_id: int | str) -> str:
    """Il codice ancora valido, se c'e'. Non ne crea uno."""
    with _LOCK:
        voce = _CODICI.get(int(bot_id))
    if not voce:
        return ""
    codice, scade = voce
    if time.time() > scade:
        with _LOCK:
            _CODICI.pop(int(bot_id), None)
        return ""
    return codice


def codice_valido(bot_id: int | str, codice: str) -> bool:
    """Vero se il codice e' quello giusto, e in quel caso lo consuma.

    Uso singolo: chi lo ha letto dallo schermo lo usa una volta, e un
    secondo tentativo con lo stesso codice non deve funzionare.
    """
    candidato = (codice or "").strip().lower()
    if not candidato:
        return False
    with _LOCK:
        voce = _CODICI.get(int(bot_id))
        if not voce:
            return False
        giusto, scade = voce
        if time.time() > scade:
            _CODICI.pop(int(bot_id), None)
            return False
        if not secrets.compare_digest(giusto, candidato):
            return False
        _CODICI.pop(int(bot_id), None)
        return True


def link(username: str, codice: str = "") -> str:
    """Il link che apre la chat col bot, col codice gia' dentro.

    Il codice viaggia come parametro `start`: Telegram lo consegna al
    bot come `/start <codice>`, cosi' chi inquadra il QR non deve
    ricopiare niente a mano.
    """
    nome = (username or "").strip().lstrip("@")
    if not nome:
        return ""
    base = f"https://t.me/{nome}"
    return f"{base}?start={codice}" if codice else base


# ===================================================================
#  Le domande in sospeso
# ===================================================================
# I permessi e le domande dell'agente hanno un canale in chat: qui si
# tiene traccia di quella aperta per ogni bot, cosi' il tocco su un
# pulsante (o il testo scritto subito dopo) sa a cosa rispondere.
#
# Perche' un token e non solo l'id della domanda: un modulo puo' restare
# nella chat per giorni, e un "Una volta" premuto sulla richiesta di ieri
# non deve concedere il percorso di oggi. Il token e' la prova che quel
# pulsante appartiene a questa domanda e a nessun'altra.
SOSPESI: dict[int, dict[str, Any]] = {}
# La stessa scadenza dei permessi e delle domande: dopo, chi aspetta ha
# gia' deciso da solo (nega, o va avanti), e un pulsante vivo mentirebbe.
SCADENZA_SOSPESO = 300.0


def _token() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(4))


def sospendi(bot_id: int | str, voce: dict[str, Any]) -> dict[str, Any]:
    """Registra la domanda aperta di un bot (una sola per bot).

    L'ultima vince: una domanda nuova vuol dire che quella di prima non
    aspetta piu' nessuno (chi la faceva ha gia' ricevuto il "mai" per
    scadenza), e tenerle tutte vorrebbe dire rispondere a quella
    sbagliata con il tocco giusto.
    """
    voce = dict(voce or {})
    voce.setdefault("token", _token())
    voce["scade"] = time.time() + SCADENZA_SOSPESO
    with _LOCK:
        SOSPESI[int(bot_id)] = voce
    return voce


def sospeso(bot_id: int | str) -> dict[str, Any] | None:
    """La domanda aperta adesso, o None. Una scaduta non e' aperta."""
    with _LOCK:
        voce = SOSPESI.get(int(bot_id))
        if voce is None:
            return None
        if time.time() > float(voce.get("scade") or 0):
            SOSPESI.pop(int(bot_id), None)
            return None
        return dict(voce)


def chiudi(bot_id: int | str, token: str = "") -> dict[str, Any] | None:
    """Chiude la domanda aperta, se il token e' quello giusto.

    Con `token` vuoto chiude comunque: e' il caso della risposta scritta,
    che arriva nella stessa chat e nello stesso momento, senza un
    pulsante da cui copiare il token.
    """
    with _LOCK:
        voce = SOSPESI.get(int(bot_id))
        if voce is None:
            return None
        if time.time() > float(voce.get("scade") or 0):
            SOSPESI.pop(int(bot_id), None)
            return None
        if token and not secrets.compare_digest(str(voce.get("token") or ""),
                                                token):
            return None
        SOSPESI.pop(int(bot_id), None)
        return dict(voce)


def pulisci_sospesi(bot_id: int | str) -> None:
    """Dimentica la domanda aperta di un bot.

    Si chiama a fine turno: una domanda che nessuno ha raccolto non deve
    restare in piedi, o il primo messaggio del turno dopo verrebbe letto
    come la risposta a una domanda di ieri.
    """
    with _LOCK:
        SOSPESI.pop(int(bot_id), None)


SCELTE_PERMESSO = {
    "u": ("una_volta", "concesso una volta"),
    "s": ("sessione", "concesso per questa sessione"),
    "w": ("sempre", "concesso per sempre"),
    "m": ("mai", "negato"),
}


def modulo_permesso(dati: dict[str, Any], token: str) -> tuple[str, list]:
    """Il testo e i pulsanti di una richiesta di permesso.

    Quattro scelte, le stesse della finestra: qui pero' non c'e' spazio
    per spiegare la differenza, quindi le etichette la dicono da sole.
    """
    percorso = str(dati.get("percorso") or "?")
    azione = str(dati.get("azione") or "toccare")
    righe = ["Serve un permesso: " + azione, percorso]
    dettaglio = str(dati.get("dettaglio") or "").strip()
    if dettaglio:
        righe.append(dettaglio[:300])
    motivo = str(dati.get("motivo") or "").strip()
    if motivo:
        righe.append("(" + motivo + ")")
    righe.append("Senza risposta la richiesta scade dopo cinque minuti, "
                 "e vale come un no.")
    tastiera = [
        [{"testo": "Una volta", "dati": f"d:u:{token}"},
         {"testo": "Per la sessione", "dati": f"d:s:{token}"}],
        [{"testo": "Sempre", "dati": f"d:w:{token}"},
         {"testo": "Mai", "dati": f"d:m:{token}"}],
    ]
    return "\n".join(righe), tastiera


def modulo_domanda(dati: dict[str, Any], token: str) -> tuple[str, list]:
    """Il testo e i pulsanti di una domanda (o di un piano da approvare).

    Le opzioni sono suggerimenti, non un elenco chiuso: la risposta si
    puo' sempre scrivere, e per un piano il feedback libero e' spesso la
    cosa che conta di piu'.
    """
    testo = str(dati.get("testo") or "").strip()
    opzioni = [str(o) for o in (dati.get("opzioni") or []) if str(o).strip()]
    tastiera = [[{"testo": o[:64], "dati": f"r:{i}:{token}"}]
                for i, o in enumerate(opzioni[:6])]
    coda = ("Tocca una risposta, oppure scrivila qui."
            if opzioni else "Rispondi scrivendo qui.")
    return testo + "\n\n" + coda, tastiera


# ===================================================================
#  L'API
# ===================================================================
Trasporto = Callable[[str, dict[str, Any], float], dict[str, Any]]
# Il caricamento di un file e' multipart: non e' un'altra chiamata JSON,
# quindi ha un trasporto suo (i test lo sostituiscono senza aprire socket).
Carica = Callable[[str, dict[str, Any], str, tuple[str, bytes, str], float],
                  dict[str, Any]]


def _risposta(grezzo: bytes) -> dict[str, Any]:
    """Il JSON di Telegram, o l'errore che Telegram ha spiegato."""
    try:
        dati_risposta = json.loads(grezzo.decode("utf-8", "replace"))
    except ValueError as e:
        raise ErroreTelegram(f"risposta illeggibile da Telegram: {e}") from e
    if not isinstance(dati_risposta, dict) or not dati_risposta.get("ok"):
        descrizione = ""
        if isinstance(dati_risposta, dict):
            descrizione = str(dati_risposta.get("description") or "")
        raise ErroreTelegram(descrizione or "richiesta rifiutata da Telegram",
                             (dati_risposta or {}).get("error_code")
                             if isinstance(dati_risposta, dict) else None)
    return dati_risposta


def _apri(req: urllib.request.Request, secondi: float) -> bytes:
    try:
        with urllib.request.urlopen(req, timeout=secondi) as risposta:
            return risposta.read()
    except urllib.error.HTTPError as e:
        # Telegram sbaglia con un JSON che spiega l'errore: buttarlo
        # via lascerebbe solo "400 Bad Request", che non dice niente.
        return e.read() or b"{}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroreTelegram(f"rete non raggiungibile: {e}") from e


def _urllib(url: str, dati: dict[str, Any], secondi: float) -> dict[str, Any]:
    corpo = urllib.parse.urlencode(dati).encode("utf-8")
    req = urllib.request.Request(
        url, data=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return _risposta(_apri(req, secondi))


def _multipart(url: str, campi: dict[str, Any], campo_file: str,
               allegato: tuple[str, bytes, str],
               secondi: float) -> dict[str, Any]:
    """Una richiesta multipart/form-data, scritta a mano.

    Non c'e' una libreria per questo e non serve: il confine, le parti,
    il file. `requests` sarebbe una dipendenza in piu' per dieci righe.
    """
    nome, dati, tipo = allegato
    confine = "----orchestra" + secrets.token_hex(12)
    pezzi: list[bytes] = []
    for chiave, valore in campi.items():
        pezzi.append((f"--{confine}\r\n"
                      f"Content-Disposition: form-data; name=\"{chiave}\"\r\n\r\n"
                      f"{valore}\r\n").encode("utf-8"))
    pezzi.append((f"--{confine}\r\n"
                  f"Content-Disposition: form-data; name=\"{campo_file}\"; "
                  f"filename=\"{nome}\"\r\n"
                  f"Content-Type: {tipo}\r\n\r\n").encode("utf-8"))
    pezzi.append(dati)
    pezzi.append(f"\r\n--{confine}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        url, data=b"".join(pezzi),
        headers={"Content-Type": f"multipart/form-data; boundary={confine}"})
    return _risposta(_apri(req, max(secondi, 120)))


class Api:
    """Le quattro chiamate che servono, e nient'altro.

    Il trasporto e' un parametro perche' i test non devono parlare con
    Telegram: una funzione che prende (url, dati, secondi) e torna il
    JSON decodificato basta a provare tutta la logica.
    """

    def __init__(self, token: str, *, trasporto: Trasporto | None = None,
                 base: str = BASE,
                 scarica: Callable[[str, int], bytes] | None = None,
                 carica: Carica | None = None) -> None:
        self.token = (token or "").strip()
        self.base = base.rstrip("/")
        self._trasporto = trasporto or _urllib
        # Il download di un file non e' una chiamata JSON: un URL con il
        # token dentro e dei byte come risposta. Trasporto a parte, per
        # la stessa ragione dell'altro: i test non escono dalla macchina.
        self._scarica = scarica or self._scarica_urllib
        # L'invio di un file e' multipart, quindi un terzo trasporto.
        self._carica = carica or _multipart

    def chiama(self, metodo: str, secondi: float = 30,
               **campi: Any) -> dict[str, Any]:
        if not self.token:
            raise ErroreTelegram("manca il token del bot")
        url = f"{self.base}/bot{self.token}/{metodo}"
        return self._trasporto(url, campi, secondi)

    def _scarica_urllib(self, percorso: str, massimo: int) -> bytes:
        url = f"{self.base}/file/bot{self.token}/{percorso.lstrip('/')}"
        try:
            with urllib.request.urlopen(url, timeout=90) as risposta:
                dati = risposta.read(max(1, int(massimo)) + 1)
        except urllib.error.HTTPError as e:
            raise ErroreTelegram(f"download rifiutato da Telegram ({e.code})",
                                 e.code) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErroreTelegram(f"rete non raggiungibile: {e}") from e
        if len(dati) > massimo:
            raise ErroreTelegram("il file supera il limite che Telegram concede")
        return dati

    def get_file(self, file_id: str, secondi: float = 20) -> dict[str, Any]:
        """Dove sta il file, secondo Telegram. Poi si scarica a parte."""
        if not (file_id or "").strip():
            raise ErroreTelegram("manca l'identificativo del file")
        risultato = self.chiama("getFile", secondi=secondi,
                                file_id=file_id.strip())
        file_ = risultato.get("result") or {}
        return {"file_path": file_.get("file_path") or "",
                "dimensione": int(file_.get("file_size") or 0)}

    def scarica(self, percorso: str,
                massimo: int = MASSIMO_FILE) -> bytes:
        return self._scarica(percorso, int(massimo))

    def edit_message(self, chat_id: str | int, message_id: int,
                     testo: str, secondi: float = 15,
                     markup: str | None = None,
                     parse_mode: str | None = None) -> bool:
        """Riscrive un messaggio gia' mandato. False se non e' cambiato.

        "message is not modified" non e' un errore: arriva quando due
        aggiornamenti di stato si somigliano, ed e' esattamente il caso
        che il limite di frequenza produce.

        `markup` e' il JSON di `tastiera()`: passarlo cambia i pulsanti
        insieme al testo, e passarne uno vuoto li toglie. E' l'unico
        modo di fare un menu che non lascia dietro di se' messaggi
        vecchi con dentro bottoni che non funzionano piu'.
        """
        campi: dict[str, Any] = {
            "chat_id": str(chat_id), "message_id": int(message_id),
            "text": testo, "disable_web_page_preview": "true",
        }
        if markup is not None:
            campi["reply_markup"] = markup
        if parse_mode:
            campi["parse_mode"] = parse_mode
        try:
            self.chiama("editMessageText", secondi=secondi, **campi)
        except ErroreTelegram as e:
            if "not modified" in str(e).lower():
                return False
            raise
        return True

    def delete_message(self, chat_id: str | int, message_id: int,
                       secondi: float = 15) -> bool:
        """Toglie un messaggio. Un messaggio gia' sparito non e' un guasto."""
        try:
            self.chiama("deleteMessage", secondi=secondi,
                        chat_id=str(chat_id), message_id=int(message_id))
        except ErroreTelegram as e:
            if "not found" in str(e).lower():
                return False
            raise
        return True

    def set_my_commands(self, comandi: tuple[tuple[str, str], ...] | None = None,
                        secondi: float = 20) -> bool:
        """Scrive il menu degli slash sul bot.

        `commands` e' una lista JSON, non un campo ripetuto: Telegram
        vuole nome e descrizione insieme, e una stringa JSON e' l'unico
        modo di mandarli in una chiamata sola.
        """
        voci = list(COMANDI_MENU if comandi is None else comandi)
        risultato = self.chiama(
            "setMyCommands", secondi=secondi,
            commands=json.dumps([{"command": c, "description": d}
                                 for c, d in voci], ensure_ascii=False))
        return bool(risultato.get("ok"))

    def get_me(self, secondi: float = 15) -> dict[str, Any]:
        risultato = self.chiama("getMe", secondi=secondi)
        bot = risultato.get("result") or {}
        return {
            "id": bot.get("id"),
            "username": bot.get("username") or "",
            "nome": bot.get("first_name") or "",
        }

    def get_updates(self, offset: int | None = None,
                    secondi: int = ATTESA_POLLING) -> list[dict[str, Any]]:
        campi: dict[str, Any] = {
            "timeout": max(0, int(secondi)),
            # `callback_query` sono i tocchi sui pulsanti dei moduli:
            # senza dichiararlo Telegram non li consegna mai, e i bottoni
            # restano decorativi.
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        if offset is not None:
            campi["offset"] = int(offset)
        # La rete deve aspettare piu' del polling: se il timeout del
        # socket fosse uguale, ogni giro lungo morirebbe come "rete non
        # raggiungibile" mentre Telegram sta solo aspettando un messaggio.
        risultato = self.chiama("getUpdates", secondi=secondi + 15, **campi)
        aggiornamenti = risultato.get("result") or []
        return [a for a in aggiornamenti if isinstance(a, dict)]

    def send_message(self, chat_id: str | int, testo: str,
                     secondi: float = 20,
                     markup: str | None = None,
                     parse_mode: str | None = None) -> dict[str, Any]:
        campi: dict[str, Any] = {
            "chat_id": str(chat_id), "text": testo,
            "disable_web_page_preview": "true",
        }
        if markup is not None:
            campi["reply_markup"] = markup
        if parse_mode:
            campi["parse_mode"] = parse_mode
        return self.chiama("sendMessage", secondi=secondi, **campi)

    def send_file(self, chat_id: str | int, nome: str, dati: bytes,
                  *, didascalia: str = "", foto: bool = False,
                  secondi: float = 180) -> dict[str, Any]:
        """Allega un file alla chat.

        `foto=True` usa sendPhoto, che mostra l'immagine dentro la chat;
        per tutto il resto sendDocument, che e' l'unico modo di mandare un
        PDF, un foglio o un'immagine che Telegram non accetta come foto
        (un gif, un webp, un svg).
        """
        if not (nome or "").strip():
            nome = "file"
        metodo = "sendPhoto" if foto else "sendDocument"
        campo = "photo" if foto else "document"
        campi: dict[str, Any] = {"chat_id": str(chat_id)}
        if didascalia:
            # Il tetto di Telegram per una didascalia: oltre, rifiuta il
            # file intero, e perdere l'allegato per una frase e' assurdo.
            campi["caption"] = didascalia.strip()[:1024]
        url = f"{self.base}/bot{self.token}/{metodo}"
        return self._carica(url, campi, campo,
                            (nome, dati, _tipo_mime(nome)), secondi)

    def answer_callback(self, callback_id: str, testo: str = "") -> bool:
        """Chiude la rotellina di un pulsante premuto.

        Telegram la fa girare finche' il bot non risponde, e un pulsante
        che gira per sempre sembra rotto. Quindi si risponde sempre,
        anche quando non c'e' niente da dire; e se la risposta non parte
        non e' un guasto — il modulo sotto e' gia' cambiato.
        """
        if not (callback_id or "").strip():
            return False
        campi: dict[str, Any] = {"callback_query_id": callback_id.strip()}
        if testo:
            campi["text"] = testo[:200]
        try:
            self.chiama("answerCallbackQuery", secondi=10, **campi)
        except ErroreTelegram:
            return False
        return True

    def scrive(self, chat_id: str | int) -> None:
        """L'indicatore "sta scrivendo". Non deve mai far fallire niente."""
        try:
            self.chiama("sendChatAction", secondi=10,
                        chat_id=str(chat_id), action="typing")
        except ErroreTelegram:
            pass

    def senza_webhook(self) -> None:
        """Toglie un webhook rimasto acceso.

        Con un webhook attivo `getUpdates` risponde 409 e il ponte non
        parte: chi ha provato un webhook una volta e poi e' tornato al
        polling non deve restare bloccato senza capire perche'.
        """
        try:
            self.chiama("deleteWebhook", secondi=15,
                        drop_pending_updates="false")
        except ErroreTelegram:
            pass


def tastiera(righe: list[list[dict[str, Any]]] | None) -> str:
    """Il JSON di una tastiera a pulsanti, o una vuota per toglierla.

    I pulsanti portano `callback_data`, non un link: un tocco torna al
    ponte come aggiornamento, e il ponte decide cosa fare. E' l'unica
    forma che non fa uscire dalla chat e non chiede all'utente di
    ricordarsi un nome di modello a memoria.

    Il limite di Telegram e' 64 byte per `callback_data`: qui passano
    un identificativo di servizio e un numero, mai un nome di modello.
    """
    if not righe:
        return json.dumps({"inline_keyboard": []})
    costruite = []
    for riga in righe:
        voci = []
        for voce in riga or []:
            dati = str(voce.get("dati", ""))
            if not dati:
                continue
            voci.append({"text": str(voce.get("testo", ""))[:64],
                         "callback_data": dati[:64]})
        if voci:
            costruite.append(voci)
    if not costruite:
        return json.dumps({"inline_keyboard": []})
    return json.dumps({"inline_keyboard": costruite})


# Le estensioni che vale la pena allegare a un messaggio: documenti,
# immagini e qualche archivio. Il codice no: un turno che scrive venti
# file .py non deve riempire la chat di allegati che dal telefono nessuno
# apre, e che sono gia' nella cartella che l'utente vede.
ALLEGABILI = (
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".odt", ".ods",
    ".csv", ".md", ".txt", ".rtf", ".png", ".jpg", ".jpeg", ".webp",
    ".gif", ".svg", ".mp3", ".ogg", ".wav", ".mp4", ".zip",
)
# Cartelle in cui non si guarda: sono lo stato dell'app o le dipendenze,
# non il lavoro del turno.
ESCLUSE = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".idea", ".vscode", "sessions", "tmp", "temp", "dist", "build",
    ".pytest_cache", ".mypy_cache",
}


def file_del_turno(root: str, inizio: float,
                   massimo: int = MASSIMO_FILE_PER_TURNO) -> list[dict[str, Any]]:
    """I file prodotti dal turno che vale la pena allegare.

    Non si sa per certo cosa abbia "prodotto": un PDF puo' nascere da uno
    script lanciato con la shell, e nessun tool dice "ho creato questo".
    La cosa onesta e' guardare cosa e' stato scritto nella cartella di
    lavoro da quando il turno e' partito, e filtrare per estensione — un
    file toccato ma non nostro costa un allegato di troppo, un PDF mai
    mandato costa una risposta che sembra incompleta.

    Il tetto sul numero di file visitati evita che un progetto enorme
    faccia pagare a ogni turno una scansione intera.
    """
    base = (root or "").strip()
    if not base or not os.path.isdir(base):
        return []
    soglia = float(inizio or 0) - 2.0
    trovati: list[tuple[float, str]] = []
    visitati = 0
    for cartella, sottocartelle, nomi in os.walk(base):
        sottocartelle[:] = [d for d in sottocartelle
                           if d.lower() not in ESCLUSE
                           and not d.startswith(".")]
        for nome in nomi:
            visitati += 1
            if visitati > 20000:
                break
            if os.path.splitext(nome)[1].lower() not in ALLEGABILI:
                continue
            # I file di stato di Orchestra (memory.md, il budget, gli
            # obiettivi) vengono riscritti ogni volta che il turno li legge:
            # allegarli vuol dire mandare in chat cose che nessuno ha
            # chiesto, e che non sono il lavoro del turno. Sono una lista
            # chiusa, in `dati.FILE_STATO`: non si indovina dal nome.
            if nome.lower() in FILE_STATO:
                continue
            percorso = os.path.join(cartella, nome)
            try:
                stato = os.stat(percorso)
            except OSError:
                continue
            if stato.st_size <= 0 or stato.st_size > MASSIMO_INVIO:
                continue
            if stato.st_mtime < soglia:
                continue
            trovati.append((stato.st_mtime, percorso))
        if visitati > 20000:
            break
    trovati.sort(reverse=True)
    return [{"percorso": p, "nome": os.path.basename(p)}
            for _m, p in trovati[:max(0, int(massimo))]]


def dividi(testo: str, limite: int = MAX_TESTO) -> list[str]:
    """Spezza un testo lungo nei pezzi che Telegram accetta.

    Si prova a tagliare dove il testo respira (riga vuota, a capo,
    spazio) e solo alla fine a meta' parola: un messaggio tagliato in
    mezzo a una frase e' meglio di uno rifiutato, ma solo come ultima
    risorsa.
    """
    resto = (testo or "").strip()
    if not resto:
        return []
    pezzi: list[str] = []
    while len(resto) > limite:
        finestra = resto[:limite]
        taglio = -1
        for separatore in ("\n\n", "\n", " "):
            posizione = finestra.rfind(separatore)
            if posizione > limite // 2:
                taglio = posizione
                break
        if taglio <= 0:
            taglio = limite
        pezzi.append(resto[:taglio].rstrip())
        resto = resto[taglio:].lstrip()
    if resto:
        pezzi.append(resto)
    return pezzi


# ---- markdown -> HTML di Telegram ------------------------------------
#
# Il modello scrive in markdown: `**grassetto**`, `### titolo`, i blocchi
# di codice. Telegram non lo interpreta — senza `parse_mode` quei segni
# arrivano al telefono come caratteri, ed e' quello che si vedeva in chat
# (`### 1. Controlla`, `**Ctrl + Maiusc + Esc**`).
#
# Si converte in HTML e non in MarkdownV2 di proposito: MarkdownV2
# pretende che si escapi una dozzina di caratteri, e basta un underscore
# in un nome di file per farsi rifiutare l'intero messaggio. L'HTML ha una
# sola regola (`&`, `<`, `>`) e la conversione e' verificabile.
_MD_FENCE = re.compile(r"```([A-Za-z0-9_+.-]*)\n?(.*?)```", re.S)
_MD_TITOLO = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_MD_PUNTO = re.compile(r"^(\s*)[-*+]\s+")
_MD_SEPARATORE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_MD_CODICE = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_MD_GRASSETTO = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_BARRATO = re.compile(r"~~(.+?)~~", re.S)
_MD_SOTTOLINEATO = re.compile(r"(?<![0-9A-Za-z])__(.+?)__(?![0-9A-Za-z])", re.S)
_MD_CORSIVO = re.compile(r"(?<![*0-9A-Za-z])\*([^*\n]+)\*(?![*0-9A-Za-z])")
_MD_ENFASI = re.compile(r"(?<![0-9A-Za-z])_([^_\n]+)_(?![0-9A-Za-z])")


def _scappa(testo: str) -> str:
    """Le tre cose che l'HTML di Telegram legge come codice."""
    return (testo.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _in_linea(testo: str) -> str:
    """Le marcature di una riga, con i pezzi di codice al riparo.

    Il codice si sostituisce PRIMA con un segnaposto: dentro `a * b` un
    asterisco non e' corsivo, e convertirne uno solo lascerebbe l'altro
    in giro a rovinare il resto della riga.
    """
    codici: list[str] = []

    def _codice(m):
        codici.append("<code>" + m.group(1) + "</code>")
        return f"\x00{len(codici) - 1}\x00"

    testo = _MD_CODICE.sub(_codice, testo)
    testo = _MD_LINK.sub(
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', testo)
    testo = _MD_GRASSETTO.sub(r"<b>\1</b>", testo)
    testo = _MD_BARRATO.sub(r"<s>\1</s>", testo)
    testo = _MD_SOTTOLINEATO.sub(r"<b>\1</b>", testo)
    testo = _MD_CORSIVO.sub(r"<i>\1</i>", testo)
    testo = _MD_ENFASI.sub(r"<i>\1</i>", testo)
    for n, pezzo in enumerate(codici):
        testo = testo.replace(f"\x00{n}\x00", pezzo)
    return testo


def _righe(blocco: str) -> str:
    """Un pezzo di testo normale: prima le righe, poi le marcature."""
    fuori = []
    for riga in (blocco or "").replace("```", "").split("\n"):
        riga = _scappa(riga)
        titolo = _MD_TITOLO.match(riga)
        if titolo:
            fuori.append("<b>" + _in_linea(titolo.group(1)) + "</b>")
            continue
        if _MD_SEPARATORE.match(riga):
            fuori.append("—————")
            continue
        fuori.append(_in_linea(_MD_PUNTO.sub(r"\1• ", riga)))
    return "\n".join(fuori)


def per_telegram(testo: str) -> str:
    """Il testo da mandare, in HTML di Telegram.

    I blocchi di codice si trattano a parte: dentro non si converte
    niente, altrimenti un `**` in un sorgente diventerebbe grassetto e il
    codice arriverebbe diverso da com'e' scritto.
    """
    parti: list[str] = []
    ultimo = 0
    for trovato in _MD_FENCE.finditer(testo or ""):
        parti.append(_righe((testo or "")[ultimo:trovato.start()]))
        lingua, corpo = trovato.group(1), trovato.group(2)
        # La prima riga di un blocco senza lingua dichiarata e' spesso il
        # nome della lingua (`python`): dentro <pre> e' solo rumore.
        if not lingua and "\n" in corpo:
            prima, resto = corpo.split("\n", 1)
            if re.fullmatch(r"[A-Za-z0-9_+.-]{1,20}", prima.strip()):
                corpo = resto
        parti.append("<pre>" + _scappa(corpo.strip("\n")) + "</pre>")
        ultimo = trovato.end()
    parti.append(_righe((testo or "")[ultimo:]))
    return "".join(parti)


def semplice(testo: str) -> str:
    """Il testo senza marcature: l'ultima risorsa se l'HTML e' rifiutato.

    Un tag che Telegram non conosce fa 400 e il messaggio non parte: una
    risposta brutta ma leggibile e' meglio di una risposta che non arriva,
    perche' il lavoro e' stato fatto lo stesso.
    """
    fuori = []
    for riga in (testo or "").split("\n"):
        if _MD_SEPARATORE.match(riga):
            fuori.append("—————")
            continue
        riga = _MD_TITOLO.sub(r"\1", riga)
        riga = _MD_PUNTO.sub(r"\1• ", riga)
        riga = riga.replace("**", "").replace("~~", "").replace("`", "")
        fuori.append(riga)
    return "\n".join(fuori)


# ===================================================================
#  Il ponte
# ===================================================================

# Quanto si aspetta prima di ritentare un invio che Telegram ha
# rifiutato per un motivo temporaneo. Corto di proposito: una risposta in
# ritardo e' meglio di una persa, ma non deve diventare un minuto di
# attesa davanti a un telefono.
RITENTA_ATTESA = 1.0


def _ritentabile(e: ErroreTelegram) -> bool:
    """Un errore che passa da solo: rete, limite di frequenza, 5xx.

    Un 400 "chat not found" non passa ritentando: ritentarlo tre volte
    allunga solo la perdita e lascia credere che sia un problema di rete.
    """
    if e.codice is None:
        return True
    return int(e.codice) == 429 or 500 <= int(e.codice) < 600


class Ponte:
    """Un bot di Orchestra, il suo token, e la chat che gli scrive.

    Tre cose che questo modulo non sa fare, e che arrivano da fuori:

    `turno(testo, allegati, avanzamento)` esegue la richiesta e torna la
    risposta. `avanzamento(testo, azione=None)` e' una funzione che il
    turno chiama quando ha qualcosa da raccontare: `testo` e' la riga di
    sintesi ("sto leggendo i test, giro 2"), `azione` e' un passo
    concreto appena partito ("bash · pytest"). Il ponte manda le azioni
    come messaggi nuovi, che restano, e tiene il testo in un messaggio
    solo che si riscrive e sparisce alla fine.

    `comandi(nome, argomento)` fa steer, stop, nuova, modello, stato.
    Sta fuori perche' quelle cose riguardano la sessione, non la chat:
    qui si sa chi ha scritto, la' cosa si puo' fare.

    Il turno gira in un thread suo. Non e' un dettaglio: se il ponte
    restasse fermo dentro il turno, non farebbe `getUpdates`, e i
    messaggi che arrivano mentre l'agente lavora — cioe' proprio le
    guide e gli stop — resterebbero su Telegram fino alla fine.
    """

    def __init__(self, bot_id: int, nome: str, api: Api, turno: Callable[..., Any],
                 *, comandi: Callable[[str, str], str | dict[str, Any]]
                 | None = None,
                 tocco: Callable[[str], str | dict[str, Any] | None] | None = None,
                 risposta: Callable[[str], str | None] | None = None,
                 attesa: int = ATTESA_POLLING,
                 log: Callable[[str], None] | None = None) -> None:
        self.bot_id = int(bot_id)
        self.nome = (nome or "").strip() or f"bot {bot_id}"
        self.api = api
        self.turno = turno
        self.comandi = comandi
        # Un pulsante premuto, e una risposta scritta mentre una domanda
        # e' aperta. Stanno fuori perche' chi risponde deve sapere cosa
        # c'e' in attesa (permessi, domande): il ponte sa solo che
        # qualcosa aspetta e che la risposta arriva dall'altra parte.
        self.tocco = tocco
        self.risposta = risposta
        self.attesa = max(0, int(attesa))
        self._log = log or (lambda _m: None)
        self._fermo = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None
        self._primo = True
        self._turno_thread: threading.Thread | None = None
        self._stato_progresso: dict[str, Any] | None = None
        # Gli album in raccolta, per `media_group_id`: chat, didascalia,
        # allegati e il timer che li chiude.
        self._album: dict[str, dict[str, Any]] = {}
        self._album_lock = threading.Lock()
        self.fatti = 0
        self.ultimo_turno = 0.0

    # --- ciclo -----------------------------------------------------
    def avvia(self) -> "Ponte":
        if self._thread and self._thread.is_alive():
            return self
        self._fermo.clear()
        self._thread = threading.Thread(target=self.gira, daemon=True,
                                        name=f"telegram-{self.nome}")
        self._thread.start()
        return self

    def ferma(self, secondi: float = 3.0) -> None:
        self._fermo.set()
        # Un album a meta' non deve partire dopo la fermata: il timer
        # sopravvive alla chat, e farebbe un turno su un ponte chiuso.
        with self._album_lock:
            for voce in self._album.values():
                timer = voce.get("timer")
                if timer is not None:
                    timer.cancel()
            self._album.clear()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=secondi)

    @property
    def attivo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def occupato(self) -> bool:
        """C'e' un turno in corso adesso."""
        t = self._turno_thread
        return bool(t and t.is_alive())

    def aspetta(self, secondi: float = 10.0) -> bool:
        """Aspetta la fine del turno in corso.

        Serve ai test, che fanno avanzare il ponte a mano: un turno che
        si prova senza poterlo aspettare si verifica a colpi di `sleep`,
        e un test che dorme e' un test che prima o poi fallisce da solo.
        """
        t = self._turno_thread
        if t is None:
            return True
        t.join(timeout=secondi)
        return not t.is_alive()

    def _allinea_comandi(self) -> None:
        """Riallinea il menu degli slash a questo bot.

        Non e' estetica: il menu vive sul bot, non nell'applicazione. Un
        bot usato prima con un'altra app si porta dietro i suoi comandi, e
        chi preme "/" li prova convinto che siano di Orchestra. Una
        chiamata all'avvio e una quando una chat si collega bastano a non
        lasciarlo indietro.
        """
        try:
            self.api.set_my_commands()
        except Exception as e:  # noqa: BLE001 - il menu non ferma il ponte
            self._log(f"telegram {self.nome}: menu comandi non aggiornato: "
                      f"{type(e).__name__}: {e}")

    def gira(self) -> None:
        try:
            self.api.senza_webhook()
        except ErroreTelegram:
            pass
        while not self._fermo.is_set():
            try:
                quanti = self.passo()
            except ErroreTelegram as e:
                # 409 = un altro processo sta gia' facendo polling con
                # questo token. Riprovare subito peggiora la cosa.
                pausa = INTERVALLO_ERRORE * (3 if e.codice == 409 else 1)
                self._log(f"telegram {self.nome}: {e}; riprovo fra "
                          f"{int(pausa)}s")
                self._fermo.wait(pausa)
                continue
            except Exception as e:  # noqa: BLE001
                self._log(f"telegram {self.nome}: {type(e).__name__}: {e}")
                self._fermo.wait(INTERVALLO_ERRORE)
                continue
            if not quanti:
                self._fermo.wait(0.3)

    def passo(self) -> int:
        """Un giro di `getUpdates`. Torna quanti messaggi ha gestito.

        E' pubblico perche' i test lo chiamano a mano: un ciclo che si
        puo' far avanzare di un passo si prova senza thread e senza
        attese vere.
        """
        if self._primo:
            self._allinea_comandi()
            self._primo = False
            # L'arretrato non si rigioca: si prende l'ultimo
            # aggiornamento e si riparte da dopo.
            ultimi = self.api.get_updates(-1, secondi=0)
            if ultimi:
                self._offset = int(ultimi[-1].get("update_id", 0)) + 1
            return 0

        aggiornamenti = self.api.get_updates(self._offset, secondi=self.attesa)
        gestiti = 0
        for aggiornamento in aggiornamenti:
            try:
                self._offset = int(aggiornamento.get("update_id", 0)) + 1
            except (TypeError, ValueError):
                continue
            tocco = aggiornamento.get("callback_query")
            if isinstance(tocco, dict):
                self._pulsante(tocco)
                gestiti += 1
                self.fatti += 1
                continue
            messaggio = aggiornamento.get("message")
            if not isinstance(messaggio, dict):
                continue
            self._gestisci(messaggio)
            gestiti += 1
            self.fatti += 1
        return gestiti

    # --- messaggi --------------------------------------------------
    def _invia_testo(self, chat_id: str, testo: str,
                     markup: str | None = None) -> dict[str, Any]:
        """Manda un pezzo formattato, e ripiega se Telegram lo rifiuta.

        Un tag sbagliato fa 400 e il messaggio non parte: in quel caso
        parte lo stesso testo senza formattazione. Meglio brutto che perso.
        """
        try:
            return self.api.send_message(chat_id, per_telegram(testo),
                                         markup=markup, parse_mode="HTML")
        except ErroreTelegram as e:
            if e.codice != 400:
                raise
            return self.api.send_message(chat_id, semplice(testo),
                                         markup=markup)

    def _modifica_testo(self, chat_id: str, message_id: int, testo: str,
                        markup: str | None = None) -> bool:
        """Come `_invia_testo`, per un messaggio che si riscrive."""
        try:
            return self.api.edit_message(chat_id, message_id,
                                         per_telegram(testo), markup=markup,
                                         parse_mode="HTML")
        except ErroreTelegram as e:
            if e.codice != 400:
                raise
            return self.api.edit_message(chat_id, message_id,
                                         semplice(testo), markup=markup)

    def _rispondi(self, chat_id: str, testo: str) -> None:
        """Manda la risposta a pezzi, e ritenta quando Telegram tentenna.

        Un 429 (troppe richieste) o un 5xx non sono "il messaggio non si
        manda": sono "adesso no". Senza ritentare, la risposta del turno
        andava persa con una riga nel log e niente in chat — ed e' il
        "poi non fa piu' niente" che si vede dal telefono, con il lavoro
        che pero' nella finestra era stato fatto.
        """
        for pezzo in dividi(testo):
            for tentativo in range(3):
                try:
                    self._invia_testo(chat_id, pezzo)
                    break
                except ErroreTelegram as e:
                    if not _ritentabile(e) or tentativo == 2:
                        self._log(f"telegram {self.nome}: risposta non "
                                  f"inviata: {e}")
                        return
                    time.sleep(RITENTA_ATTESA * (2 ** tentativo))

    def recapita(self, testo: str,
                 file: list[dict[str, Any]] | None = None) -> bool:
        """Manda una risposta che il turno ha prodotto DOPO l'attesa.

        La chat si rilegge adesso invece di tenerla da parte: se nel
        frattempo e' stata scollegata o sostituita, un messaggio alla
        vecchia sarebbe un messaggio a un numero sbagliato.
        """
        chat, _nome_chat = chat_di(self.bot_id)
        if not chat or not (testo or "").strip():
            return False
        self.api.scrive(chat)
        self._rispondi(chat, testo)
        if file:
            self._manda_file(chat, [f for f in file if isinstance(f, dict)])
        return True

    def _invia_modulo(self, chat_id: str, testo: str,
                      righe: list | None) -> int:
        """Manda un testo con i pulsanti attaccati all'ultimo pezzo.

        Torna l'id del messaggio coi pulsanti, 0 se non e' partito: e' il
        messaggio che poi si riscrive per dire com'e' finita.
        """
        pezzi = dividi(testo) or [""]
        ultimo_id = 0
        for i, pezzo in enumerate(pezzi):
            ultimo = i == len(pezzi) - 1
            try:
                inviato = self._invia_testo(
                    chat_id, pezzo, markup=tastiera(righe) if ultimo else None)
            except ErroreTelegram as e:
                self._log(f"telegram {self.nome}: modulo non inviato: {e}")
                return 0
            if ultimo:
                ultimo_id = int((inviato.get("result") or {}).get(
                    "message_id") or 0)
        return ultimo_id

    def _manda_modulo(self, chat_id: str, modulo: dict[str, Any]) -> None:
        """Un messaggio con i pulsanti: e' un modulo, non una risposta."""
        self._invia_modulo(chat_id, str(modulo.get("testo") or ""),
                           modulo.get("tastiera"))

    def chiedi_in_chat(self, tipo: str, dati: dict[str, Any]) -> bool:
        """Porta in chat un permesso o una domanda, con i suoi pulsanti.

        La chiama chi emette l'evento (la webapp), non il ciclo dei
        messaggi: cosi' la domanda arriva anche quando il turno e' stato
        avviato dalla finestra e non da qui — che e' proprio il caso in
        cui si e' lontani dal computer.

        False se non c'e' una chat a cui chiedere: in quel caso la
        domanda resta nella finestra, come prima.
        """
        chat, _nome = chat_di(self.bot_id)
        if not chat:
            return False
        token = _token()
        if tipo == "permission_request":
            testo, righe = modulo_permesso(dati, token)
            voce: dict[str, Any] = {"tipo": "permesso"}
        elif tipo == "domanda_utente":
            testo, righe = modulo_domanda(dati, token)
            voce = {"tipo": "domanda",
                    "opzioni": [str(o) for o in (dati.get("opzioni") or [])]}
        else:
            return False
        voce["id"] = str(dati.get("id") or "")
        if not voce["id"]:
            return False
        voce["token"] = token
        voce["chat"] = chat
        messaggio = self._invia_modulo(chat, testo, righe)
        if not messaggio:
            return False
        voce["message_id"] = messaggio
        sospendi(self.bot_id, voce)
        return True

    def _pulsante(self, tocco: dict[str, Any]) -> None:
        """Un pulsante premuto: si riscrive quel messaggio, non se ne manda un altro.

        Il modulo vive in un messaggio solo. Rispondere con un messaggio
        nuovo a ogni tocco lascerebbe una pila di menu vecchi con dentro
        bottoni ormai scollegati dalla realta'.
        """
        dati = (tocco.get("data") or "").strip()
        messaggio = tocco.get("message") or {}
        chat = messaggio.get("chat") or {}
        chat_id = str(chat.get("id", "") or "")
        cb_id = str(tocco.get("id") or "")
        try:
            message_id = int(messaggio.get("message_id"))
        except (TypeError, ValueError):
            message_id = 0
        if not chat_id:
            return
        legata, _nome_chat = chat_di(self.bot_id)
        if not legata or legata != chat_id:
            self.api.answer_callback(cb_id,
                                     "Questa chat non e' collegata a Orchestra.")
            return
        if self.tocco is None and self.comandi is None:
            self.api.answer_callback(cb_id, "Modulo non disponibile.")
            return
        try:
            if self.tocco is not None:
                risposta = self.tocco(dati)
            else:
                risposta = self.comandi("modello", f"cb:{dati}")
        except Exception as e:  # noqa: BLE001
            risposta = (f"Errore nel modulo: {type(e).__name__}: {e}")
        self.api.answer_callback(cb_id)
        if isinstance(risposta, dict):
            testo = str(risposta.get("testo") or "")
            righe = risposta.get("tastiera")
        else:
            testo = str(risposta or "Fatto.")
            righe = None
        if not message_id:
            self._manda_modulo(chat_id, {"testo": testo, "tastiera": righe})
            return
        try:
            self._modifica_testo(chat_id, message_id,
                                 (testo or "Fatto.")[:MAX_TESTO],
                                 markup=tastiera(righe))
        except ErroreTelegram as e:
            self._log(f"telegram {self.nome}: modulo non aggiornato: {e}")

    def _gestisci(self, messaggio: dict[str, Any]) -> None:
        chat = messaggio.get("chat") or {}
        chat_id = str(chat.get("id", "") or "")
        if not chat_id:
            return
        testo = (messaggio.get("text") or "").strip()
        allegato = allegato_da(messaggio)
        chi = (chat.get("username") or chat.get("first_name")
               or chat.get("title") or chat_id)
        legata, _nome_chat = chat_di(self.bot_id)

        if testo.startswith("/"):
            comando, _, argomento = testo.partition(" ")
            comando = comando.split("@", 1)[0].lower()
            argomento = argomento.strip()
            if comando == "/start":
                self._start(chat_id, chi, argomento, legata)
                return
            if comando in ("/aiuto", "/guida", "/help", "/comandi"):
                self._rispondi(chat_id, GUIDA)
                return
            # Lo scollegamento si e' spostato: `/stop` adesso ferma il
            # turno, che e' la cosa che serve di piu' e che non si puo'
            # fare altrimenti dal telefono. Staccare la chat si fa
            # apposta, con un comando che lo dice.
            if comando == "/scollega":
                if legata and legata == chat_id:
                    dimentica_chat(self.bot_id)
                    self._rispondi(chat_id, "Scollegato. Da adesso non "
                                            "rispondo piu' qui.")
                else:
                    self._rispondi(chat_id, "Questa chat non e' collegata "
                                            "a nessun bot di Orchestra.")
                return
            if not legata or legata != chat_id:
                self._rispondi(chat_id, _invito_collegare())
                return
            self._comando(chat_id, comando, argomento)
            return

        if not legata or legata != chat_id:
            # Nessun turno, nessun tool, nessun costo: chi non ha il
            # codice riceve una spiegazione, non un agente.
            self._rispondi(chat_id, _invito_collegare())
            return

        if not testo and allegato is None:
            self._rispondi(chat_id, "Non c'e' niente da leggere in questo "
                                    "messaggio. Leggo testo, foto, "
                                    "documenti e vocali.")
            return

        # Prima di tutto il resto: c'e' una domanda aperta in questa chat?
        # Allora quello che si scrive e' la risposta, non un nuovo turno e
        # non una guida. Senza questo controllo il testo finirebbe nella
        # coda degli steer, l'agente continuerebbe ad aspettare, e dopo
        # cinque minuti la domanda scadrebbe avendo gia' la risposta in
        # mano — la peggiore delle combinazioni.
        atteso = sospeso(self.bot_id)
        if atteso:
            if testo:
                self._risposta_scritta(chat_id, testo, atteso)
                return
            self._rispondi(chat_id, "C'e' una domanda aperta qui sopra: "
                                    "rispondi a quella (un pulsante o una "
                                    "riga di testo) prima di mandarmi file.")
            return

        if self.occupato:
            # Un messaggio durante un turno e' una guida, non una nuova
            # richiesta: il turno e' gia' partito, e accodarne un altro
            # vorrebbe dire farlo leggere sulla domanda sbagliata.
            guida = testo or (allegato or {}).get("didascalia") or ""
            if not guida:
                self._rispondi(chat_id, "Sto ancora lavorando al messaggio "
                                        "prima: questo file mandamelo quando "
                                        "ho finito, o usa /stop.")
                return
            self._comando(chat_id, "steer", guida)
            return

        gruppo = str(messaggio.get("media_group_id") or "").strip()
        if gruppo and allegato is not None:
            # Un album arriva a pezzi e la richiesta e' il gruppo, non la
            # prima foto. Qui non parte nessun turno, quindi `occupato`
            # resta falso per tutti i pezzi e nessuno di loro viene
            # scambiato per una guida.
            self._raccogli_album(chat_id, gruppo, testo, allegato)
            return
        self._avvia_turno(chat_id, testo, [allegato] if allegato else [])

    def _comando(self, chat_id: str, comando: str, argomento: str) -> None:
        nome = comando.lstrip("/").lower()
        # La lista sta qui e non la' fuori: un comando che il ponte non
        # conosce e' un errore di battitura, e mandarlo al turno
        # vorrebbe dire spendere token per far leggere all'agente
        # "/pippo".
        if nome not in COMANDI_AGENTE:
            self._rispondi(chat_id, f"Comando /{nome} non riconosciuto. "
                                    "/aiuto per la lista.")
            return
        if self.comandi is None:
            if nome == "stato":
                self._rispondi(chat_id, f"Collegato a {self.nome}. "
                                        "Scrivi e ti rispondo.")
            else:
                self._rispondi(chat_id, f"Comando /{nome} non disponibile "
                                        "in questo ponte. /aiuto per la "
                                        "lista.")
            return
        try:
            risposta = self.comandi(nome, argomento)
        except Exception as e:  # noqa: BLE001
            risposta = f"Errore nel comando /{nome}: {type(e).__name__}: {e}"
        if isinstance(risposta, dict):
            self._manda_modulo(chat_id, risposta)
            return
        self._rispondi(chat_id, risposta or "Fatto.")

    def _start(self, chat_id: str, chi: str, argomento: str,
               legata: str) -> None:
        if legata and legata == chat_id:
            self._rispondi(chat_id, f"Sei gia' collegato a {self.nome}. "
                                    "Scrivi e ti rispondo, /aiuto per i "
                                    "comandi.")
            return
        if argomento and codice_valido(self.bot_id, argomento):
            imposta_chat(self.bot_id, chat_id, chi)
            self._allinea_comandi()
            self._rispondi(chat_id,
                           f"Collegato a {self.nome}.\n\n"
                           "Quello che scrivi qui arriva all'agente, con i "
                           "suoi tool e i suoi permessi. Mentre lavora "
                           "puoi guidarlo scrivendo, e fermarlo con /stop. "
                           "/aiuto per i comandi, /scollega per staccare.")
            return
        # Codice assente, scaduto o sbagliato: si dice cosa fare, non se
        # esiste un codice.
        self._rispondi(chat_id,
                       "Per collegare questa chat a Orchestra serve il "
                       "codice che compare nel pannello Bot, sotto "
                       "Telegram. Inquadra il QR da li', oppure mandalo "
                       "qui come /start <codice>. Il codice scade dopo "
                       "dieci minuti.")

    # --- album -----------------------------------------------------
    def _raccogli_album(self, chat_id: str, gruppo: str, testo: str,
                        allegato: dict[str, Any]) -> None:
        """Tiene da parte le foto di un album, e parte quando sono finite.

        Il timer si riarma a ogni pezzo: a decidere il momento e' l'ultimo
        che arriva, non il primo. La didascalia la porta uno solo dei
        messaggi del gruppo (Telegram non la ripete), quindi si tiene
        l'ultima non vuota che si vede.
        """
        with self._album_lock:
            voce = self._album.get(gruppo)
            if voce is None:
                voce = {"chat": chat_id, "testo": "", "allegati": [],
                        "timer": None, "visto": 0.0}
                self._album[gruppo] = voce
            if (testo or "").strip():
                voce["testo"] = testo.strip()
            voce["allegati"].append(allegato)
            voce["visto"] = time.time()
            vecchio = voce.get("timer")
            if vecchio is not None:
                vecchio.cancel()
            timer = threading.Timer(ATTESA_ALBUM, self._chiudi_album,
                                    args=(gruppo,))
            timer.daemon = True
            voce["timer"] = timer
            timer.start()

    def _chiudi_album(self, gruppo: str) -> None:
        """Il gruppo e' finito: un turno solo, con tutte le foto."""
        with self._album_lock:
            voce = self._album.get(gruppo)
        if voce is None:
            return
        # Il timer e' scattato nello stesso istante in cui arrivava un
        # altro pezzo: quel pezzo ha gia' riarmato un timer nuovo, e questo
        # giro non deve rubargli l'album.
        if time.time() - float(voce.get("visto") or 0.0) < ATTESA_ALBUM - 0.2:
            return
        with self._album_lock:
            voce = self._album.pop(gruppo, None)
        if not voce:
            return
        allegati = list(voce.get("allegati") or [])
        if not allegati:
            return
        self._avvia_turno(str(voce.get("chat") or ""),
                          str(voce.get("testo") or ""), allegati)

    # --- il turno --------------------------------------------------
    def _avvia_turno(self, chat_id: str, testo: str,
                     allegati: list[dict[str, Any]]) -> None:
        t = threading.Thread(target=self._esegui_turno,
                             args=(chat_id, testo, allegati), daemon=True,
                             name=f"telegram-turno-{self.nome}")
        self._turno_thread = t
        t.start()

    def _esegui_turno(self, chat_id: str, testo: str,
                      allegati_rif: list[dict[str, Any]]) -> None:
        allegati: list[Any] = []
        richiesta = (testo or "").strip()
        testi: list[str] = []
        for rif in allegati_rif or []:
            try:
                extra, presi = self._prepara_allegato(rif)
            except ErroreAllegato as e:
                # Un file rifiutato non porta via gli altri: l'album puo'
                # avere una foto troppo grande e due buone.
                self._rispondi(chat_id, str(e))
                continue
            except ErroreTelegram as e:
                self._rispondi(chat_id,
                               f"Non riesco a prendere l'allegato: {e}")
                continue
            allegati.extend(presi)
            if extra and extra not in testi:
                testi.append(extra)
        if allegati_rif and not allegati and not testi:
            # Ogni file e' gia' stato rifiutato con il suo motivo: un turno
            # su una richiesta fatta di soli allegati, senza allegati, non
            # ha niente da leggere. I vocale fanno eccezione: non portano
            # allegati perche' il loro contenuto sono le parole trascritte.
            return
        if not richiesta:
            # Un album di sole foto ha una didascalia sola, e le altre foto
            # portano il predefinito. Se una didascalia vera c'e', il
            # predefinito e' rumore: resta solo quello che ha scritto
            # l'utente.
            vere = [t for t in testi if t != TESTO_FOTO]
            richiesta = "\n".join(vere or testi).strip()
        if not richiesta:
            self._rispondi(chat_id, "Dimmi cosa devo fare con questo file.")
            return

        self.api.scrive(chat_id)
        aggiorna = self._avanzatore(chat_id)
        try:
            esito = self.turno(richiesta, allegati, aggiorna)
        except Exception as e:  # noqa: BLE001
            self._fine_progresso()
            self._rispondi(chat_id, f"Errore durante il turno: "
                                    f"{type(e).__name__}: {e}")
            return
        finally:
            # Una domanda che nasce e muore dentro il turno non deve
            # sopravvivergli: il messaggio dopo sarebbe letto come la sua
            # risposta.
            pulisci_sospesi(self.bot_id)
        self._fine_progresso()
        self.ultimo_turno = time.time()
        # Il turno puo' tornare anche i file che ha prodotto: `{testo,
        # file}`. Una stringa resta valida — e' quello che torna un
        # chiamante che i file non li sa elencare.
        risposta = ""
        ragionamento = ""
        prodotti: list[dict[str, Any]] = []
        if isinstance(esito, dict):
            risposta = str(esito.get("testo") or "").strip()
            ragionamento = str(esito.get("ragionamento") or "").strip()
            prodotti = [f for f in (esito.get("file") or [])
                       if isinstance(f, dict)]
        else:
            risposta = str(esito or "").strip()
        if not risposta:
            risposta = ("Il turno e' finito senza una risposta testuale. "
                        "Il lavoro puo' essere comunque stato fatto: "
                        "controlla nella finestra di Orchestra.")
        # Prima il ragionamento, poi la risposta: cosi' l'ultima cosa in
        # chat e' quello che conta, e chi l'ha acceso lo legge
        # scorrendo all'indietro quando vuole.
        if ragionamento:
            self._rispondi(chat_id, "Ragionamento del turno:\n" + ragionamento)
        self._rispondi(chat_id, risposta)
        if prodotti:
            self._manda_file(chat_id, prodotti)

    def _risposta_scritta(self, chat_id: str, testo: str,
                          atteso: dict[str, Any]) -> None:
        """Una riga di testo mentre una domanda e' aperta: e' la risposta.

        Per un permesso non c'e' niente da fare: le quattro scelte hanno
        bisogno di sapere quale, e "si'" non dice se vale una volta o per
        sempre. Lo si dice, invece di indovinare.
        """
        esito = ""
        if self.risposta is not None:
            try:
                esito = self.risposta(testo) or ""
            except Exception as e:  # noqa: BLE001
                esito = f"Non sono riuscito a consegnare la risposta: {e}"
        if sospeso(self.bot_id) is None:
            # Consumata: il modulo resta nella chat come promemoria, ma
            # senza pulsanti che non portano piu' da nessuna parte.
            self._chiudi_modulo(
                atteso, "Risposta: " + (testo[:600] or "(vuota)"))
        self._rispondi(chat_id, esito or "Risposta inviata.")

    def _chiudi_modulo(self, atteso: dict[str, Any], testo: str) -> None:
        """Riscrive il messaggio della domanda togliendo i pulsanti."""
        chat = str(atteso.get("chat") or "")
        try:
            messaggio = int(atteso.get("message_id") or 0)
        except (TypeError, ValueError):
            messaggio = 0
        if not chat or not messaggio:
            return
        try:
            self._modifica_testo(chat, messaggio,
                                 (testo or "Fatto.")[:MAX_TESTO],
                                 markup=tastiera(None))
        except ErroreTelegram as e:
            self._log(f"telegram {self.nome}: modulo non chiuso: {e}")

    def _manda_file(self, chat_id: str, file: list[dict[str, Any]]) -> None:
        """Allega alla chat i file che il turno ha prodotto.

        Il tetto e' quello del Bot API (50 MB) e non quello del download:
        sono due limiti diversi. Un file troppo grande non si manda, ma si
        dice dove sta, perche' "non e' arrivato niente" senza motivo e' un
        guasto che l'utente non sa come chiudere.
        """
        mandati = 0
        for voce in file[:MASSIMO_FILE_PER_TURNO]:
            percorso = str(voce.get("percorso") or "")
            nome = str(voce.get("nome") or os.path.basename(percorso) or "file")
            try:
                with open(percorso, "rb") as f:
                    dati = f.read(MASSIMO_INVIO + 1)
            except OSError as e:
                self._log(f"telegram {self.nome}: {nome} non leggibile: {e}")
                continue
            if not dati:
                continue
            if len(dati) > MASSIMO_INVIO:
                self._rispondi(chat_id,
                               f"{nome} supera i"
                               f" {MASSIMO_INVIO // (1024 * 1024)} MB che "
                               "Telegram accetta: sta in " + percorso)
                continue
            foto = os.path.splitext(nome)[1].lower() in FOTO
            try:
                self.api.send_file(chat_id, nome, dati,
                                   didascalia=str(voce.get("didascalia") or ""),
                                   foto=foto)
                mandati += 1
            except ErroreTelegram as e:
                self._log(f"telegram {self.nome}: {nome} non inviato: {e}")
                self._rispondi(chat_id, f"Non sono riuscito ad allegare "
                                        f"{nome}: {e}. Il file e' in {percorso}")
        resto = len(file) - MASSIMO_FILE_PER_TURNO
        if resto > 0:
            self._rispondi(chat_id, f"Altri {resto} file li ha prodotti il "
                                    "turno, ma qui ne allego cinque: sono "
                                    "nella cartella del progetto.")

    def _prepara_allegato(self, rif: dict[str, Any]) -> tuple[str, list[Any]]:
        """Scarica il file e lo prepara per il turno.

        Torna (testo da mandare all'agente, allegati). Per un vocale il
        testo e' la trascrizione e non c'e' allegato: l'agente l'audio
        non lo sa leggere, le parole si'.
        """
        tipo = rif.get("tipo") or ""
        nome = rif.get("nome") or "file"
        if tipo == "video":
            raise ErroreAllegato(
                "I video non li guardo: mandami un'immagine, un documento "
                "o un vocale.")
        dimensione = int(rif.get("dimensione") or 0)
        if dimensione > MASSIMO_FILE:
            raise ErroreAllegato(
                f"{nome}: {dimensione // (1024 * 1024)} MB. Telegram non mi "
                f"lascia scaricare piu' di {MASSIMO_FILE // (1024 * 1024)} "
                "MB: mandalo piu' piccolo, o mettilo nella cartella di "
                "lavoro e dimmi il nome.")
        info = self.api.get_file(rif.get("file_id") or "")
        percorso = info.get("file_path") or ""
        if not percorso:
            raise ErroreAllegato(f"{nome}: Telegram non mi ha dato il file.")
        dati = self.api.scarica(percorso)
        if not dati:
            raise ErroreAllegato(f"{nome}: e' arrivato vuoto.")

        if tipo in ("voce", "audio"):
            return self._trascrivi(nome, dati), []

        from .attachments import AttachmentError, allega

        try:
            att = allega(nome, dati)
        except AttachmentError as e:
            raise ErroreAllegato(str(e)) from None
        testo = (rif.get("didascalia") or "").strip()
        if not testo:
            testo = (TESTO_FOTO if tipo == "foto"
                     else f"Leggi questo documento ({nome}).")
        return testo, [att]

    def _trascrivi(self, nome: str, dati: bytes) -> str:
        from . import stt

        if not stt.disponibile():
            raise ErroreAllegato(
                "Il vocale lo so trascrivere, ma il motore vocale non e' "
                "installato. In Orchestra: Opzioni, pulsante Dipendenze, "
                "e installa faster-whisper. Oppure scrivimi quello che "
                "dicevi.")
        try:
            testo = (stt.trascrivi(dati, nome) or "").strip()
        except Exception as e:  # noqa: BLE001
            raise ErroreAllegato(
                f"Non riesco a trascrivere il vocale: {type(e).__name__}: "
                f"{e}") from None
        if not testo:
            raise ErroreAllegato("Il vocale non si sente: non ho capito "
                                 "niente.")
        return testo

    # --- il messaggio di stato -------------------------------------
    def _avanzatore(self, chat_id: str) -> Callable[..., None]:
        """La funzione che il turno chiama per dire come sta andando.

        Due cose diverse, due destini diversi. Il *pensiero* e' una riga
        sola che si riscrive e alla fine sparisce: nessuno rilegge la
        coda del ragionamento, e lasciarla li' seppellisce la risposta.
        Le *azioni* invece sono la cronaca: ogni tool che parte e' un
        messaggio nuovo, e resta. Prima anche quelle finivano dentro il
        messaggio riscritto, quindi si vedeva che qualcosa cambiava ma
        non cosa era stato fatto.
        """
        stato: dict[str, Any] = {"chat": chat_id, "id": 0,
                                 "inizio": time.monotonic(),
                                 "ultimo": 0.0, "testo": "",
                                 "azioni": 0, "ultima_azione": 0.0,
                                 "prima_pendente": 0.0, "pendenti": []}
        self._stato_progresso = stato

        def manda_azioni(forza: bool = False) -> None:
            """Manda le azioni in attesa, se e' ora di mandarle."""
            if not stato["pendenti"]:
                return
            if stato["azioni"] >= MAX_AZIONI:
                stato["pendenti"].clear()
                return
            ora = time.monotonic()
            # Si aspetta l'intervallo dalla *prima* azione in coda, non
            # dall'ultimo invio: due tool partiti insieme sono un messaggio
            # solo con due righe, non due messaggi a un decimo di secondo.
            if not forza and ora - stato["prima_pendente"] < INTERVALLO_AZIONE:
                return
            righe = stato["pendenti"][:6]
            del stato["pendenti"][:6]
            try:
                self.api.send_message(chat_id, "\n".join(righe))
            except ErroreTelegram as e:
                self._log(f"telegram {self.nome}: azione non inviata: {e}")
                return
            stato["azioni"] += 1
            stato["ultima_azione"] = ora
            stato["prima_pendente"] = 0.0

        def aggiorna(testo: str, azione: str | None = None) -> None:
            if azione:
                azione = azione.strip()[:200]
                if azione:
                    if not stato["pendenti"]:
                        stato["prima_pendente"] = time.monotonic()
                    stato["pendenti"].append(azione)
                manda_azioni()
            testo = (testo or "").strip()
            if not testo:
                return
            testo = testo[:MAX_TESTO]
            ora = time.monotonic()
            if not stato["id"]:
                # Un turno da due secondi non merita un messaggio che poi
                # sparisce: si aspetta di sapere che e' lungo.
                if ora - stato["inizio"] < PRIMO_AVVISO:
                    return
                try:
                    inviato = self._invia_testo(chat_id, testo)
                except ErroreTelegram as e:
                    self._log(f"telegram {self.nome}: stato non inviato: {e}")
                    return
                stato["id"] = int((inviato.get("result") or {}).get(
                    "message_id") or 0)
                stato["ultimo"] = ora
                stato["testo"] = testo
                return
            if ora - stato["ultimo"] < INTERVALLO_PROGRESSO:
                return
            if testo == stato["testo"]:
                return
            try:
                self._modifica_testo(chat_id, stato["id"], testo)
            except ErroreTelegram as e:
                self._log(f"telegram {self.nome}: stato non aggiornato: {e}")
            stato["ultimo"] = ora
            stato["testo"] = testo

        return aggiorna

    def _fine_progresso(self) -> None:
        stato = self._stato_progresso
        self._stato_progresso = None
        if not stato:
            return
        # L'ultima azione non deve sparire solo perche' il turno e'
        # finito prima del prossimo intervallo: quelle rimaste in coda
        # partono insieme, in un messaggio solo.
        pendenti = stato.get("pendenti") or []
        if pendenti and stato.get("azioni", 0) < MAX_AZIONI:
            try:
                self._invia_testo(stato["chat"],
                                  "\n".join(a[:200] for a in pendenti[:6]))
            except ErroreTelegram as e:
                self._log(f"telegram {self.nome}: azione non inviata: {e}")
        stato["pendenti"] = []
        if not stato.get("id"):
            return
        try:
            self.api.delete_message(stato["chat"], stato["id"])
        except ErroreTelegram as e:
            self._log(f"telegram {self.nome}: stato non tolto: {e}")


def _invito_collegare() -> str:
    return ("Questa chat non e' collegata a nessun bot di Orchestra, quindi "
            "non eseguo niente.\n\n"
            "Apri Orchestra sul computer, vai nel pannello Bot, scegli il "
            "bot e inquadra il codice che compare (o mandalo qui come "
            "/start <codice>).")
