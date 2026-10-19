"""Tool write_file: scrivere un file intero."""

from __future__ import annotations

from ..types import Tool
from ._guard import _safe_path


def tool_write_file() -> Tool:
    def handler(path: str, content: str) -> str:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_text(content, encoding="utf-8")
        verb = "aggiornato" if existed else "creato"
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
