"""Tool office: scrivere un .docx o un .xlsx vero.

PERCHE' UN TOOL E NON "USA write_file"

`write_file` scrive testo: un CSV lo produce, un .docx no. E un CSV non e'
un preventivo: non ha intestazione, non si apre in Word, non lo mandi a un
cliente senza spiegazioni. Questo tool produce il file che serve, e lo fa
con la stessa guardia dei percorsi degli altri tool di scrittura — un
percorso fuori dalla cartella di lavoro chiede il permesso, e i file
protetti restano negati.

LEGGERE NON E' QUI

Un .docx si legge gia' con `read_file` (e con `office.py` sotto). Questo
tool scrive e basta: due direzioni nella stessa descrizione confondono il
modello, che finirebbe per chiamarlo per leggere un file che ha gia' in
mano.
"""

from __future__ import annotations

from typing import Any

from ..types import Tool
from ._guard import _root, _safe_path
import orchestra.office_scrivi as office_scrivi


def _registra(p, azione: str) -> None:
    """Segna il file come toccato, come fa `write_file`."""
    try:
        from .. import progetti as _pr
        try:
            rel = str(p.relative_to(_root()))
        except Exception:  # noqa: BLE001
            rel = str(p)
        _pr.registra_file(_pr._root_progetto(), rel, azione)
    except Exception:  # noqa: BLE001
        pass


def _dettaglio(percorso, righe: Any, fogli: Any) -> str:
    if percorso.suffix.lower() == ".pdf":
        quante = len(righe or [])
        return (f"PDF, {quante} righe di tabella" if quante
                else "PDF impaginato")
    if percorso.suffix.lower() != ".xlsx":
        return ""
    if fogli:
        nomi = [str((f or {}).get("nome") or "") if isinstance(f, dict) else ""
                for f in fogli]
        quante = sum(len((f or {}).get("righe") or []) if isinstance(f, dict)
                     else len(f or []) for f in fogli)
        return f"{len(fogli)} fogli ({', '.join(n for n in nomi if n)}), " \
               f"{quante} righe totali"
    righe = righe or []
    colonne = max((len(r) for r in righe), default=0)
    return f"{len(righe)} righe x {colonne} colonne"


def tool_office() -> Tool:
    def handler(azione: str = "scrivi", percorso: str = "", formato: str = "",
                titolo: str = "", paragrafi: Any = None,
                righe: Any = None, fogli: Any = None,
                foglio: str = "", intestazione: bool = True) -> str:
        azione = (azione or "scrivi").strip().lower()
        if azione not in ("scrivi", "crea", "write", "aggiungi",
                          "append", "accoda"):
            return ("ERRORE: azione sconosciuta. Questo tool scrive o "
                    "aggiunge: usa `scrivi` o `aggiungi`. Per leggere un "
                    "Office c'e' `read_file`.")
        if not (percorso or "").strip():
            return ("ERRORE: serve `percorso` (per esempio "
                    "'preventivo.pdf', 'preventivo.docx' o 'ore.xlsx').")
        try:
            p = _safe_path(percorso.strip())
            if azione in ("aggiungi", "append", "accoda"):
                # In coda a un file che c'e' gia': nessun checkpoint, perche'
                # un annullamento qui cancellerebbe il lavoro vecchio.
                esito = office_scrivi.aggiungi(
                    p, formato, paragrafi=paragrafi, righe=righe)
                _registra(p, "aggiornato")
                return (f"Aggiunti a {percorso.strip()}: {esito['aggiunti']} "
                        f"{esito['tipo']} ({p.stat().st_size} byte)")
            # Checkpoint prima della scrittura: se il file esisteva, la
            # versione vecchia non esiste piu' dopo l'os.replace.
            try:
                from ..checkpoint import registra as _checkpoint

                _checkpoint(p, _root(), "scrittura")
            except Exception:  # noqa: BLE001 - un lavoro non salvato e' peggio
                pass
            esisteva = p.exists()
            office_scrivi.scrivi(
                p, formato, titolo=titolo, paragrafi=paragrafi,
                righe=righe, fogli=fogli, intestazione=bool(intestazione),
                foglio=foglio or "Foglio1")
            _registra(p, "aggiornato" if esisteva else "creato")
            dettaglio = _dettaglio(p, righe, fogli)
            byte = p.stat().st_size
            return (f"File {'aggiornato' if esisteva else 'creato'}: "
                    f"{percorso.strip()}"
                    + (f" ({dettaglio})" if dettaglio else "")
                    + f", {byte} byte")
        except PermissionError as e:
            return f"ERRORE: {e}"
        except Exception as e:  # noqa: BLE001 - un tool non fa cadere il turno
            return f"ERRORE: {type(e).__name__}: {e}"

    return Tool(
        name="office",
        description=(
            "Writes a real .docx (Word) or .xlsx (Excel) file — a quote, a "
            "letter, a timesheet — inside the working folder. For .docx pass "
            "`titolo` and `paragrafi` (one string per paragraph). For .xlsx "
            "pass `righe` (a list of rows, each a list of cells; numbers stay "
            "numbers), or `fogli` for several sheets, each "
            "{nome, righe}. The first row is formatted as a bold, frozen "
            "header unless `intestazione` is false; column widths follow the "
            "content. A cell that starts with '=' becomes a real formula and "
            "Excel computes it on open — use the English function names "
            "(SUM, AVERAGE, IF), which is what the file format stores. The "
            "extension of `percorso` decides the format unless `formato` is "
            "given. It creates a new file: to read an existing Office file "
            "use read_file, and if the user already has a document to "
            "update, say so instead of writing a second one. It also writes "
            "a .pdf (title, paragraphs, optional `righe` table) and, with "
            "`azione=\"aggiungi\"`, appends paragraphs to an existing .docx "
            "or rows to the first sheet of an existing .xlsx without "
            "touching the rest of the file. A PDF cannot be appended to: "
            "it is written from scratch."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {"type": "string", "description":
                           "scrivi (create/overwrite) or aggiungi (append to "
                           "an existing docx/xlsx)."},
                "percorso": {"type": "string", "description":
                             "Path relative to the project root; .docx, .xlsx "
                             "or .pdf."},
                "formato": {"type": "string", "description":
                            "docx|xlsx, when the path has no extension."},
                "titolo": {"type": "string", "description":
                           "Title, written as the first bold paragraph (docx)."},
                "paragrafi": {"type": "array", "items": {"type": "string"},
                              "description": "Paragraphs, in order (docx)."},
                "righe": {"type": "array", "description":
                          "Rows of cells for one sheet (xlsx) or a table "
                          "(pdf): [[\"Voce\",\"Ore\"],[\"Totale\","
                          "\"=SUM(B2:B2)\"]]."},
                "fogli": {"type": "array", "description":
                          "Several sheets (xlsx): [{\"nome\":\"Gennaio\","
                          "\"righe\":[[...]]}, ...]."},
                "foglio": {"type": "string", "description":
                           "Sheet name when there is one sheet (default Foglio1)."},
                "intestazione": {"type": "boolean", "description":
                                 "Bold and freeze the first row (xlsx, default true)."},
            },
            "required": ["percorso"],
        },
        handler=handler,
    )
