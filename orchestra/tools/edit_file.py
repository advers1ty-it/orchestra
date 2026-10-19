"""Tool edit_file: sostituire una parte di file senza riscriverlo tutto.

E' nato come script a sé in `orchestra/tools/`, e per questo motivo non
era mai stato visto dall'agente: `orchestra/tools.py` (modulo) e
`orchestra/tools/` (cartella) hanno lo stesso nome, e senza `__init__.py`
Python ignora la cartella — `import orchestra.tools.edit_file` fallisce con
`__path__ attribute not found`. Il file c'era, ma non era importabile.

Ora il pacchetto esiste e il tool sta dentro, importabile come gli altri.
"""

from __future__ import annotations

from ..types import Tool
from ._guard import _safe_path


def _sostituisci(testo: str, trova: str, sostituisci: str, quante: int) -> tuple[str, int]:
    """Sostituisce al massimo `quante` occorrenze di `trova`.

    Le posizioni vengono ricalcolate a ogni passo: sostituire dal fondo
    con gli indici calcolati una volta sola darebbe posizioni sbagliate non
    appena la sostituzione ha una lunghezza diversa dalla stringa trovata.
    """
    out = testo
    fatte = 0
    while fatte < quante:
        idx = out.find(trova)
        if idx == -1:
            break
        out = out[:idx] + sostituisci + out[idx + len(trova):]
        fatte += 1
    return out, fatte


def tool_edit_file() -> Tool:
    """Sostituisce una stringa in un file, senza riscrivere tutto il file.

    E' la differenza con `write_file`: riscrivere un file di 2000 righe
    per cambiare una riga costa il file intero in token, e ogni riga
    rischiata e' una riga potenzialmente corrotta. Qui si passa quello
    che si cerca e quello che lo sostituisce.
    """

    def handler(path: str, trova: str, sostituisci: str,
                all: bool = False, count: int | None = None,
                dry_run: bool = False) -> str:
        if not trova:
            # Una sostituzione vuota non e' un errore di battitura: e' una
            # richiesta palese. Ma senza messaggio il modello non capisce
            # perche' non e' successo niente.
            return ("ERRORE: 'trova' e' vuoto. Una sostituzione vuota "
                    "non ha senso: usa write_file per riscrivere il file.")

        p = _safe_path(path)
        if not p.exists():
            return f"NON ESISTE: {path}"
        if p.is_dir():
            return f"È UNA DIRECTORY: {path} (edit_file modifica un file)"

        try:
            originale = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Un file binario non si modifica a stringhe: si segnala invece
            # di scrivere bytes come se fossero testo.
            return (f"ERRORE: {path} non e' un file di testo UTF-8 "
                    f"(file binario?). Usa write_file solo se sai cosa fai.")

        occorrenze = originale.count(trova)
        if occorrenze == 0:
            return (f"NESSUNA CORRISPONDENZA in {path}: la stringa cercata "
                    f"non c'e'. Leggi il file e riprova con la stringa esatta.")

        if all:
            quante = occorrenze
        elif count is not None:
            quante = max(0, min(int(count), occorrenze))
        else:
            quante = 1

        nuovo, fatte = _sostituisci(originale, trova, sostituisci, quante)
        if fatte == 0:
            return f"NESSUNA SOSTITUZIONE in {path}"

        if dry_run:
            return (f"DRY-RUN: {fatte} sostituzioni su {occorrenze} "
                    f"occorrenze in {path} (nessuna scrittura)")

        p.write_text(nuovo, encoding="utf-8")
        resto = occorrenze - fatte
        msg = f"Sostituite {fatte} occorrenze in {path}"
        if resto:
            # Dire quante ne restano e' il segnale che "all" non e' stato
            # chiesto: il modello vede subito che la modifica e' parziale.
            msg += f" (ne restano {resto}: usa all=true per tutte)"
        return msg

    return Tool(
        name="edit_file",
        description=(
            "Modifica pezzi di file senza riscrivere tutto: sostituisce una "
            "stringa con un'altra. Usalo invece di write_file per i file "
            "grandi. Controlla il contenuto con read_file PRIMA, e passa la "
            "stringa esatta come appare nel file."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Percorso relativo alla root, o ASSOLUTO: un percorso "
                        "fuori dalla root chiede il permesso all'utente."
                    ),
                },
                "trova": {
                    "type": "string",
                    "description": (
                        "Stringa esatta da trovare nel file (copiala da "
                        "read_file, spazi e righe incluse)."
                    ),
                },
                "sostituisci": {
                    "type": "string",
                    "description": "Stringa che la sostituisce.",
                },
                "all": {
                    "type": "boolean",
                    "description": (
                        "Sostituisce TUTTE le occorrenze. Default false: "
                        "solo la prima."
                    ),
                    "default": False,
                },
                "count": {
                    "type": "integer",
                    "description": (
                        "Sostituisce al massimo N occorrenze (alternative a "
                        "all). Default: 1."
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Mostra quante sostituzioni farebbe SENZA scrivere. "
                        "Utile prima di modificare."
                    ),
                    "default": False,
                },
            },
            "required": ["path", "trova", "sostituisci"],
        },
        handler=handler,
    )


if __name__ == '__main__':
    import argparse, sys
    p = argparse.ArgumentParser()
    p.add_argument('path')
    p.add_argument('trova')
    p.add_argument('sostituisci')
    p.add_argument('--all', action='store_true')
    p.add_argument('--count', type=int, default=1)
    p.add_argument('--show', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args(sys.argv[1:])
    result = tool_edit_file().handler(a.path, a.trova, a.sostituisci, all=a.all, count=a.count, dry_run=a.dry_run)
    print(result)
