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
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .dati import percorso as percorso_dati

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


class ErroreTelegram(RuntimeError):
    """La chiamata all'API non e' riuscita, e il messaggio dice perche'."""

    def __init__(self, messaggio: str, codice: int | None = None) -> None:
        super().__init__(messaggio)
        self.codice = codice


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
    conn.commit()
    return conn


def _riga(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "bot_id": int(r["bot_id"]),
        "token": r["token"] or "",
        "username": r["username"] or "",
        "chat_id": r["chat_id"] or "",
        "chat_nome": r["chat_nome"] or "",
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

        bot_validi = [int(b["id"]) for b in bots_mod.tutti()]
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
#  L'API
# ===================================================================
Trasporto = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _urllib(url: str, dati: dict[str, Any], secondi: float) -> dict[str, Any]:
    corpo = urllib.parse.urlencode(dati).encode("utf-8")
    req = urllib.request.Request(
        url, data=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=secondi) as risposta:
            grezzo = risposta.read()
    except urllib.error.HTTPError as e:
        # Telegram sbaglia con un JSON che spiega l'errore: buttarlo
        # via lascerebbe solo "400 Bad Request", che non dice niente.
        grezzo = e.read() or b"{}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroreTelegram(f"rete non raggiungibile: {e}") from e
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


class Api:
    """Le quattro chiamate che servono, e nient'altro.

    Il trasporto e' un parametro perche' i test non devono parlare con
    Telegram: una funzione che prende (url, dati, secondi) e torna il
    JSON decodificato basta a provare tutta la logica.
    """

    def __init__(self, token: str, *, trasporto: Trasporto | None = None,
                 base: str = BASE) -> None:
        self.token = (token or "").strip()
        self.base = base.rstrip("/")
        self._trasporto = trasporto or _urllib

    def chiama(self, metodo: str, secondi: float = 30,
               **campi: Any) -> dict[str, Any]:
        if not self.token:
            raise ErroreTelegram("manca il token del bot")
        url = f"{self.base}/bot{self.token}/{metodo}"
        return self._trasporto(url, campi, secondi)

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
            "allowed_updates": json.dumps(["message"]),
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
                     secondi: float = 20) -> dict[str, Any]:
        return self.chiama("sendMessage", secondi=secondi,
                           chat_id=str(chat_id), text=testo,
                           disable_web_page_preview="true")

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


# ===================================================================
#  Il ponte
# ===================================================================
class Ponte:
    """Un bot di Orchestra, il suo token, e la chat che gli scrive.

    `turno(testo)` e' l'unica cosa che questo modulo non sa fare: prende
    il messaggio dell'utente e torna la risposta dell'agente. Tutto il
    resto — chi puo' scrivere, cosa si risponde a chi non e' collegato,
    come si spezza un testo lungo — e' qui, e si prova senza rete.
    """

    def __init__(self, bot_id: int, nome: str, api: Api,
                 turno: Callable[[str], str], *,
                 attesa: int = ATTESA_POLLING,
                 log: Callable[[str], None] | None = None) -> None:
        self.bot_id = int(bot_id)
        self.nome = (nome or "").strip() or f"bot {bot_id}"
        self.api = api
        self.turno = turno
        self.attesa = max(0, int(attesa))
        self._log = log or (lambda _m: None)
        self._fermo = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None
        self._primo = True
        self.fatti = 0

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
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=secondi)

    @property
    def attivo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

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
            self._primo = False
            # L'arretrato non si rigioca: si prende l'ultimo
            # aggiornamento e si riparte da dopo.
            try:
                ultimi = self.api.get_updates(-1, secondi=0)
            except ErroreTelegram:
                raise
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
            messaggio = aggiornamento.get("message")
            if not isinstance(messaggio, dict):
                continue
            self._gestisci(messaggio)
            gestiti += 1
            self.fatti += 1
        return gestiti

    # --- messaggi --------------------------------------------------
    def _rispondi(self, chat_id: str, testo: str) -> None:
        for pezzo in dividi(testo):
            try:
                self.api.send_message(chat_id, pezzo)
            except ErroreTelegram as e:
                self._log(f"telegram {self.nome}: risposta non inviata: {e}")
                return

    def _gestisci(self, messaggio: dict[str, Any]) -> None:
        chat = messaggio.get("chat") or {}
        chat_id = str(chat.get("id", "") or "")
        if not chat_id:
            return
        testo = (messaggio.get("text") or "").strip()
        chi = (chat.get("username") or chat.get("first_name")
               or chat.get("title") or chat_id)
        legata, _nome_chat = chat_di(self.bot_id)

        if testo.startswith("/"):
            comando, _, argomento = testo.partition(" ")
            comando = comando.split("@", 1)[0].lower()
            if comando == "/start":
                self._start(chat_id, chi, argomento.strip(), legata)
                return
            if comando == "/stop":
                if legata and legata == chat_id:
                    dimentica_chat(self.bot_id)
                    self._rispondi(chat_id, "Scollegato. Da adesso non "
                                            "rispondo piu' qui.")
                else:
                    self._rispondi(chat_id, "Questa chat non e' collegata "
                                            "a nessun bot di Orchestra.")
                return
            if comando == "/stato":
                if legata and legata == chat_id:
                    self._rispondi(chat_id, f"Collegato a {self.nome}. "
                                            "Scrivi e ti rispondo.")
                else:
                    self._rispondi(chat_id, "Non collegato: apri Orchestra, "
                                            "pannello Bot, e inquadra il "
                                            "codice.")
                return
            self._rispondi(chat_id, "Comandi: /start <codice> per collegare, "
                                    "/stato, /stop per scollegare. "
                                    "Qualunque altro testo e' una richiesta.")
            return

        if not legata or legata != chat_id:
            # Nessun turno, nessun tool, nessun costo: chi non ha il
            # codice riceve una spiegazione, non un agente.
            self._rispondi(chat_id,
                           "Questa chat non e' collegata a nessun bot di "
                           "Orchestra, quindi non eseguo niente.\n\n"
                           "Apri Orchestra sul computer, vai nel pannello "
                           "Bot, scegli il bot e inquadra il codice che "
                           "compare (o mandalo qui come /start <codice>).")
            return

        if not testo:
            self._rispondi(chat_id, "Per ora leggo solo testo: foto, "
                                    "documenti e vocali non li ricevo.")
            return

        self.api.scrive(chat_id)
        try:
            risposta = (self.turno(testo) or "").strip()
        except Exception as e:  # noqa: BLE001
            self._rispondi(chat_id, f"Errore durante il turno: "
                                    f"{type(e).__name__}: {e}")
            return
        if not risposta:
            risposta = ("Il turno e' finito senza una risposta testuale. "
                        "Il lavoro puo' essere comunque stato fatto: "
                        "controlla nella finestra di Orchestra.")
        self._rispondi(chat_id, risposta)

    def _start(self, chat_id: str, chi: str, argomento: str,
               legata: str) -> None:
        if legata and legata == chat_id:
            self._rispondi(chat_id, f"Sei gia' collegato a {self.nome}. "
                                    "Scrivi e ti rispondo.")
            return
        if argomento and codice_valido(self.bot_id, argomento):
            imposta_chat(self.bot_id, chat_id, chi)
            self._rispondi(chat_id,
                           f"Collegato a {self.nome}.\n\n"
                           "Quello che scrivi qui arriva all'agente, con i "
                           "suoi tool e i suoi permessi. /stop per "
                           "scollegare. Le risposte possono metterci un "
                           "po': Telegram non mostra l'avanzamento del "
                           "lavoro, solo il risultato.")
            return
        # Codice assente, scaduto o sbagliato: si dice cosa fare, non se
        # esiste un codice.
        self._rispondi(chat_id,
                       "Per collegare questa chat a Orchestra serve il "
                       "codice che compare nel pannello Bot, sotto "
                       "Telegram. Inquadra il QR da li', oppure mandalo "
                       "qui come /start <codice>. Il codice scade dopo "
                       "dieci minuti.")
