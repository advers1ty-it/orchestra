"""Tool ask_user: una domanda di chiarimento, e si aspetta la risposta."""

from __future__ import annotations

from ..types import Tool

NESSUN_CANALE = (
    "NESSUNO A CUI CHIEDERE: qui non c'e' un canale per le domande "
    "(CLI, benchmark o test). Non aspettare. Scegli l'ipotesi piu' "
    "probabile, dichiarala in una riga e continua; se la scelta cambia "
    "tutto il lavoro, fermati e spiega in una riga cosa ti serve."
)


def tool_ask_user() -> Tool:
    def handler(domanda: str, opzioni: list[str] | None = None) -> str:
        from .. import domande

        try:
            d = domande.crea(domanda, opzioni)
        except ValueError as e:
            return f"ERRORE: {e}. Scrivi una domanda vera, in una frase."
        if not domande.invia(d):
            # La domanda e' stata registrata ma non e' arrivata a nessuno:
            # senza questo resta in attesa per sempre, e la prossima
            # domanda trova un fantasma davanti.
            domande.annulla(d["id"])
            return NESSUN_CANALE
        risposta = domande.attendi(d["id"])
        if risposta is None:
            return (
                "NESSUNA RISPOSTA entro cinque minuti: la domanda e' "
                "scaduta. Non ripeterla uguale. Scegli l'ipotesi piu' "
                "probabile, dichiarala e continua.")
        return (f"Risposta dell'utente: {risposta}\n"
                "Usala come dato. Non fare la stessa domanda di nuovo.")

    return Tool(
        name="ask_user",
        description=(
            "Asks the user ONE question and waits for the answer, inside the "
            "same turn. Use it when a piece of information you cannot get "
            "from the tools changes what you are about to do: a name, which "
            "of the two files, an ambiguous requirement. Do not use it to "
            "ask permission (the tool does that already) nor to confirm the "
            "work is fine: the user can see it."),
        schema={
            "type": "object",
            "properties": {
                "domanda": {
                    "type": "string",
                    "description": (
                        "The question, in one sentence. Say why you ask and "
                        "what changes with the answer."
                    ),
                },
                "opzioni": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Up to 6 likely answers, shown as shortcuts. The "
                        "answer stays free."
                    ),
                },
            },
            "required": ["domanda"],
        },
        handler=handler,
    )
