"""Posta: configurazione, lettura e invio, con server finti.

Nessuna rete: le classi IMAP e SMTP vengono sostituite, e il test guarda
cosa il codice ha chiesto al server (host, criteri di ricerca, busta del
messaggio). Un test che parla con Gmail vero avrebbe bisogno di una
password per le app e fallirebbe per la rete, non per il codice.
"""

import email
import imaplib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import orchestra.mail as mail_mod  # noqa: E402

_conta = 0
_falliti: list[str] = []


def check(nome: str, cond: bool, extra: str = "") -> None:
    global _conta
    if cond:
        _conta += 1
        print(f"  OK  {nome}")
    else:
        _falliti.append(nome)
        print(f"  FAIL  {nome}" + (f" — {extra}" if extra else ""))


def env(**extra: str) -> dict[str, str]:
    base = {"ORCHESTRA_MAIL_INDIRIZZO": "tizio@gmail.com",
            "ORCHESTRA_MAIL_PASSWORD": "password-per-le-app"}
    base.update(extra)
    return base


def _messaggio(da: str, oggetto: str, corpo: str) -> bytes:
    m = email.message.EmailMessage()
    m["From"] = da
    m["To"] = "io@example.com"
    m["Subject"] = oggetto
    m["Date"] = "Mon, 09 Nov 2026 10:00:00 +0100"
    m.set_content(corpo)
    return m.as_bytes()


MESSAGGI = [
    _messaggio("Mario Rossi <mario@example.com>", "Prima mail", "il primo corpo"),
    _messaggio("Anna Bianchi <anna@example.com>", "Risposta importante",
               "il secondo corpo, quello piu' recente"),
]


class FakeIMAP:
    istanze: list["FakeIMAP"] = []
    errore_login = ""
    vuoto = False

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.criterio = ""
        self.cartella = ""
        self.logout_chiamato = False
        FakeIMAP.istanze.append(self)

    def login(self, utente, password):
        if FakeIMAP.errore_login:
            raise imaplib.IMAP4.error(FakeIMAP.errore_login)
        return "OK", [b"logged in"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\HasNoChildren) "/" "[Gmail]/Sent Mail"']

    def select(self, cartella, readonly=False):
        self.cartella = cartella
        return "OK", [b"2"]

    def search(self, charset, criterio):
        self.criterio = criterio
        if FakeIMAP.vuoto:
            return "OK", [b""]
        return "OK", [b"1 2"]

    def fetch(self, ident, cosa):
        return "OK", [(b"1 (RFC822 {123}", MESSAGGI[int(ident) - 1])]

    def logout(self):
        self.logout_chiamato = True


class FakeSMTP:
    istanze: list["FakeSMTP"] = []
    errore_login = ""

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.starttls_chiamato = False
        self.inviati = []
        self.chiuso = False
        FakeSMTP.istanze.append(self)

    def ehlo(self):
        return 250, b"ok"

    def starttls(self):
        self.starttls_chiamato = True

    def login(self, utente, password):
        if FakeSMTP.errore_login:
            raise mail_mod.smtplib.SMTPAuthenticationError(535, b"bad credentials")
        return 235, b"ok"

    def send_message(self, msg):
        self.inviati.append(msg)

    def quit(self):
        self.chiuso = True


class FintoSmtplib:
    SMTP = FakeSMTP
    SMTP_SSL = FakeSMTP
    SMTPException = mail_mod.smtplib.SMTPException
    SMTPAuthenticationError = mail_mod.smtplib.SMTPAuthenticationError


class FintoImaplib:
    IMAP4_SSL = FakeIMAP
    IMAP4 = imaplib.IMAP4
    error = imaplib.IMAP4.error


def con_server_finti(funzione):
    """Esegue la funzione con IMAP e SMTP sostituiti, e li rimette dopo."""
    vero_imap = mail_mod.imaplib
    vero_smtp = mail_mod.smtplib
    mail_mod.imaplib = FintoImaplib
    mail_mod.smtplib = FintoSmtplib
    FakeIMAP.istanze.clear()
    FakeSMTP.istanze.clear()
    FakeIMAP.errore_login = ""
    FakeIMAP.vuoto = False
    try:
        return funzione()
    finally:
        mail_mod.imaplib = vero_imap
        mail_mod.smtplib = vero_smtp


print("[1] configurazione: i preset e gli override")
cfg = mail_mod.configurazione(env())
check("gmail ricavato dall'indirizzo", cfg["imap_host"] == "imap.gmail.com", cfg["imap_host"])
check("porta IMAP 993", cfg["imap_port"] == 993, cfg["imap_port"])
check("porta SMTP 587", cfg["smtp_port"] == 587, cfg["smtp_port"])
cfg = mail_mod.configurazione(env(ORCHESTRA_MAIL_PROVIDER="libero",
                                  ORCHESTRA_MAIL_INDIRIZZO="tizio@libero.it"))
check("preset esplicito libero", cfg["imap_host"] == "imap.libero.it", cfg["imap_host"])
cfg = mail_mod.configurazione(env(ORCHESTRA_MAIL_IMAP_HOST="posta.azienda.it",
                                  ORCHESTRA_MAIL_SMTP_HOST="invio.azienda.it"))
check("host espliciti vincono sul preset",
      (cfg["imap_host"], cfg["smtp_host"]) == ("posta.azienda.it", "invio.azienda.it"),
      cfg)

print("[2] configurazione: quando manca qualcosa lo dice")
try:
    mail_mod.configurazione({"ORCHESTRA_MAIL_INDIRIZZO": "tizio@gmail.com"})
    check("password mancante segnalata", False)
except mail_mod.ErrorePosta as e:
    check("password mancante segnalata", "ORCHESTRA_MAIL_PASSWORD" in str(e), str(e))
    check("spiega che serve la password per le app",
          "password per le app" in str(e), str(e))
try:
    mail_mod.configurazione({"ORCHESTRA_MAIL_INDIRIZZO": "tizio@dominio-sconosciuto.it",
                             "ORCHESTRA_MAIL_PASSWORD": "x"})
    check("fornitore sconosciuto segnalato", False)
except mail_mod.ErrorePosta as e:
    check("fornitore sconosciuto segnalato",
          "ORCHESTRA_MAIL_PROVIDER" in str(e), str(e))

print("[3] leggi: filtri, ordine e contenuto")
def leggi_due():
    return mail_mod.leggi(quanti=2, da="mario", non_letti=True, env=env())

messaggi = con_server_finti(leggi_due)
check("ha letto due messaggi", len(messaggi) == 2, str(len(messaggi)))
check("prima il piu' recente", messaggi[0]["oggetto"] == "Risposta importante",
      str(messaggi[0]))
check("il mittente e' decodificato", "Mario Rossi" in messaggi[1]["da"],
      messaggi[1]["da"])
check("la data e' leggibile", messaggi[0]["data"].startswith("2026-11-09"),
      messaggi[0]["data"])
check("l'anteprima contiene il corpo", "secondo corpo" in messaggi[0]["anteprima"],
      messaggi[0]["anteprima"])
istanza = FakeIMAP.istanze[-1]
check("ha chiesto UNSEEN", "UNSEEN" in istanza.criterio, istanza.criterio)
check("ha filtrato per mittente", 'FROM "mario"' in istanza.criterio,
      istanza.criterio)
check("ha aperto INBOX in sola lettura", istanza.cartella == "INBOX",
      istanza.cartella)
check("la connessione e' stata chiusa", istanza.logout_chiamato)
check("ha usato il timeout", istanza.timeout == mail_mod.SECONDI, istanza.timeout)


def leggi_vuoto():
    FakeIMAP.vuoto = True
    return mail_mod.leggi(quanti=5, env=env())

check("casella senza messaggi: lista vuota", con_server_finti(leggi_vuoto) == [])

print("[4] cartelle: i nomi come li chiama il server")
nomi = con_server_finti(lambda: mail_mod.cartelle(env=env()))
check("elenco cartelle", nomi == ["INBOX", "[Gmail]/Sent Mail"], str(nomi))

print("[5] manda: la busta e il collegamento giusto")
def invia(con_allegato=False):
    allegati = []
    if con_allegato:
        fd, percorso = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        with open(percorso, "w", encoding="utf-8") as f:
            f.write("contenuto allegato")
        allegati = [percorso]
    esito = mail_mod.manda(a="mario@example.com, anna@example.com",
                           cc="capo@example.com",
                           oggetto="Rapporto di oggi",
                           corpo="Ciao, ecco il rapporto.",
                           allegati=allegati, env=env())
    return esito

esito = con_server_finti(invia)
server = FakeSMTP.istanze[-1]
check("ha usato il server giusto", server.host == "smtp.gmail.com", server.host)
check("STARTTLS sulla 587", server.starttls_chiamato)
check("un solo messaggio inviato", len(server.inviati) == 1)
busta = server.inviati[0]
check("mittente corretto", busta["From"] == "tizio@gmail.com", busta["From"])
check("destinatari separati", "mario@example.com" in busta["To"]
      and "anna@example.com" in busta["To"], busta["To"])
check("copia in Cc", busta["Cc"] == "capo@example.com", busta["Cc"])
check("oggetto", busta["Subject"] == "Rapporto di oggi", busta["Subject"])
corpo = busta.get_body(preferencelist=("plain",)).get_content()
check("corpo", "ecco il rapporto" in corpo, corpo)
check("esito elenca i destinatari", len(esito["a"]) == 2, str(esito))
check("la connessione e' stata chiusa", server.chiuso)

print("[6] manda: allegato e porta 465")
def invia_con_allegato():
    return mail_mod.manda(a="mario@example.com", oggetto="Con file",
                          corpo="in allegato", allegati=[allegato], env=env())
fd, allegato = tempfile.mkstemp(suffix=".txt")
os.close(fd)
with open(allegato, "w", encoding="utf-8") as f:
    f.write("contenuto")
esito = con_server_finti(invia_con_allegato)
msg = FakeSMTP.istanze[-1].inviati[0]
nomi_allegati = [p.get_filename() for p in msg.iter_attachments()]
check("l'allegato e' nel messaggio", nomi_allegati == [os.path.basename(allegato)],
      str(nomi_allegati))

def invia_465():
    return mail_mod.manda(a="mario@example.com", oggetto="Aruba",
                          corpo="ciao",
                          env=env(ORCHESTRA_MAIL_PROVIDER="aruba",
                                  ORCHESTRA_MAIL_INDIRIZZO="tizio@aruba.it"))
con_server_finti(invia_465)
server = FakeSMTP.istanze[-1]
check("porta 465", server.port == 465, server.port)
check("niente STARTTLS sulla 465", not server.starttls_chiamato)

print("[7] manda: gli errori si fermano prima di partire")
def senza_destinatario():
    return mail_mod.manda(a="", oggetto="x", corpo="y", env=env())

try:
    con_server_finti(senza_destinatario)
    check("destinatario mancante segnalato", False)
except mail_mod.ErrorePosta as e:
    check("destinatario mancante segnalato", "destinatario" in str(e), str(e))

def senza_oggetto():
    return mail_mod.manda(a="mario@example.com", oggetto="  ", corpo="y", env=env())

try:
    con_server_finti(senza_oggetto)
    check("oggetto mancante segnalato", False)
except mail_mod.ErrorePosta as e:
    check("oggetto mancante segnalato", "oggetto" in str(e), str(e))

def allegato_mancante():
    return mail_mod.manda(a="mario@example.com", oggetto="x", corpo="y",
                          allegati=[os.path.join(tempfile.gettempdir(), "non-esiste.pdf")],
                          env=env())

try:
    con_server_finti(allegato_mancante)
    check("allegato inesistente segnalato", False)
except mail_mod.ErrorePosta as e:
    check("allegato inesistente segnalato", "allegato non trovato" in str(e), str(e))
check("nessun invio partito con un allegato mancante",
      not FakeSMTP.istanze or not FakeSMTP.istanze[-1].inviati)

print("[8] errori di accesso: la password per le app va nominata")
def login_imap_rifiutato():
    FakeIMAP.errore_login = "AUTHENTICATIONFAILED"
    return mail_mod.leggi(env=env())

try:
    con_server_finti(login_imap_rifiutato)
    check("login IMAP rifiutato segnalato", False)
except mail_mod.ErrorePosta as e:
    check("login IMAP rifiutato segnalato",
          "password per le app" in str(e), str(e))

def login_smtp_rifiutato():
    FakeSMTP.errore_login = "535"
    return mail_mod.manda(a="mario@example.com", oggetto="x", corpo="y", env=env())

try:
    con_server_finti(login_smtp_rifiutato)
    check("login SMTP rifiutato segnalato", False)
except mail_mod.ErrorePosta as e:
    check("login SMTP rifiutato segnalato",
          "password per le app" in str(e), str(e))

print("[9] tool email: configurazione assente e azioni")
from orchestra.tools.email import tool_email  # noqa: E402

strumento = tool_email()
check("il tool si chiama email", strumento.name == "email", strumento.name)
risposta = strumento.handler(azione="boh")
check("azione sconosciuta segnalata", risposta.startswith("ERRORE:"), risposta)

salvate = {k: os.environ.pop(k, None) for k in
           ("ORCHESTRA_MAIL_INDIRIZZO", "ORCHESTRA_MAIL_PASSWORD",
            "ORCHESTRA_MAIL_PROVIDER", "ORCHESTRA_MAIL_IMAP_HOST",
            "ORCHESTRA_MAIL_SMTP_HOST")}
try:
    risposta = strumento.handler(azione="stato")
    check("senza configurazione il tool lo dice",
          risposta.startswith("ERRORE:") and "ORCHESTRA_MAIL" in risposta, risposta)
finally:
    for k, v in salvate.items():
        if v is not None:
            os.environ[k] = v

os.environ["ORCHESTRA_MAIL_INDIRIZZO"] = "tizio@gmail.com"
os.environ["ORCHESTRA_MAIL_PASSWORD"] = "password-per-le-app"
try:
    risposta = strumento.handler(azione="stato")
    check("lo stato mostra host e porte",
          "imap.gmail.com" in risposta and "smtp.gmail.com" in risposta, risposta)
    risposta = con_server_finti(lambda: strumento.handler(azione="leggi", quanti=2))
    check("il tool formatta i messaggi",
          "Risposta importante" in risposta and "Mario Rossi" in risposta, risposta)
finally:
    os.environ.pop("ORCHESTRA_MAIL_INDIRIZZO", None)
    os.environ.pop("ORCHESTRA_MAIL_PASSWORD", None)

print(f"\n{_conta} check, {len(_falliti)} falliti")
if _falliti:
    print("FALLITI: " + ", ".join(_falliti))
    sys.exit(1)
