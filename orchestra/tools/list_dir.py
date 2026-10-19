"""Tool list_dir: elencare una directory."""

from __future__ import annotations

from fnmatch import fnmatch

from ..types import Tool
from ._guard import _root, _safe_path


def tool_list_dir() -> Tool:
    def handler(path: str = ".", max_items: int = 300,
                pattern: str = "") -> str:
        p = _safe_path(path)
        if not p.is_dir():
            return f"NON È UNA DIRECTORY: {path}"
        # max_items era già applicato (tagliava a 300) ma non era nello
        # schema: il modello lo passava per buon senso e moriva con
        # "unexpected keyword argument". Esposto = il modello lo può
        # chiedere e gli si risponde.
        try:
            max_items = max(1, min(int(max_items or 300), 5000))
        except (TypeError, ValueError):
            max_items = 300
        out = []
        # _root() e non la costante ROOT: ROOT viene congelata all'import,
        # e se il processo cambia ORCHESTRA_ROOT dopo, il confronto
        # fallirebbe sempre e ogni percorso — anche interno — uscirebbe
        # per esteso. Meglio una riga lunga che un elenco illeggibile.
        base = _root()
        for x in sorted(p.iterdir()):
            # pattern (es. '*.py'): su una cartella grande non si vuole
            # tutto, si vuole quel tipo. Filtro sul NOME, come il glob che
            # l'agente scriverebbe a mano in `run_shell`.
            if pattern and not fnmatch(x.name, pattern):
                continue
            # relative_to(base) solleva quando l'utente ha autorizzato
            # una cartella FUORI dalla root e l'agente la elenca: senza
            # questo, il permesso concesso non serve a nulla perche' il
            # listing muore con un ValueError. Fuori dalla root mostriamo
            # il percorso per esteso, che e' anche l'unica forma che
            # l'agente puo' riaprire.
            try:
                rel = x.relative_to(base)
            except ValueError:
                rel = x
            if x.is_dir():
                n = len(list(x.rglob("*")))
                out.append(f"[dir]  {rel}/  ({n} elementi)")
            else:
                out.append(f"[file] {rel}  ({x.stat().st_size} byte)")
        if not out and pattern:
            return f"NESSUN ELEMENTO '{pattern}' in {path}"
        return "\n".join(out[:max_items]) or "(vuota)"

    return Tool(
        name="list_dir",
        description="Elenca il contenuto di una directory con dimensioni.",
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory, default '.'. Può essere ASSOLUTA: se è fuori "
                        "dalla root, all'utente compare la domanda sul permesso."
                    ),
                    "default": ".",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Elementi massimi da elencare (default 300).",
                    "default": 300,
                },
                "pattern": {
                    "type": "string",
                    "description": "Filtra per nome con un glob, es. '*.py'. Vuoto = tutto.",
                    "default": "",
                },
            },
        },
        handler=handler,
    )
