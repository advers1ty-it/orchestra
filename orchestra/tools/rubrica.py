"""Tool rubrica: cercare, aggiungere e correggere i contatti.

PERCHE' NON BASTAVA LA POSTA

Cercare "l'email di Mario" dentro la casella funziona finche' Mario ti ha
scritto. Un fornitore nuovo, il dentista, l'idraulico: non ci sono. La
rubrica e' il posto dove un contatto esiste anche prima del primo
messaggio, e dove `cerca` risponde in una riga invece che in venti.

La regola dei doppioni sta nel modulo (`aggiungi` aggiorna invece di
duplicare): qui si dice all'agente di usarla, invece di lasciarlo
indovinare fra "aggiungi" e "modifica".
"""

from __future__ import annotations

from typing import Any

from ..types import Tool
import orchestra.rubrica as rubrica_mod


def _elenco(contatti: list[dict[str, Any]], titolo: str) -> str:
    if not contatti:
        return f"{titolo}: nessun contatto."
    righe = [f"{titolo} ({len(contatti)}):"]
    righe.extend("  " + rubrica_mod.formatta(c) for c in contatti)
    return "\n".join(righe)


def tool_rubrica() -> Tool:
    def handler(azione: str = "cerca", testo: str = "", id: str = "",
                nome: str = "", email: str = "", telefono: str = "",
                azienda: str = "", note: str = "") -> str:
        azione = (azione or "cerca").strip().lower()
        try:
            if azione in ("cerca", "trova", "search"):
                contatti = rubrica_mod.cerca(testo)
                quanto = f"Contatti con '{testo}'" if testo.strip() else "Rubrica"
                return _elenco(contatti, quanto)

            if azione in ("aggiungi", "crea", "add", "salva"):
                salvato = rubrica_mod.aggiungi(
                    nome=nome, email=email, telefono=telefono,
                    azienda=azienda, note=note)
                verbo = "aggiornato" if salvato.get("aggiornato") else "aggiunto"
                return (f"Contatto {verbo}: " + rubrica_mod.formatta(salvato))

            if azione in ("modifica", "aggiorna", "edit"):
                if not (id or "").strip():
                    return ("ERRORE: serve `id` per modificare un contatto "
                            "(lo trovi con cerca).")
                cambiato = rubrica_mod.modifica(
                    id, nome=nome, email=email, telefono=telefono,
                    azienda=azienda, note=note)
                if cambiato is None:
                    return f"ERRORE: nessun contatto con id {id}."
                return "Contatto aggiornato: " + rubrica_mod.formatta(cambiato)

            if azione in ("elimina", "cancella", "delete"):
                if not (id or "").strip():
                    return "ERRORE: serve `id` per eliminare un contatto."
                if rubrica_mod.elimina(id):
                    return f"Contatto eliminato: {id}"
                return f"ERRORE: nessun contatto con id {id}."

            if azione in ("conta", "stato"):
                return f"Contatti in rubrica: {rubrica_mod.conta()}."

            return ("ERRORE: azione sconosciuta. Usa: cerca, aggiungi, "
                    "modifica, elimina, conta.")
        except ValueError as e:
            return f"ERRORE: {e}"
        except Exception as e:  # noqa: BLE001 - un tool non fa cadere il turno
            return f"ERRORE: {type(e).__name__}: {e}"

    return Tool(
        name="rubrica",
        description=(
            "The user's address book: name, email, phone, company, notes. "
            "The `azione` values are: `cerca` (testo: matches any field, and "
            "phone numbers also match digit by digit), `aggiungi` "
            "(nome/email/telefono/azienda/note — a contact with the same "
            "email is UPDATED, not duplicated), `modifica` (id plus the "
            "fields to change), `elimina` (id), `conta`. "
            "Use it before asking the user 'who is this person?', and before "
            "sending a mail to an address you are not sure about. Never "
            "invent a contact: if it is not there, say so."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {"type": "string", "description":
                           "cerca|aggiungi|modifica|elimina|conta "
                           "(search|add|edit|delete|count)."},
                "testo": {"type": "string", "description":
                          "Text to search in every field (for cerca)."},
                "id": {"type": "string", "description":
                       "Contact id (for modifica/elimina)."},
                "nome": {"type": "string", "description": "Full name."},
                "email": {"type": "string", "description": "Email address."},
                "telefono": {"type": "string", "description": "Phone number."},
                "azienda": {"type": "string", "description": "Company."},
                "note": {"type": "string", "description": "Free notes."},
            },
            "required": [],
        },
        handler=handler,
    )
