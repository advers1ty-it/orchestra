"""Leggere uno screenshot e darlo al modello come immagine.

Il problema che risolve: `computer_screenshot` e `browser_screenshot`
scrivono un PNG e dicono "salvato in ...". Ma il modello non ha modo di
VEDERE quel file: riceve un percorso, e un percorso non è uno schermo.
Lo strumento esisteva, ma serviva a poco — come una telecamera che
scatta e poi nasconde la foto.

Questo tool chiude il cerchio: prende il PNG (o JPG) che è stato
prodotto, lo legge e lo manda al modello come immagine, così può
descrivere cosa c'è a schermo, trovare un elemento, verificare un
layout.

Il formato è lo stesso degli allegati della chat (data URL base64):
non c'è motivo di inventarne uno secondo.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..attachments import AttachmentError, allega
from ..types import Tool, ToolResult


def _risolvi(nome_file: str) -> tuple[Path | None, str]:
    """(percorso, problema). Il problema e' "" quando il percorso va bene.

    Passa da `_safe_path` come ogni altro tool, e non da una risoluzione
    fatta a mano. Due ragioni, entrambe viste succedere:

    - il confine. Prima un percorso ASSOLUTO fuori dalla cartella di
      lavoro veniva letto senza chiedere niente, mentre `read_file` sullo
      stesso file chiedeva il permesso: il tool che non applica la
      guardia e' la porta girevole, e questa e' la porta piu' comoda
      (un'immagine si guarda, non si legge riga per riga, quindi nessuno
      se ne accorge).
    - la cartella. Prima `from . import _root` prendeva la root del
      PACCHETTO (`orchestra/`), non quella di lavoro: un percorso
      relativo corretto diventava "Non trovo", e il messaggio invitava a
      passarne un altro. `_safe_path` usa la root giusta.
    """
    from ._guard import _safe_path

    try:
        return _safe_path(nome_file), ""
    except PermissionError as e:
        return None, str(e)
    except (ValueError, OSError) as e:
        return None, f"Non posso aprire '{nome_file}': {e}"


def tool_screenshot_view() -> Tool:
    def handler(nome_file: str = "") -> ToolResult:
        if not nome_file:
            return ToolResult(
                text=("Serve il percorso dell'immagine: quello che "
                      "computer_screenshot e browser_screenshot dicono nel "
                      "loro risultato, oppure il nome di un file immagine "
                      "nella cartella di lavoro."))
        p, problema = _risolvi(nome_file)
        if p is None:
            return ToolResult(text=problema)
        try:
            dati = p.read_bytes()
        except FileNotFoundError:
            return ToolResult(
                text=(f"Non trovo '{nome_file}'. Un percorso relativo parte "
                      f"dalla cartella di lavoro; per un file altrove serve "
                      f"il percorso assoluto, e li' chiedo il permesso."))
        except OSError as e:
            return ToolResult(text=f"Non leggo '{nome_file}': {e}")

        try:
            att = allega(os.path.basename(nome_file), dati)
        except AttachmentError as e:
            return ToolResult(text=str(e))

        if not att.immagini:
            # allega ha deciso che non è un'immagine (es. un PDF con
            # testo): in quel caso il contenuto è in `testo`, e mandarlo
            # come tale è meglio che mandarlo come immagine.
            return ToolResult(text=att.testo or f"{nome_file}: vuoto")

        kb = len(dati) // 1024
        return ToolResult(
            text=(f"Screenshot '{os.path.basename(nome_file)}' "
                  f"({kb} KB). Ecco l'immagine: descrivi cosa vedi, "
                  f"o trova ciò che ti serve."),
            immagini=list(att.immagini),
        )

    return Tool(
        name="screenshot_view",
        description=(
            "Looks at an image file (PNG/JPG/GIF/WebP: a screenshot, but "
            "also a photo or a logo) and shows it to the model. It is the "
            "only way to SEE an image on disk: read_file on a PNG does not "
            "give its content, and a path is not an image. Use it to "
            "describe a screen, find an element on a page, check a layout, "
            "or see what a photo contains before placing text on it. "
            "Accepts a path relative to the working directory or an "
            "absolute one (outside the root it asks permission). On a PDF "
            "it returns the text, when there is one."
        ),
        schema={"type": "object",
                "properties": {"nome_file": {
                    "type": "string",
                    "description": "Path of the image file to look at."}},
                "required": ["nome_file"]},
        handler=handler,
    )
