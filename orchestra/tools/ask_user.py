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
            "Fa UNA domanda all'utente e aspetta la risposta, dentro lo "
            "stesso turno. Usalo quando un'informazione che non puoi "
            "ricavare dagli strumenti cambia quello che stai per fare: "
            "un nome, quale dei due file, un requisito ambiguo. Non usarlo "
            "per chiedere permesso (lo fa gia' lo strumento) e non per "
            "confermare che il lavoro va bene: quello lo vede l'utente."),
        schema={
            "type": "object",
            "properties": {
                "domanda": {
                    "type": "string",
                    "description": "La domanda, in una frase. Dì perche' la fai e cosa cambia in base alla risposta.",
                },
                "opzioni": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fino a 6 risposte probabili, mostrate come scorciatoie. La risposta resta libera.",
                },
            },
            "required": ["domanda"],
        },
        handler=handler,
    )
