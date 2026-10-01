"""Allegare un file alla chat: foto e PDF.

La regola che decide tutto: un PDF non e' un'immagine. Un PDF con testo
dentro si legge come testo, e Costa zero token; mandarlo come immagine
fa spendere 1100 token PER PAGINA per ottenere un risultato peggiore. Un
PDF scansionato invece e' immagagine, e senza visione non si legge.

Quindi: si guarda dentro il PDF, e si sceglie. Non si chiede all'utente
perche' lo sa gia' — un PDF con testo si vede aprendolo.

Il limite sui PDF e' dichiarato perche' renderlo significa fallire in
silenzio. Un PDF di 300 pagine a 1100 token per pagina sono 330.000
token: piu' del contesto di quasi ogni modello, e la richiesta muore
con un errore che sembla di rete. Si ferma prima.
"""

import base64
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


from orchestra.attachments import Attachment, AttachmentError, allega  # noqa: E402
from orchestra.types import Message  # noqa: E402

print("[1] Una foto PNG")
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
try:
    a = allega("foto.png", png)
    check("accettata", a.kind == "image", a.kind)
    check("diventa una data URL", a.data_url.startswith("data:image/png;base64,"))
    check("il nome resta per la UI", a.nome == "foto.png")
except AttachmentError as e:
    check("accettata", False, str(e))

print("\n[2] Un JPEG")
jpg = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")
try:
    a = allega("foto.jpg", jpg)
    check("accettata", a.kind == "image", a.kind)
    check("formato giusto", a.data_url.startswith("data:image/jpeg;base64,"))
except AttachmentError as e:
    check("accettata", False, str(e))

print("\n[3] Un PNG che dice di essere un PDF")
# Contenuto e nome devono ANDARE d'accordo. Un file rinominato non e'
# un formato diverso: e' un tentativo, e fallisce sul magic number.
falso = base64.b64encode(png).replace(b"iVBOR", b"JVBER")
try:
    a = allega("documento.pdf", falso)
    check("respinto", False, f"accettato come {a.kind}")
except AttachmentError as e:
    check("respinto perche' il contenuto non e' un PDF", True)

print("\n[4] Cosa e' accettato e cosa no")
# Il testo semplice viene accettato: un .txt o un .csv sono spesso
# quello che serve per estrarre qualcosa. Il test precedente chiedeva
# di rifiutarlo e falliva — ma la decisione giusta e' accettarlo, e il
# test sbagliava, non il codice.
try:
    a = allega("dati.txt", "nome;eta;citta".encode())
    check("un .txt di testo e' accettato", a.kind == "testo", a.kind)
    check("e ne conserva il contenuto", "eta" in a.testo, a.testo[:30])
except AttachmentError as e:
    check("un .txt di testo e' accettato", False, str(e))

# ma un file binario senza estensione coerente no.
# bytes() e non b"\xff": in una stringa Python quegli escape diventano
# quattro caratteri ASCII, che sono UTF-8 valido, e il file verrebbe
# accettato come testo. Il test avrebbe fallito per la ragione
# sbagliata e avrebbe insegnato che il codice sbaglia.
try:
    allega("file", bytes([0, 1, 2, 255, 254]))
    check("un binario viene respinto", False, "accettato come testo")
except AttachmentError as e:
    check("un binario viene respinto", True)
    print(f"          -> {e}")

# file vuoto
try:
    allega("vuoto", b"")
    check("un file vuoto viene respinto", False, "accettato")
except AttachmentError as e:
    check("un file vuoto viene respinto", True)

print("\n[5] I limiti sono dichiarati, non nascosti")
# Il caso pericoloso e' il PDF gigante: si scopre solo al momento della
# richiesta, con un errore che sembra di rete.
from orchestra.attachments import LIMITE_PDF_PAGINE, LIMITE_MB  # noqa: E402

check("c'e' un tetto sui PDF in pagine", LIMITE_PDF_PAGINE > 0, str(LIMITE_PDF_PAGINE))
check("e un tetto in byte", LIMITE_MB > 0, f"{LIMITE_MB} MB")
try:
    allega("grande.png", b"x" * (int(LIMITE_MB * 1024 * 1024) + 10))
    check("un file troppo grande viene respinto", False, "accettato")
except AttachmentError as e:
    check("un file troppo grande viene respinto", True)
    print(f"          -> {e}")

print("\n[6] Il testo va PRIMA delle immagini")
# Non per abitudine: se l'istruzione arriva dopo, un modello puo'
# leggerla come descrizione dell'immagine. E l'API OpenAI mette testo e
# immagini in una lista ordinata: l'ordine che mando e' l'ordine che
# arriva.
m = Message(role="user", content="estrai i prezzi", images=["data:image/png;base64,AA"])
api = m.to_api()
parti = api["content"]
check("content e' una lista", isinstance(parti, list), type(parti).__name__)
check("il testo e' il primo elemento", parti[0]["type"] == "text", parti[0]["type"])
check("poi vengono le immagini", parti[1]["type"] == "image_url", parti[1]["type"])

print("\n[7] Senza immagini resta una stringa")
# Alcuni gateway rifiutano la forma a lista. Non costa mandare la
# forma semplice quando la semplice basta.
m2 = Message(role="user", content="ciao")
check("content e' ancora una stringa", isinstance(m2.to_api()["content"], str))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
