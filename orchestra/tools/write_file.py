"""Tool write_file: scrivere un file intero."""

from __future__ import annotations

from ..types import Tool
from ._guard import _safe_path


def _registra(p, azione: str) -> None:
    """Segna il file come toccato, per il progetto in cui si sta lavorando.

    E' quello che rende la vista "i file di questo progetto" vera:
    senza, la lista mostrerebbe i file che un git status vede, che
    non e' la stessa cosa di "cosa ha fatto l'agente in questa
    conversazione".

    Il path e' relativo alla root del progetto, non assoluto: e' il
    modo in cui l'utente conosce i suoi file, e non espone il
    percorso della macchina.
    """
    try:
        from .. import progetti as _pr
        from ._guard import _root
        try:
            rel = str(p.relative_to(_root()))
        except Exception:  # noqa: BLE001
            rel = str(p)
        _pr.registra_file(_pr._root_progetto(), rel, azione)
    except Exception:  # noqa: BLE001
        pass


def tool_write_file() -> Tool:
    def handler(path: str, content: str) -> str:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_text(content, encoding="utf-8")
        verb = "aggiornato" if existed else "creato"
        _registra(p, verb)
        return f"File {verb}: {path} ({len(content)} caratteri, {content.count(chr(10))+1} righe)"

    return Tool(
        name="write_file",
        description="Scrive un file di testo, creando le directory necessarie.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso relativo alla root, o ASSOLUTO: un percorso fuori dalla root chiede il permesso all utente."},
                "content": {"type": "string", "description": "Contenuto completo del file."},
            },
            "required": ["path", "content"],
        },
        handler=handler,
    )
