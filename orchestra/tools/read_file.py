"""Tool read_file: leggere un file con i numeri di riga.

Il tool legge TESTO. Per questo, prima di decodificare, guarda i byte: un
PDF, un .docx o un PNG non sono testo, e leggerli come se lo fossero non
dava un errore — dava caratteri casuali presentati come righe. Il modello
riceveva 4.800 caratteri di struttura PDF, con i numeri di riga accanto, e
niente gli diceva che non era il contenuto del documento. Un output
sbagliato che sembra giusto e' peggio di un errore.

Le tre cose che questo file fa, e perche':

1. Riconosce il binario dai primi byte, e per i formati che sappiamo
   aprire (PDF, docx/xlsx/pptx) restituisce il TESTO VERO; per gli altri
   dice qual e' lo strumento giusto (`screenshot_view` per un'immagine).
2. Decodifica il testo con l'encoding che il file ha davvero. Un .txt o
   un .csv esportato da un programma italiano su Windows e' spesso
   cp1252, e `utf-8` con `errors="replace"` trasformava ogni accento in
   U+FFFD: l'accento spariva in silenzio, e nessuno poteva sapere che era
   stato letto male. Quando l'encoding non e' UTF-8 lo si dice.
3. Taglia con i numeri di riga, come prima: start_line, end_line e
   max_lines valgono identici per un file di testo e per il testo
   estratto da un PDF.
"""

from __future__ import annotations

from ..testo import decodifica, descrizione_encoding, tipo_binario
from ..types import Tool
from ._guard import _safe_path

_ESTENSIONI_OFFICE = ("docx", "xlsx", "pptx")


def _testo_da_binario(path: str, nome: str, dati: bytes, tipo: str) -> str:
    """Il testo di un file che non e' testo, o la spiegazione del perche' no."""
    if tipo == "pdf":
        from ..attachments import AttachmentError, allega

        try:
            att = allega(nome, dati)
        except AttachmentError as e:
            # Il messaggio dice la causa vera (libreria mancante, file
            # protetto, pagine troppe): qui si aggiunge solo dove siamo.
            return f"NON RIESCO A LEGGERLO: {e}"
        if att.testo:
            return (f"... [testo estratto dal PDF, {att.pagine} pagine]\n"
                    + att.testo)
        # Scansionato: le pagine sono immagini. Guardarlo e' un lavoro per
        # un modello con la visione, non per read_file.
        return (f"{path} e' un PDF scansionato: le pagine sono immagini, "
                f"non testo. Per guardarle usa screenshot_view con questo "
                f"percorso.")
    if tipo.startswith("immagine"):
        return (f"{path} e' {tipo}, non testo: leggerlo come testo darebbe "
                f"caratteri casuali. Per guardarlo usa "
                f"screenshot_view('{path}').")
    return (f"{path} sembra {tipo}, non un file di testo. read_file legge "
            f"testo; per i PDF e i documenti Office lo fa gia', per gli "
            f"archivi e i formati binari serve il programma che li apre.")


def tool_read_file() -> Tool:
    def handler(path: str, max_lines: int = 400, start_line: int = 1, end_line: int | None = None) -> str:
        p = _safe_path(path)
        if not p.exists():
            return f"NON ESISTE: {path}"
        if p.is_dir():
            entries = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())
            return f"DIRECTORY {path}:\n" + "\n".join(entries[:max_lines])
        try:
            start_line = max(1, int(start_line or 1))
        except (TypeError, ValueError):
            start_line = 1
        # end_line ha priorita' su max_lines: se il chiamante dice
        # "dalla riga 50 alla riga 100", e' piu' preciso di "50 righe
        # a partire dalla 50". Se e' None o 0, torna a max_lines.
        if end_line is not None:
            try:
                end_line = int(end_line)
            except (TypeError, ValueError):
                end_line = None
        if end_line is not None and end_line > 0:
            max_lines = max(1, end_line - start_line + 1)
        else:
            try:
                max_lines = max(1, min(int(max_lines or 400), 2000))
            except (TypeError, ValueError):
                max_lines = 400
        try:
            dati = p.read_bytes()
        except OSError as e:
            return f"NON RIESCO A LEGGERLO: {path}: {e}"
        ext = p.suffix.lower().lstrip(".")
        if ext in _ESTENSIONI_OFFICE:
            # Un file Office e' uno zip di XML: il magic number direbbe
            # "archivio zip", l'estensione dice quale parte leggere.
            from .. import office

            try:
                tipo_doc, testo = office.estrai(p.name, dati)
            except office.OfficeError as e:
                return f"NON RIESCO A LEGGERLO: {e}"
            intestazione = f"... [testo estratto da {tipo_doc}]\n"
        else:
            tipo = tipo_binario(dati)
            if tipo:
                return _testo_da_binario(path, p.name, dati, tipo)
            testo, encoding = decodifica(dati)
            intestazione = (
                f"... [file non UTF-8: letto come "
                f"{descrizione_encoding(encoding)}]\n"
                if encoding not in ("utf-8", "utf-8-sig") else ""
            )
        lines = testo.splitlines()
        # start_line è 1-based, come i numeri che si vedono a schermo:
        # chiedere "riga 500" e ricevere dalla 501 è il tipo di errore che
        # non si nota finché non si modifica la riga sbagliata.
        fetta = lines[start_line - 1:start_line - 1 + max_lines]
        numbered = [f"{i + start_line:>5}| {l}" for i, l in enumerate(fetta)]
        tail = (
            f"\n... [{len(lines) - (start_line - 1 + max_lines)} righe rimanenti non mostrate]"
            if len(lines) > start_line - 1 + max_lines
            else ""
        )
        head = f"... [prime {start_line - 1} righe omesse]\n" if start_line > 1 else ""
        if not numbered:
            return f"VUOTO OLTRE LA RIGA {start_line}: {path} ha {len(lines)} righe."
        return intestazione + head + "\n".join(numbered) + tail

    return Tool(
        name="read_file",
        description=(
            "Legge un file di testo con numeri di riga, o elenca una "
            "directory. Legge anche il TESTO dentro un PDF o un "
            ".docx/.xlsx/.pptx. Per un'immagine (foto, logo, screenshot) "
            "usa screenshot_view."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso relativo alla root, o ASSOLUTO: un percorso fuori dalla root chiede il permesso all utente."},
                "start_line": {
                    "type": "integer",
                    "description": "Riga da cui partire (1 = inizio, default 1).",
                    "default": 1,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Righe massime da leggere (default 400). Ignorato se end_line e' specificato.",
                    "default": 400,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Riga finale da leggere (inclusiva). Se specificato, sovrascrive max_lines. Es: start_line=50, end_line=100 legge le righe 50-100.",
                },
            },
            "required": ["path"],
        },
        handler=handler,
    )
