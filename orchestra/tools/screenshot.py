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


def _risolvi(nome_file: str) -> Path:
    """Il percorso dello screenshot: relativo alla root, o assoluto."""
    p = Path(nome_file)
    if not p.is_absolute():
        try:
            from . import _root

            p = _root() / p
        except Exception:  # noqa: BLE001 - senza root si lavora sul CWD
            p = Path(os.getcwd()) / p
    return p


def tool_screenshot_view() -> Tool:
    def handler(nome_file: str = "") -> ToolResult:
        if not nome_file:
            return ToolResult(
                text=("Serve il nome del file: computer_screenshot e "
                      "browser_screenshot dicono il percorso nel loro "
                      "risultato."))
        try:
            dati = _risolvi(nome_file).read_bytes()
        except FileNotFoundError:
            return ToolResult(
                text=(f"Non trovo '{nome_file}'. Chiamalo con il percorso "
                      "esatto che computer_screenshot o browser_screenshot "
                      "hanno restituito."))
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
            "Legge un file immagine (screenshot PNG/JPG, es. quello creato "
            "da computer_screenshot o browser_screenshot) e lo mostra al "
            "modello come immagine. Usalo quando devi VEDERE qualcosa "
            "allora che il testo del tool non basta: descrivere uno "
            "schermo, trovare un elemento in una pagina, verificare un "
            "layout. Passa il percorso che lo screenshot ha restituito."
        ),
        schema={"type": "object",
                "properties": {"nome_file": {
                    "type": "string",
                    "description": "Percorso del file immagine da leggere."}},
                "required": ["nome_file"]},
        handler=handler,
    )
