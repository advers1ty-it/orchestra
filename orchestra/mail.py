"""Posta: leggere la casella con IMAP e mandare con SMTP.

PERCHE' IMAP E SMTP, E NON UN SERVIZIO DI INVIO

Per mandare un'email da un programma esiste mezza dozzina di servizi con
una chiave API. Ma qui la casella non e' "un canale per far arrivare un
avviso": e' la posta dell'utente, con dentro quello che gli hanno
scritto. Un servizio di invio non legge la posta di nessuno, e un
servizio di invio che legge una casella non esiste. Gmail, Outlook,
Libero, Aruba, iCloud: parlano tutti IMAP e SMTP, che sono due
protocolli, non due account da aprire.

LA PASSWORD

Non e' la password dell'account. Gmail e Outlook (e quasi tutti gli
altri) vogliono una "password per le app": una password lunga generata
nelle impostazioni di sicurezza, che si revoca da sola senza cambiare
quella vera. Il messaggio d'errore lo dice, perche' "autenticazione
fallita" con la password giusta e' il modo piu' comune di perdere
mezz'ora.
"""

from __future__ import annotations

import email
import imaplib
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parsedate_to_datetime
from typing import Any

# I fornitori piu' comuni, con i loro host. Non e' un elenco esaustivo:
# chi non c'e' mette gli host a mano, ed e' per questo che esistono
# ORCHESTRA_MAIL_IMAP_HOST e ORCHESTRA_MAIL_SMTP_HOST.
PRESET: dict[str, tuple[str, int, str, int]] = {
    # nome: (host imap, porta, host smtp, porta)
    "gmail": ("imap.gmail.com", 993, "smtp.gmail.com", 587),
    "googlemail": ("imap.gmail.com", 993, "smtp.gmail.com", 587),
    "outlook": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "hotmail": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "live": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "libero": ("imap.libero.it", 993, "smtp.libero.it", 587),
    "virgilio": ("imap.virgilio.it", 993, "smtp.virgilio.it", 587),
    "aruba": ("imaps.aruba.it", 993, "smtps.aruba.it", 465),
    "tiscali": ("imap.tiscali.it", 993, "smtp.tiscali.it", 587),
    "icloud": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587),
    "me": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587),
    "yahoo": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465),
    "fastmail": ("imap.fastmail.com", 993, "smtp.fastmail.com", 587),
    "gmx": ("imap.gmx.com", 993, "mail.gmx.com", 587),
}

CHIAVI = ("ORCHESTRA_MAIL_INDIRIZZO", "ORCHESTRA_MAIL_PASSWORD")

# Un elenco di messaggi non e' un archivio: su un telefono si leggono le
# prime righe, e il resto e' rumore. Il contenuto completo di UN
# messaggio e' un'altra cosa, e ha un tetto suo.
MAX_MESSAGGI = 20
# Quanto corpo si scarica per un messaggio. `RFC822` porterebbe a casa
# anche l'allegato da 20 MB per leggere due righe; dieci messaggi cosi'
# sono duecento megabyte per un'anteprima.
LIMITE_ANTEPRIMA = 4096
SECONDI = 30


class ErrorePosta(RuntimeError):
    """La casella non risponde, o la configurazione non basta."""


def _pulisci(testo: str) -> str:
    """Un valore da mettere dentro una ricerca IMAP, senza rompere la sintassi."""
    return " ".join(str(testo or "").split()).replace('"', "").replace("\\", "")


def configurazione(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Host, porte e credenziali, con i preset e gli override.

    Le variabili esplicite vincono sul preset: un fornitore che cambia
    host, o un server aziendale che non e' in nessun elenco, si configura
    senza aspettare una versione nuova.
    """
    e = dict(env) if env is not None else dict(os.environ)
    try:
        from .percorsi import ENV_PATH
        from .providers import load_env

        # Il .env sotto l'ambiente vero: in chat le variabili non sono
        # esportate, e senza questa lettura una casella configurata in
        # Opzioni risulterebbe "non configurata".
        e = {**load_env(ENV_PATH), **e}
    except Exception:  # noqa: BLE001 - la configurazione non deve crashare
        pass
    indirizzo = (e.get("ORCHESTRA_MAIL_INDIRIZZO") or "").strip()
    password = (e.get("ORCHESTRA_MAIL_PASSWORD") or "").strip()
    mancanti = [k for k, v in zip(CHIAVI, (indirizzo, password)) if not v]
    if mancanti:
        raise ErrorePosta(
            "manca " + " e ".join(mancanti) + ". Servono l'indirizzo della "
            "casella e una password per le app (non quella dell'account: "
            "Gmail e Outlook la generano nelle impostazioni di sicurezza). "
            "Si mettono in Opzioni, oppure nel .env di Orchestra.")

    provider = (e.get("ORCHESTRA_MAIL_PROVIDER") or "").strip().lower()
    preset = PRESET.get(provider)
    imap_host = (e.get("ORCHESTRA_MAIL_IMAP_HOST") or "").strip()
    smtp_host = (e.get("ORCHESTRA_MAIL_SMTP_HOST") or "").strip()
    if not imap_host or not smtp_host:
        if preset is None:
            # Il dominio e' un indizio onesto: se la casella e'
            # nome@gmail.com il preset giusto e' ovvio, e non serve
            # chiederlo.
            dominio = indirizzo.rsplit("@", 1)[-1].lower()
            preset = PRESET.get(dominio.split(".")[0])
        if preset is None:
            raise ErrorePosta(
                "non so quali server usare per questa casella: imposta "
                "ORCHESTRA_MAIL_PROVIDER (gmail, outlook, libero, aruba, "
                "tiscali, icloud, yahoo, gmx, fastmail) oppure "
                "ORCHESTRA_MAIL_IMAP_HOST e ORCHESTRA_MAIL_SMTP_HOST.")
        imap_host = imap_host or preset[0]
        smtp_host = smtp_host or preset[2]
    imap_port = _porta(e.get("ORCHESTRA_MAIL_IMAP_PORT"), preset[1] if preset else 993)
    smtp_port = _porta(e.get("ORCHESTRA_MAIL_SMTP_PORT"), preset[3] if preset else 587)
    return {
        "indirizzo": indirizzo,
        "password": password,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "provider": provider,
    }


def _porta(valore: Any, predefinita: int) -> int:
    try:
        porta = int(str(valore or "").strip())
    except (TypeError, ValueError):
        return int(predefinita)
    return porta if 0 < porta < 65536 else int(predefinita)


def _imap(cfg: dict[str, Any]) -> imaplib.IMAP4_SSL:
    """Una connessione IMAP gia' autenticata.

    Il timeout e' obbligatorio: senza, un host che non risponde tiene
    fermo il turno finche' la rete non decide, e l'agente sembra morto.
    Se il login fallisce la connessione si chiude: un socket aperto a
    ogni tentativo con la password sbagliata e' un socket per volta
    lasciato li'.
    """
    con = None
    try:
        con = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"],
                                timeout=SECONDI)
        con.login(cfg["indirizzo"], cfg["password"])
    except imaplib.IMAP4.error as e:
        _chiudi(con)
        raise ErrorePosta(
            f"{cfg['imap_host']} ha rifiutato l'accesso a "
            f"{cfg['indirizzo']}: {_testo_errore(e)}. Se la password e' "
            "giusta, serve una password per le app (Gmail e Outlook non "
            "accettano quella dell'account).") from None
    except OSError as e:
        _chiudi(con)
        raise ErrorePosta(
            f"non riesco a raggiungere {cfg['imap_host']}:"
            f"{cfg['imap_port']} ({e}). Controlla la rete e l'host.") from None
    return con


def _nome_cartella(nome: str) -> str:
    """Il nome della cartella come lo vuole il server.

    `[Gmail]/Posta inviata` ha uno spazio: passato nudo, il server legge
    due argomenti e risponde BAD. Le virgolette vanno messe, e i
    caratteri interni che le romperebbero vanno protetti.
    """
    nome = (nome or "INBOX").strip() or "INBOX"
    if nome.startswith('"') and nome.endswith('"') and len(nome) > 1:
        return nome
    if any(c in nome for c in ' ()"/'):
        return '"' + nome.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return nome


def _testo_errore(e: BaseException) -> str:
    """Il messaggio vero di imaplib/smtplib, senza il tipo davanti."""
    testo = str(e).strip()
    return testo or e.__class__.__name__


def cartelle(env: dict[str, str] | None = None) -> list[str]:
    """Le cartelle della casella, come le chiama il server."""
    cfg = configurazione(env)
    con = _imap(cfg)
    try:
        tip, righe = con.list()
        if tip != "OK":
            return []
        nomi: list[str] = []
        for riga in righe or []:
            if not isinstance(riga, bytes):
                continue
            testo = riga.decode("utf-8", "replace")
            # La forma e' `(\HasNoChildren) "/" "INBOX"`: l'ultimo pezzo
            # tra virgolette e' il nome, e i prefissi dei server Microsoft
            # ci sono dentro anche loro.
            nome = testo.rsplit('"', 2)[-2] if '"' in testo else testo.split()[-1]
            if nome:
                nomi.append(nome)
        return nomi
    finally:
        _chiudi(con)


def _chiudi(con: Any) -> None:
    try:
        con.logout()
    except Exception:  # noqa: BLE001 - chiudere non deve sollevare
        pass


def _intestazione(msg: email.message.Message, nome: str) -> str:
    valore = msg.get(nome)
    if valore is None:
        return ""
    try:
        from email.header import decode_header, make_header

        return str(make_header(decode_header(str(valore)))).strip()
    except Exception:  # noqa: BLE001
        return str(valore).strip()


def _primo_letterale(pezzi: Any) -> bytes:
    for pezzo in pezzi or []:
        if isinstance(pezzo, tuple) and len(pezzo) >= 2 and pezzo[1]:
            return pezzo[1]
    return b""


def _letterali(pezzi: Any) -> list[bytes]:
    return [p[1] for p in (pezzi or [])
            if isinstance(p, tuple) and len(p) >= 2 and p[1]]


def _anteprima(con: Any, ident: bytes, msg: email.message.Message) -> str:
    """Le prime righe del corpo, senza scaricare il messaggio intero.

    Si chiede solo la prima parte (il testo) e al massimo
    LIMITE_ANTEPRIMA byte. Un allegato dentro il messaggio non viene
    nemmeno trasferito: e' la differenza fra leggere la posta e
    scaricarsela tutta per guardare il mittente.
    """
    try:
        # `is_multipart()` guarda il payload, che qui non c'e' (abbiamo
        # solo l'intestazione): sarebbe sempre falso, e un messaggio con
        # allegato verrebbe letto come corpo unico. La struttura si legge
        # dal Content-Type.
        if msg.get_content_maintype() == "multipart":
            tip, pezzi = con.fetch(
                ident,
                f"(BODY.PEEK[1.MIME] BODY.PEEK[1]<0.{LIMITE_ANTEPRIMA}>)")
            if tip != "OK":
                return ""
            letterali = _letterali(pezzi)
            if len(letterali) < 2:
                return ""
            # Intestazione MIME + quei 4 KB: cosi' `get_payload(decode=True)`
            # scioglie anche quoted-printable e base64.
            parte = email.message_from_bytes(
                letterali[0].rstrip() + b"\r\n\r\n" + letterali[1])
        else:
            tip, pezzi = con.fetch(
                ident, f"(BODY.PEEK[TEXT]<0.{LIMITE_ANTEPRIMA}>)")
            if tip != "OK":
                return ""
            parte = email.message_from_bytes(
                msg.as_bytes().rstrip() + b"\r\n\r\n"
                + _primo_letterale(pezzi))
    except imaplib.IMAP4.error:
        return ""
    if parte.get_content_maintype() != "text":
        return ""
    testo = " ".join(_decodifica(parte).split())
    return testo[:800] + ("…" if len(testo) > 800 else "")


def _decodifica(parte: email.message.Message) -> str:
    try:
        dati = parte.get_payload(decode=True) or b""
    except Exception:  # noqa: BLE001
        return ""
    charset = parte.get_content_charset() or "utf-8"
    try:
        return dati.decode(charset, "replace")
    except (LookupError, UnicodeDecodeError):
        return dati.decode("utf-8", "replace")


def leggi(*, cartella: str = "INBOX", quanti: int = 10,
          da: str = "", oggetto: str = "", testo: str = "",
          non_letti: bool = False,
          env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Gli ultimi messaggi che corrispondono ai filtri, dal piu' recente.

    I filtri sono campi, non una stringa di ricerca IMAP: una stringa
    libera scritta dal modello e' un modo per farsi rispondere "BAD
    invalid search criteria" e non capire perche'.
    """
    quanti = max(1, min(int(quanti or 10), MAX_MESSAGGI))
    cfg = configurazione(env)
    criteri = []
    if non_letti:
        criteri.append("UNSEEN")
    if da.strip():
        criteri.append(f'FROM "{_pulisci(da)}"')
    if oggetto.strip():
        criteri.append(f'SUBJECT "{_pulisci(oggetto)}"')
    if testo.strip():
        criteri.append(f'TEXT "{_pulisci(testo)}"')
    criterio = "(" + " ".join(criteri) + ")" if criteri else "ALL"

    con = _imap(cfg)
    try:
        tip, _dati = con.select(_nome_cartella(cartella), readonly=True)
        if tip != "OK":
            raise ErrorePosta(f"la cartella {cartella!r} non si apre.")
        try:
            tip, dati = con.search(None, criterio)
        except imaplib.IMAP4.error as e:
            raise ErrorePosta(
                f"ricerca rifiutata dal server: {_testo_errore(e)}") from None
        if tip != "OK" or not dati:
            return []
        ids = (dati[0] or b"").split()
        scelti = ids[-quanti:]
        messaggi: list[dict[str, Any]] = []
        for ident in reversed(scelti):
            try:
                tip, pezzi = con.fetch(ident, "(BODY.PEEK[HEADER])")
            except imaplib.IMAP4.error:
                continue
            if tip != "OK":
                continue
            intestazione = _primo_letterale(pezzi)
            if not intestazione:
                continue
            msg = email.message_from_bytes(intestazione)
            quando = _intestazione(msg, "Date")
            try:
                quando = parsedate_to_datetime(quando).strftime(
                    "%Y-%m-%d %H:%M")
            except Exception:  # noqa: BLE001 - una data strana non è un errore
                pass
            messaggi.append({
                "da": _intestazione(msg, "From"),
                "a": _intestazione(msg, "To"),
                "oggetto": _intestazione(msg, "Subject") or "(senza oggetto)",
                "data": quando,
                "anteprima": _anteprima(con, ident, msg),
            })
        return messaggi
    finally:
        _chiudi(con)


def manda(*, a: str, oggetto: str, corpo: str, cc: str = "",
          allegati: list[str] | None = None,
          env: dict[str, str] | None = None) -> dict[str, Any]:
    """Manda un messaggio. Torna i destinatari, non un "ok" generico.

    `a` e `cc` accettano piu' indirizzi separati da virgola. Un allegato
    che non c'e' ferma l'invio: mandare la mail senza il file che
    l'utente aveva chiesto e' peggio che non mandarla, perche' sembra
    fatta.
    """
    destinatari = _indirizzi(a)
    if not destinatari:
        raise ErrorePosta("manca il destinatario")
    copia = _indirizzi(cc)
    if not (oggetto or "").strip():
        raise ErrorePosta("manca l'oggetto: una mail senza oggetto finisce "
                          "dritta nello spam, quando ci finisce")
    file_allegati = [str(p).strip() for p in (allegati or []) if str(p).strip()]
    for percorso_allegato in file_allegati:
        if not os.path.isfile(percorso_allegato):
            raise ErrorePosta(f"allegato non trovato: {percorso_allegato}")

    cfg = configurazione(env)
    msg = EmailMessage()
    msg["From"] = cfg["indirizzo"]
    msg["To"] = ", ".join(destinatari)
    if copia:
        msg["Cc"] = ", ".join(copia)
    msg["Subject"] = oggetto.strip()
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(corpo or "")
    for percorso_allegato in file_allegati:
        nome = os.path.basename(percorso_allegato)
        tipo, _ = mimetypes.guess_type(nome)
        principale, _, sotto = (tipo or "application/octet-stream").partition("/")
        with open(percorso_allegato, "rb") as f:
            msg.add_attachment(f.read(), maintype=principale or "application",
                               subtype=sotto or "octet-stream", filename=nome)

    try:
        if cfg["smtp_port"] == 465:
            server: Any = smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"],
                                           timeout=SECONDI)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"],
                                  timeout=SECONDI)
            server.ehlo()
            server.starttls()
            server.ehlo()
        try:
            server.login(cfg["indirizzo"], cfg["password"])
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
    except smtplib.SMTPAuthenticationError as e:
        raise ErrorePosta(
            f"{cfg['smtp_host']} ha rifiutato l'accesso a {cfg['indirizzo']}: "
            f"{_testo_errore(e)}. Serve una password per le app, non quella "
            "dell'account.") from None
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorePosta(
            f"invio non riuscito con {cfg['smtp_host']}:{cfg['smtp_port']}: "
            f"{_testo_errore(e)}") from None
    return {"a": destinatari, "cc": copia,
            "allegati": [os.path.basename(p) for p in file_allegati],
            "da": cfg["indirizzo"]}


def _indirizzi(testo: str) -> list[str]:
    parti = [p.strip() for p in str(testo or "").replace(";", ",").split(",")]
    return [p for p in parti if p]
