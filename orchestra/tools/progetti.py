"""Il tool `progetti`: guardare i progetti, e annotare quello attivo.

PERCHE' ESISTE

Il blocco progetto nel prompt dice nome, cartella, nota, alias, git e
piani del progetto ATTIVO. Ma le domande che iniziano con "quali
progetti ho?", "cosa avevamo annotato su questo?" o "segnati che il
cliente ha cambiato consegna" non hanno risposta: senza tool, l'agente
deve rimandare alla UI mentre l'utente sta parlando con lui.

COSA NON FA

Non cambia il progetto attivo. Il progetto e' il confine di sicurezza:
sposta la cartella in cui i tool scrivono. Quel cambio resta alla UI e
al riconoscimento deterministico dell'intento (`Session._riconosci_progetto`),
dove c'e' una conferma o una regola esplicita. Un modello che decide da
solo di spostare la root e' il caso peggiore: file scritti nella cartella
sbagliata, e l'utente lo scopre dopo.

`nota` scrive solo sulla nota del progetto ATTIVO: e' testo descrittivo,
e non cambia dove si scrive.
"""

from __future__ import annotations

import time
from typing import Any

from ..types import Tool

# Quanto di una nota entra nell'elenco: la nota intera si legge con
# `stato`. Un elenco di venti progetti con note lunghe non si legge.
MAX_NOTA_ELENCO = 120
MAX_FILE_STATO = 8


def _quando(ts: Any) -> str:
    """Un timestamp in `gg/mm/aaaa`, o "" se non c'e' o non e' un numero.

    `0` vuol dire "mai usato", e non il primo gennaio 1970: una data
    vera e falsa e' peggio di nessuna data.
    """
    try:
        valore = float(ts)
    except (TypeError, ValueError):
        return ""
    if valore <= 0:
        return ""
    try:
        return time.strftime("%d/%m/%Y", time.localtime(valore))
    except (OverflowError, OSError):
        return ""


def _nota_breve(nota: str) -> str:
    testo = " ".join((nota or "").split())
    if len(testo) <= MAX_NOTA_ELENCO:
        return testo
    return testo[:MAX_NOTA_ELENCO].rstrip() + "…"


def _attivo() -> str:
    """Il NOME del progetto attivo, o "".

    `progetti.progetto_attivo` guarda il nome nel thread e, se manca,
    risale dalla cartella di lavoro a un progetto registrato: e' il
    caso della CLI, dove il nome non lo imposta la UI.
    """
    try:
        from .. import progetti as _pr

        return (_pr.progetto_attivo() or "").strip()
    except Exception:  # noqa: BLE001 - senza progetto si dice, non si indovina
        return ""


def tool_progetti() -> Tool:
    def elenca(limite: int = 50) -> str:
        """Tutti i progetti registrati, con percorso, nota e ultimo uso."""
        from .. import progetti as _pr

        try:
            tutti = _pr.tutti()
        except Exception as e:  # noqa: BLE001
            return f"Non riesco a leggere i progetti: {type(e).__name__}: {e}"
        if not tutti:
            return ("Nessun progetto registrato. Si creano dalla UI, "
                    "pannello Progetti: il tool non cambia il progetto attivo.")
        try:
            limite = max(1, min(int(limite), 200))
        except (TypeError, ValueError):
            limite = 50
        attivo = _attivo()
        righe = [f"{len(tutti)} progetti registrati"
                 + (f" (attivo: {attivo})" if attivo else "") + ":", ""]
        for p in tutti[:limite]:
            nome = str(p.get("nome") or "").strip()
            if not nome:
                continue
            percorso = str(p.get("percorso") or "").strip()
            nota = _nota_breve(str(p.get("note") or ""))
            ultimo = _quando(p.get("ultimo_use"))
            n_file = p.get("n_file")
            segno = " (attivo)" if attivo and nome.lower() == attivo.lower() else ""
            riga = f"- {nome}{segno}: `{percorso}`"
            if nota:
                riga += f"; nota: {nota}"
            if ultimo:
                riga += f"; ultimo uso: {ultimo}"
            try:
                quanti = int(n_file or 0)
            except (TypeError, ValueError):
                quanti = 0
            if quanti == 1:
                riga += "; 1 file toccato"
            elif quanti > 1:
                riga += f"; {quanti} file toccati"
            righe.append(riga)
        if len(tutti) > limite:
            righe.append(f"[altri progetti non mostrati: "
                         f"{len(tutti) - limite}. Alza `limite`.]")
        return "\n".join(righe)

    def stato() -> str:
        """La scheda del progetto attivo: percorso, nota, alias, file."""
        from .. import progetti as _pr

        nome = _attivo()
        if not nome:
            return ("Nessun progetto attivo: si lavora nella cartella di "
                    "installazione. Il progetto si sceglie dalla UI o "
                    "chiedendolo in una frase (\"lavoriamo al sito\").")
        try:
            riga = _pr.per_nome(nome)
        except Exception as e:  # noqa: BLE001
            return f"Non riesco a leggere i progetti: {type(e).__name__}: {e}"
        if not riga:
            return (f"Il progetto attivo «{nome}» non e' fra quelli "
                    f"registrati: la cartella resta quella globale.")
        righe = [f"Progetto attivo: {nome}",
                 f"Cartella: `{riga.get('percorso') or ''}`"]
        nota = " ".join(str(riga.get("note") or "").split())
        if nota:
            righe.append(f"Nota: {nota}")
        try:
            alias = _pr.alias_di(riga)
        except Exception:  # noqa: BLE001
            alias = []
        if alias:
            righe.append("Chiamato anche: " + ", ".join(alias))
        ultimo = _quando(riga.get("ultimo_use"))
        if ultimo:
            righe.append(f"Ultimo uso: {ultimo}")
        try:
            recenti = _pr.file_toccati(nome, limite=MAX_FILE_STATO)
        except Exception:  # noqa: BLE001
            recenti = []
        percorsi: list[str] = []
        for f in recenti:
            percorso = str(f.get("path") or "").strip()
            if percorso and percorso not in percorsi:
                percorsi.append(percorso)
        if percorsi:
            righe.append("Ultimi file toccati: "
                         + ", ".join(f"`{x}`" for x in percorsi))
        righe.append("Per cambiare progetto serve la UI (o dirlo in una "
                     "frase): questo tool non sposta la cartella.")
        return "\n".join(righe)

    def nota(testo: str = "") -> str:
        """Scrive la nota del progetto ATTIVO. Non cambia il progetto."""
        from .. import progetti as _pr

        nome = _attivo()
        if not nome:
            return ("Nessun progetto attivo: la nota appartiene a un "
                    "progetto, e non c'e'. Attivane uno dalla UI, poi "
                    "richiama `nota`.")
        try:
            riga = _pr.per_nome(nome)
        except Exception as e:  # noqa: BLE001
            return f"Non riesco a leggere i progetti: {type(e).__name__}: {e}"
        if not riga:
            return (f"Il progetto attivo «{nome}» non e' registrato: "
                    f"non posso annotare niente.")
        percorso = str(riga.get("percorso") or "")
        # `alias=None` vuol dire "non toccare gli alias": qui si cambia
        # solo la nota, e il percorso resta quello registrato.
        try:
            _pr.registra(nome, percorso, note=testo or "")
        except Exception as e:  # noqa: BLE001
            return f"Non riesco a salvare la nota: {type(e).__name__}: {e}"
        pulita = " ".join((testo or "").split())
        if not pulita:
            return f"Nota del progetto «{nome}» svuotata."
        if len(pulita) > MAX_NOTA_ELENCO:
            pulita = pulita[:MAX_NOTA_ELENCO].rstrip() + "…"
        return f"Nota del progetto «{nome}» aggiornata: {pulita}"

    def handler(azione: str = "elenca", limite: int = 50,
                testo: str = "") -> str:
        try:
            azione = (azione or "elenca").strip().lower()
            if azione == "elenca":
                return elenca(limite)
            if azione == "stato":
                return stato()
            if azione == "nota":
                return nota(testo)
            return ("Azione non riconosciuta: " + azione
                    + ". Puoi fare: elenca, stato, nota.")
        except Exception as e:  # noqa: BLE001 - un tool non uccide il turno
            return f"Errore nei progetti: {type(e).__name__}: {e}"

    return Tool(
        name="progetti",
        description=(
            "Lists registered projects (path, note, last use), shows the "
            "active project's card (path, note, aliases, recent files), and "
            "updates the active project's note. It NEVER changes the active "
            "project: switching stays in the UI or in the deterministic "
            "intent recognition, because it moves the folder tools write to."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {
                    "type": "string",
                    "enum": ["elenca", "stato", "nota"],
                    "description": (
                        "elenca (list every project), stato (card of the "
                        "active project), nota (write the active project's "
                        "note). Default: elenca."
                    ),
                },
                "limite": {
                    "type": "integer",
                    "description": "How many projects to list. Default 50.",
                },
                "testo": {
                    "type": "string",
                    "description": (
                        "The new note, for azione='nota'. Empty clears it. "
                        "Only meaningful for the active project."
                    ),
                },
            },
        },
        handler=handler,
    )
