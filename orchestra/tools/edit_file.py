"""Tool edit_file: sostituire una o più parti di un file senza riscriverlo.

E' nato come script a sé in `orchestra/tools/`, e per questo motivo non
era mai stato visto dall'agente: `orchestra/tools.py` (modulo) e
`orchestra/tools/` (cartella) hanno lo stesso nome, e senza `__init__.py`
Python ignora la cartella — `import orchestra.tools.edit_file` fallisce con
`__path__ attribute not found`. Il file c'era, ma non era importabile.

Ora il pacchetto esiste e il tool sta dentro, importabile come gli altri.

Accetta anche una lista di sostituzioni (`modifiche`): si legge il file una
volta, si applicano in ordine, e si scrive una volta sola con un solo
checkpoint. Se una voce non trova la sua stringa non si scrive niente: un
batch a metà è peggio di un batch fallito, perché la prima metà non si
distingue dal resto.
"""

from __future__ import annotations

from ..testo import codifica, decodifica, tipo_binario
from ..types import Tool
from ._guard import _root, _safe_path


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


def _prepara(testo: str, trova: str, sostituisci: str) -> tuple[str, str, int]:
    """La stringa da cercare, quella che la sostituisce, e quante volte c'è.

    Il ripiego sui fine riga vale per OGNI voce del batch: dopo la prima
    sostituzione il testo è ancora quello del file (CRLF), e la voce
    successiva copiata da `read_file` porta i `\\n`. Calcolare le occorrenze
    una volta sola all'inizio darebbe risultati sbagliati appena una
    sostituzione cambia il testo.
    """
    cerca, metti = trova, sostituisci
    occorrenze = testo.count(cerca)
    if occorrenze == 0 and "\r\n" in testo:
        # Il modello copia le righe da read_file, che mostra il testo
        # con i \n (splitlines li toglie): su un file CRLF una ricerca
        # multilinea copiata cosi' non combacia, e il tool risponderebbe
        # "NESSUNA CORRISPONDENZA" su una stringa che esiste. Si riprova
        # con i fine riga del file, e la sostituzione adotta gli
        # stessi, altrimenti si mescolano due stili nello stesso file.
        altra = trova.replace("\r\n", "\n").replace("\n", "\r\n")
        if altra != trova and testo.count(altra):
            cerca = altra
            metti = sostituisci.replace("\r\n", "\n").replace("\n", "\r\n")
            occorrenze = testo.count(cerca)
    return cerca, metti, occorrenze


def tool_edit_file() -> Tool:
    """Sostituisce una o più stringhe in un file, senza riscriverlo tutto.

    E' la differenza con `write_file`: riscrivere un file di 2000 righe
    per cambiare una riga costa il file intero in token, e ogni riga
    rischiata e' una riga potenzialmente corrotta. Qui si passa quello
    che si cerca e quello che lo sostituisce.
    """

    def handler(path: str, trova: str = "", sostituisci: str = "",
                all: bool = False, count: int | None = None,
                dry_run: bool = False, modifiche: list | None = None) -> str:
        # Due modi per la stessa cosa: una sostituzione, o un elenco.
        # Mescolarli non e' ambiguo per il codice ma lo e' per il
        # risultato: si rifiuta, invece di scegliere in silenzio.
        if modifiche is not None and not isinstance(modifiche, (list, tuple)):
            return ("ERRORE: 'modifiche' deve essere una lista di oggetti "
                    "{trova, sostituisci}.")
        voci_batch = list(modifiche or [])
        if voci_batch and (trova or sostituisci):
            return ("ERRORE: usa o 'trova'/'sostituisci' per una sola "
                    "sostituzione, o 'modifiche' per piu' sostituzioni: "
                    "non entrambi.")
        if voci_batch and (all or count is not None):
            return ("ERRORE: con 'modifiche', metti 'all' e 'count' dentro "
                    "ogni voce, non fuori.")
        if not voci_batch and not trova:
            # Una sostituzione vuota non e' un errore di battitura: e' una
            # richiesta palese. Ma senza messaggio il modello non capisce
            # perche' non e' successo niente.
            return ("ERRORE: 'trova' e' vuoto. Una sostituzione vuota "
                    "non ha senso: usa write_file per riscrivere il file, "
                    "oppure passa 'modifiche'.")

        if voci_batch:
            voci = []
            for i, voce in enumerate(voci_batch, 1):
                if not isinstance(voce, dict):
                    return (f"ERRORE: la modifica {i} non e' un oggetto "
                            f"{{trova, sostituisci}}.")
                t = str(voce.get("trova") or "")
                if not t:
                    return (f"ERRORE: la modifica {i} ha 'trova' vuoto. "
                            f"Una sostituzione vuota non ha senso.")
                s = voce.get("sostituisci")
                voci.append({
                    "trova": t,
                    "sostituisci": "" if s is None else str(s),
                    "all": bool(voce.get("all")),
                    "count": voce.get("count"),
                })
        else:
            voci = [{"trova": trova, "sostituisci": sostituisci,
                     "all": bool(all), "count": count}]

        p = _safe_path(path)
        if not p.exists():
            return f"NON ESISTE: {path}"
        if p.is_dir():
            return f"È UNA DIRECTORY: {path} (edit_file modifica un file)"

        # I byte, non il testo tradotto: `read_text` con il default
        # converte ogni \r\n in \n, e riscrivere il risultato toglieva i
        # fine riga CRLF da TUTTO il file. Una sostituzione di una riga
        # faceva comparire il file intero nel diff — su un repo Windows e'
        # un danno che si vede solo dopo, quando il commit e' grande come
        # il file.
        try:
            dati = p.read_bytes()
        except OSError as e:
            return f"NON RIESCO A LEGGERLO: {path}: {e}"
        tipo = tipo_binario(dati)
        if tipo:
            # Un file binario non si modifica a stringhe: si segnala con
            # quello che e' davvero, invece di dire "file binario?" a un
            # .txt in cp1252 (che e' testo, solo non UTF-8).
            return (f"ERRORE: {path} e' {tipo}, non un file di testo: "
                    f"modificarlo a stringhe lo corromperebbe.")
        # L'encoding lo decide `testo.decodifica`, lo stesso che usa
        # read_file: due tool che leggono lo stesso file in due modi
        # diversi danno due verita' diverse, e l'utente non sa quale
        # credere.
        originale, codifica_file = decodifica(dati)

        nuovo = originale
        totale = 0
        dettagli: list[tuple[int, int, int]] = []
        for i, voce in enumerate(voci, 1):
            # Le occorrenze si contano sul testo GIA' modificato dalle voci
            # precedenti: e' l'ordine che il chiamante ha chiesto, e una
            # voce puo' cercare qualcosa che la voce prima ha appena
            # creato.
            cerca, metti, occorrenze = _prepara(
                nuovo, voce["trova"], voce["sostituisci"])
            if occorrenze == 0:
                if len(voci) == 1:
                    return (f"NESSUNA CORRISPONDENZA in {path}: la stringa "
                            f"cercata non c'e'. Leggi il file e riprova con "
                            f"la stringa esatta.")
                return (f"NESSUNA CORRISPONDENZA in {path}, modifica {i}: "
                        f"la stringa cercata non c'e'. Nessuna scrittura: "
                        f"il file e' intatto.")

            if voce["all"]:
                quante = occorrenze
            elif voce["count"] is not None:
                try:
                    quante = max(0, min(int(voce["count"]), occorrenze))
                except (TypeError, ValueError):
                    return (f"ERRORE: 'count' non valido nella modifica {i}: "
                            f"{voce['count']!r}.")
            else:
                quante = 1

            nuovo, fatte = _sostituisci(nuovo, cerca, metti, quante)
            if fatte == 0:
                return f"NESSUNA SOSTITUZIONE in {path} (modifica {i})"
            totale += fatte
            dettagli.append((i, fatte, occorrenze))

        if dry_run:
            if len(voci) == 1:
                _, fatte, occorrenze = dettagli[0]
                return (f"DRY-RUN: {fatte} sostituzioni su {occorrenze} "
                        f"occorrenze in {path} (nessuna scrittura)")
            righe = [f"  {i}. {fatte} su {occorrenze}"
                     for i, fatte, occorrenze in dettagli]
            return (f"DRY-RUN: {totale} sostituzioni in {path} "
                    f"({len(voci)} modifiche, nessuna scrittura)\n"
                    + "\n".join(righe))

        # Checkpoint UNA volta, prima dell'unica scrittura: se una voce
        # fallisce, il file non e' stato toccato e non c'e' niente da
        # annullare; se arriviamo qui, la versione vecchia e' ancora quella
        # da salvare.
        try:
            from ..checkpoint import registra

            registra(p, _root(), "modifica")
        except Exception:  # noqa: BLE001
            pass
        # Atomica anche qui: questa riscrive il file intero, quindi vale
        # lo stesso rischio di write_file. E nella codifica del file: un
        # .txt cp1252 modificato non deve tornare indietro come UTF-8,
        # altrimenti l'encoding l'ha cambiato il tool, non l'utente.
        from ..scrittura import scrivi_bytes

        try:
            scrivi_bytes(p, codifica(nuovo, codifica_file))
        except OSError as e:
            return f"MODIFICA FALLITA: {path}: {e} (il file non e' stato toccato)"
        resto = sum(occ - fatte for _, fatte, occ in dettagli)
        msg = f"Sostituite {totale} occorrenze in {path}"
        if len(voci) > 1:
            msg += f" ({len(voci)} modifiche)"
        if resto:
            # Dire quante ne restano e' il segnale che "all" non e' stato
            # chiesto: il modello vede subito che la modifica e' parziale.
            msg += (f" (ne restano {resto}: usa all=true nella voce "
                    f"corrispondente per tutte)")
        return msg

    return Tool(
        name="edit_file",
        description=(
            "Edits a file without rewriting it from scratch. Pass ONE "
            "replacement with `trova`/`sostituisci`, or SEVERAL with "
            "`modifiche` (a list of {trova, sostituisci, all?, count?} "
            "applied in order). A batch is atomic: every pattern must "
            "match, it gets ONE checkpoint and ONE write, and if any "
            "pattern is missing nothing is written. Read the content with "
            "read_file FIRST, and pass the exact strings as they appear "
            "in the file."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path relative to the project root, or ABSOLUTE: a "
                        "path outside the root asks the user for permission."
                    ),
                },
                "trova": {
                    "type": "string",
                    "description": (
                        "Single replacement: exact string to find in the "
                        "file (copy it from read_file, whitespace and line "
                        "breaks included). For several, use `modifiche`."
                    ),
                },
                "sostituisci": {
                    "type": "string",
                    "description": (
                        "Single replacement: string that replaces it. "
                        "Empty deletes the match."
                    ),
                },
                "all": {
                    "type": "boolean",
                    "description": (
                        "Single replacement: replace EVERY occurrence. "
                        "Default false: only the first one. In a batch, set "
                        "`all` on each item."
                    ),
                    "default": False,
                },
                "count": {
                    "type": "integer",
                    "description": (
                        "Single replacement: replace at most N occurrences "
                        "(alternative to `all`). Default: 1. In a batch, set "
                        "`count` on each item."
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Reports how many replacements it would make WITHOUT "
                        "writing. Useful before changing anything; it works "
                        "for a batch too."
                    ),
                    "default": False,
                },
                "modifiche": {
                    "type": "array",
                    "description": (
                        "Batch: replacements to apply in order. Each item is "
                        "{trova, sostituisci, all?, count?}. Use INSTEAD of "
                        "`trova`/`sostituisci`. All patterns must match; if "
                        "one is missing, nothing is written. One checkpoint "
                        "and one write for the whole batch."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "trova": {
                                "type": "string",
                                "description": (
                                    "Exact string to find, at this point in "
                                    "the sequence."
                                ),
                            },
                            "sostituisci": {
                                "type": "string",
                                "description": (
                                    "String that replaces it. Empty deletes "
                                    "the match."
                                ),
                            },
                            "all": {
                                "type": "boolean",
                                "description": (
                                    "Replace every occurrence of this item. "
                                    "Default false: only the first."
                                ),
                                "default": False,
                            },
                            "count": {
                                "type": "integer",
                                "description": (
                                    "Replace at most N occurrences of this "
                                    "item (alternative to `all`). Default: 1."
                                ),
                            },
                        },
                        "required": ["trova", "sostituisci"],
                    },
                },
            },
            "required": ["path"],
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
