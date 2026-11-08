"""Un file è testo? E se sì, con che codifica è scritto?

Due tool devono rispondere alla stessa domanda e dare la stessa risposta:
`read_file` quando legge, `edit_file` quando modifica. Quando la rispondevano
separatamente, `read_file` mostrava un .txt cp1252 con gli accenti giusti e
`edit_file` sullo stesso file diceva "file binario?" — due verità sullo stesso
byte, e l'utente in mezzo a decidere quale credere.

Quindi la risposta sta qui, una volta sola:

- `tipo_binario` dice se i byte sono di un formato che non è testo (PDF, PNG,
  zip, o semplicemente roba con byte nulli). Non indovina dall'estensione:
  un PNG rinominato `.txt` resta un PNG, e il nome non è una prova.
- `decodifica` prova UTF-8 (con o senza BOM), poi cp1252 — l'encoding di
  quasi tutti i file italiani scritti da Windows — e infine latin-1, che
  mappa ogni byte e quindi non fallisce mai. Dice quale ha usato, perché un
  accento letto con l'encoding sbagliato non è un dettaglio: è un nome
  storpiato in un'anagrafica.
- `codifica` fa il contrario con lo STESSO encoding, così modificare un file
  non lo converte di nascosto.

Il caso che questo modulo esiste per evitare: `read_text(encoding="utf-8",
errors="replace")`. Non fallisce mai, e per questo è peggio di un errore —
restituisce `Perch<U+FFFD> <U+FFFD> cos<U+FFFD>` e nessuno sa che è stato
letto male.
"""

from __future__ import annotations

# Firme che dicono "questo non è testo". Sono le stesse che usa
# `attachments` per gli allegati: se un giorno cambiano là, cambiano qui.
FIRME = (
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "immagine PNG"),
    (b"\xff\xd8\xff", "immagine JPEG"),
    (b"GIF8", "immagine GIF"),
    (b"RIFF", "file RIFF (WebP, WAV, AVI)"),
    (b"PK\x03\x04", "archivio zip"),
)

# Encoding che si sanno riscrivere senza perdere niente.
CODIFICHE = ("utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1")


def tipo_binario(dati: bytes) -> str:
    """Il tipo del file dai primi byte, "" se sembra testo.

    Il controllo sui byte nulli è la rete di sicurezza: quasi tutti i
    formati binari ne hanno uno nei primi kilobyte, e un file che ne ha
    uno non è testo qualunque sia la sua estensione.
    """
    for firma, nome in FIRME:
        if dati.startswith(firma):
            return nome
    if b"\x00" in dati[:8192]:
        return "binario"
    return ""


def decodifica(dati: bytes) -> tuple[str, str]:
    """(testo, encoding usato). Non solleva mai."""
    if dati.startswith(b"\xef\xbb\xbf"):
        # Il BOM si toglie dal testo ma si ricorda nell'encoding: senza,
        # riscrivere il file lo perderebbe, e alcuni programmi Windows
        # leggono il file come ANSI se il BOM non c'è.
        return dati[3:].decode("utf-8", "replace"), "utf-8-sig"
    if dati.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dati.decode("utf-16", "replace"), "utf-16"
    try:
        return dati.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    # cp1252 copre l'italiano e l'Europa occidentale; i cinque byte che non
    # definisce diventano U+FFFD, e in quel caso si preferisce latin-1 (che
    # li mappa tutti) invece di mostrare un carattere di sostituzione dentro
    # una parola.
    cp = dati.decode("cp1252", "replace")
    if "\ufffd" not in cp:
        return cp, "cp1252"
    return dati.decode("latin-1", "replace"), "latin-1"


def codifica(testo: str, encoding: str) -> bytes:
    """I byte di `testo` nell'encoding con cui è stato letto."""
    if encoding not in CODIFICHE:
        encoding = "utf-8"
    return testo.encode(encoding)


def descrizione_encoding(encoding: str) -> str:
    """Come si dice all'utente che il file non era UTF-8."""
    return {
        "utf-8-sig": "UTF-8 con BOM",
        "utf-16": "UTF-16",
        "cp1252": "cp1252 (Windows)",
        "latin-1": "latin-1",
    }.get(encoding, encoding)
