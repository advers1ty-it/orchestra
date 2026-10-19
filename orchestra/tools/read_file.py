"""Tool read_file: leggere un file con i numeri di riga."""

from __future__ import annotations

from ..types import Tool
from ._guard import _safe_path


def tool_read_file() -> Tool:
    def handler(path: str, max_lines: int = 400, start_line: int = 1) -> str:
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
        try:
            max_lines = max(1, min(int(max_lines or 400), 2000))
        except (TypeError, ValueError):
            max_lines = 400
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
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
        return head + "\n".join(numbered) + tail

    return Tool(
        name="read_file",
        description="Legge un file di testo con numeri di riga, o elenca una directory.",
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
                    "description": "Righe massime da leggere (default 400).",
                    "default": 400,
                },
            },
            "required": ["path"],
        },
        handler=handler,
    )
