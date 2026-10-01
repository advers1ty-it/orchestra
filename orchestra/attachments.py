"""Allegare un file alla chat: foto e PDF.

La regola che decide tutto: un PDF non e' un'immagine. Un PDF con testo
dentro si legge come testo, e costa zero token; mandarlo come immagine
fa spendere 1100 token PER PAGINA per ottenere un risultato peggiore.
Un PDF scansionato invece e' immagine, e senza visione non si legge.

Quindi si guarda dentro il PDF e si sceglie. Non si chiede all'utente
perche' lo sa gia': un PDF con testo si vede aprendolo.

I tetti sono dichiarati perche' renderli vuol dire fallire in silenzio.
Un PDF di 300 pagine a 1100 token per pagina sono 330.000 token: piu'
del contesto di quasi ogni modello, e la richiesta muore con un errore
che sembra di rete. Si ferma prima, e lo dice.
"""

import base64
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 12 MB: abbondante per una foto, e oltre il limite di molte API. Un
# allegato piu' grande non e' "un po' piu' grande", e' un allegato che
# non passera'.
LIMITE_MB = 12

# Oltre 40 pagine il conto non torna: 40 * 1100 = 44.000 token per una
# sola richiesta, e il contesto si esaurisce prima di arrivare in
# fondo. Si ferma e lo dice, invece di fallire con un errore che sembra
# di rete.
LIMITE_PDF_PAGINE = 40

# Una pagina come immagine: 1000 token a bassa risoluzione, 1500 ad
# alta. 1100 e' la stima media usata per il conto.
TOKEN_PER_PAGINA = 1100

MIME = {
    b"\x89PNG\r\n\x1a\n": ("image", "image/png"),
    b"\xff\xd8\xff": ("image", "image/jpeg"),
    b"GIF87a": ("image", "image/gif"),
    b"GIF89a": ("image", "image/gif"),
    b"RIFF": ("image", "image/webp"),      # controllato sotto: RIFF e' anche WAV
    b"%PDF-": ("pdf", "application/pdf"),
}


class AttachmentError(ValueError):
    """Un allegato che non si puo' usare. Il messaggio spiega perche'."""


@dataclass
class Attachment:
    """Un file allegato, gia' pronto per l'API.

    `immagini` e' la lista di data URL da mettere nel messaggio. Per un
    PDF con testo e' vuota, e il contenuto sta in `testo`: non si
    spendono token a mandare un file che si puo' leggere come stringa.
    """
    nome: str
    kind: str                       # "image" | "pdf" | "testo"
    mime: str
    testo: str = ""
    immagini: list[str] = field(default_factory=list)
    pagine: int = 0

    @property
    def data_url(self) -> str:
        """La prima immagine, per chi vuole una sola riga."""
        return self.immagini[0] if self.immagini else ""

    @property
    def token_stimati(self) -> int:
        """Quanto costera' in token. Detto, non lasciato indovinare.

        Un'immagine costa un numero fisso; un testo costa meta' dei suoi
        caratteri. Sono stime, ma una stima dichiarata vale piu' di una
        sorpresa in fattura.
        """
        if self.kind == "image":
            return 1100
        if self.kind == "pdf":
            return self.pagine * TOKEN_PER_PAGINA
        return max(1, len(self.testo) // 4)


def _magie(dati: bytes) -> tuple[str, str] | None:
    """Il tipo vero del file, dai suoi primi byte. Non dal nome.

    Un file rinominato non cambia formato: e' un tentativo, e si vede
    dal magic number. E l'operazione giusta, perche' un PDF che si
    spaccia da immagine viene mandato a un modello che non ha la
    pagina, e l'errore arriva tre secondi dopo senza dire perche'.
    """
    for firma, (kind, mime) in MIME.items():
        if dati.startswith(firma):
            if firma == b"RIFF":
                # RIFF e' anche WAV: si distingue dal WEBP guardando
                # i 4 byte dopo "RIFF"
                if dati[8:12] == b"WEBP":
                    return "image", "image/webp"
                return None
            return kind, mime
    return None


def tipo_descrizione(dati: bytes) -> str:
    """Che cosa dice DAVVERO questo file, per il messaggio d'errore.

    Serve per dire "questo e' un PNG, non un PDF" invece di "formato non
    riconosciuto": un messaggio che dice cos'e' il file permette di
    correggerlo, uno che dice solo "no" no.
    """
    if dati.startswith(b"\x89PNG\r\n\x1a\n"):
        return "un'immagine PNG"
    if dati.startswith(b"\xff\xd8\xff"):
        return "un'immagine JPEG"
    if dati.startswith(b"GIF8"):
        return "un'immagine GIF"
    if dati.startswith(b"RIFF") and dati[8:12] == b"WEBP":
        return "un'immagine WebP"
    if dati.startswith(b"PK\x03\x04"):
        return "un archivio zip (un .docx o .xlsx sono zip)"
    if dati.startswith(b"GIF") or dati.startswith(b"BM"):
        return "un file di un altro formato"
    return "un formato che non conosco"


def allega(nome: str, dati: bytes) -> Attachment:
    """Prepara un file per la chat. Solleva AttachmentError se non si puo'."""
    if not dati:
        raise AttachmentError(f"{nome}: file vuoto")
    if len(dati) > LIMITE_MB * 1024 * 1024:
        raise AttachmentError(
            f"{nome}: {len(dati) // (1024 * 1024)} MB, il limite e' "
            f"{LIMITE_MB} MB. Allega un file piu' piccolo, o riduci la "
            f"risoluzione delle immagini."
        )

    tipo = _magie(dati)
    if tipo is None:
        # Non e' un'immagine ne' un PDF. Si ammette il testo semplice
        # perche' un .txt o un .csv sono spesso quello che serve per
        # estrarre qualcosa — ma SOLO se l'estensione lo dichiara.
        #
        # Senza quel controllo, un PNG rinominato in .pdf diventerebbe
        # "testo": i suoi byte sono UTF-8 valido, e verrebbe mandato al
        # modello come stringa di caratteri illeggibili. Il nome dice
        # cosa e', e se il nome e' `.pdf` il magic number ha gia' detto
        # che il contenuto e' un PNG: non e' un testo, e' un file che
        # mente.
        estensione = os.path.splitext(nome)[1].lower().lstrip(".")
        if estensione in ("pdf", "png", "jpg", "jpeg", "gif", "webp"):
            raise AttachmentError(
                f"{nome}: il contenuto non corrisponde all'estensione. "
                f"Questo file e' {tipo_descrizione(dati)} non e' "
                f"{estensione}."
            )
        try:
            testo = dati.decode("utf-8")
        except UnicodeDecodeError:
            raise AttachmentError(
                f"{nome}: formato non riconosciuto. Allega un'immagine "
                f"(png, jpg, gif, webp), un PDF o un file di testo."
            ) from None
        if len(testo) > 200_000:
            raise AttachmentError(
                f"{nome}: {len(testo)} caratteri di testo, troppi per un "
                f"messaggio. Mettilo nella cartella di lavoro e lascia "
                f"che l'agente lo legga con read_file."
            )
        return Attachment(nome=nome, kind="testo", mime="text/plain",
                          testo=testo)

    kind, mime = tipo
    if kind == "image":
        b64 = base64.b64encode(dati).decode("ascii")
        return Attachment(nome=nome, kind="image", mime=mime,
                          immagini=[f"data:{mime};base64,{b64}"])

    # PDF: si guarda dentro. Con testo si legge come testo; scansionato
    # si trasforma in immagini, se i mezzi ci sono.
    return _prepara_pdf(nome, dati, mime)


def _prepara_pdf(nome: str, dati: bytes, mime: str) -> Attachment:
    """Un PDF: testo se c'e', immagini se e' scansionato."""
    testo, pagine = _leggi_pdf(dati)
    if pagine > LIMITE_PDF_PAGINE:
        raise AttachmentError(
            f"{nome}: {pagine} pagine, il limite e' {LIMITE_PDF_PAGINE}. "
            f"Servirebbero ~{pagine * TOKEN_PER_PAGINA} token per leggerlo "
            f"come immagini. Allega le pagine che ti servono, o mettilo "
            f"nella cartella di lavoro."
        )
    if testo.strip():
        # Ha testo: si manda il testo. Costa quasi niente ed e' esatto.
        # Renderlo in immagini costerebbe 1100 token a pagina per
        # ottenere qualcosa di peggio, e con reflow diverso.
        return Attachment(nome=nome, kind="pdf", mime=mime,
                          testo=testo, pagine=pagine)
    # Nessun testo: e' scansionato. Serve un modello con la visione.
    immagini = _renderizza(dati)
    if not immagini:
        raise AttachmentError(
            f"{nome}: PDF scansionato e non c'e' un modo di trasformare "
            f"le pagine in immagini. Serve un PDF con testo, oppure un "
            f"modello con la visione su un file gia' convertito."
        )
    return Attachment(nome=nome, kind="pdf", mime=mime,
                      immagini=immagini, pagine=pagine)


def _leggi_pdf(dati: bytes) -> tuple[str, int]:
    """Il testo di un PDF, e quante pagine ha. ("", 0) se non si puo'."""
    try:
        import pypdf  # noqa: PLC0415
    except ImportError:
        try:
            import PyPDF2 as pypdf  # noqa: PLC0415
        except ImportError:
            return "", dati.count(b"/Type /Page") + dati.count(b"/Type/Page")
    try:
        lettore = pypdf.PdfReader(io.BytesIO(dati))
        pagine = len(lettore.pages)
        parti = []
        for p in lettore.pages:
            try:
                parti.append(p.extract_text() or "")
            except Exception:  # noqa: BLE001 - una pagina fallita non
                parti.append("")   # deve far fallire tutto il documento
        return "\n".join(parti), pagine
    except Exception:  # noqa: BLE001
        return "", 0


def _renderizza(dati: bytes) -> list[str]:
    """Le pagine come immagini PNG. Vuoto se non si puo'."""
    try:
        import pypdfium2  # noqa: PLC0415
    except ImportError:
        return []
    try:
        doc = pypdfium2.PdfDocument(dati)
        out = []
        for i in range(min(len(doc), LIMITE_PDF_PAGINE)):
            out.append("data:image/png;base64," + base64.b64encode(
                _png(doc[i].render(scale=1.5))
            ).decode("ascii"))
        return out
    except Exception:  # noqa: BLE001
        return []


def _png(bitmap) -> bytes:
    buf = io.BytesIO()
    bitmap.to_pil().save(buf, format="PNG")
    return buf.getvalue()
