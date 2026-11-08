"""Tool write_file: scrivere un file intero."""

from __future__ import annotations

from ..types import Tool
from ._guard import _root, _safe_path


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
        # Checkpoint PRIMA della scrittura: dopo, la versione vecchia non
        # esiste piu' da nessuna parte. Se il checkpoint fallisce si
        # scrive lo stesso: un lavoro non salvato e' peggio di un lavoro
        # non annullabile.
        try:
            from ..checkpoint import registra

            registra(p, _root(), "scrittura")
        except Exception:  # noqa: BLE001
            pass
        # Scrittura atomica: un crash a meta' lascerebbe un file troncato,
        # e il backup del checkpoint e' la versione di PRIMA.
        from ..scrittura import scrivi_testo

        try:
            scrivi_testo(p, content)
        except OSError as e:
            return f"SCRITTURA FALLITA: {path}: {e}"
        verb = "aggiornato" if existed else "creato"
        _registra(p, verb)
        return f"File {verb}: {path} ({len(content)} caratteri, {content.count(chr(10))+1} righe)"

    return Tool(
        name="write_file",
        description=(
            "Writes a whole text file, creating the directories it needs. "
            "For a small change inside an existing file prefer edit_file."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the project root, or ABSOLUTE: a path outside the root asks the user for permission."},
                "content": {"type": "string", "description": "Complete content of the file."},
            },
            "required": ["path", "content"],
        },
        handler=handler,
    )
