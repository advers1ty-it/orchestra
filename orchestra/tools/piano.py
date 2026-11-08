"""Tool proponi_piano: il piano si mostra prima, non dopo.

In modalita' piano i tool che modificano sono bloccati. Questo e' l'unico
modo per sbloccarli, e passa da una risposta esplicita dell'utente: una
modale con il piano, due scorciatoie («Approva il piano», «Rifiuta») e la
risposta libera per chiedere una modifica.

PERCHE' NON RIUSA IL TESTO DELLA RISPOSTA FINALE

Un modello che scrive il piano come risposta finale chiude il turno, e
l'approvazione arriverebbe al messaggio dopo — quando il contesto del
lavoro e' ancora li' ma l'agente non sa piu' di essere in attesa. Qui il
turno resta aperto, come per `ask_user`: il modello riceve l'esito e
continua (o si ferma) dentro lo stesso turno.
"""

from __future__ import annotations

from .. import piano as piano_mod
from ..types import Tool

OPZIONE_APPROVA = "Approva il piano"
OPZIONE_RIFIUTA = "Rifiuta"

# Come si legge la risposta. Il default e' NO: un piano si esegue solo
# se l'utente ha detto di si', non se ha scritto qualcosa che non sembra
# un no. Sbagliare in questa direzione costa un clic; sbagliare
# nell'altra esegue modifiche che nessuno ha approvato.
_POSITIVE = ("approva", "approvo", "approvato", "ok", "okay", "vai",
             "procedi", "si", "sì", "yes", "va bene", "d'accordo")
_NEGATIVE = ("rifiut", "annull", "aspetta", "fermati", "cambia",
             "modifica", "invece", "non va", "non approv")


def _approvato(risposta: str) -> bool:
    t = " ".join((risposta or "").lower().split())
    if not t:
        return False
    # «No, ...» e «Non ...» vengono prima di tutto, anche prima
    # dell'opzione: un "no" esplicito non si legge come un si'.
    if t == "no" or t.startswith(("no ", "no,", "non ")):
        return False
    # Il bottone, e le risposte che cominciano con un'assenso. Un
    # «approvo, ma togli il passo 3» e' un via libera con una nota: la
    # nota torna al modello e va rispettata.
    if t.startswith(_POSITIVE):
        return True
    if any(n in t for n in _NEGATIVE):
        return False
    return False


def tool_proponi_piano() -> Tool:
    def handler(piano: str, passi: list[str] | None = None) -> str:
        from .. import domande

        testo = (piano or "").strip()
        if not testo:
            return ("ERRORE: il piano e' vuoto. Scrivi i passi veri, uno "
                    "per riga, e cosa cambiera' in ognuno.")
        if passi:
            elenco = "\n".join(
                f"{i + 1}. {str(p).strip()}"
                for i, p in enumerate(passi) if str(p).strip())
            if elenco:
                testo = f"{testo}\n\n{elenco}"

        try:
            d = domande.crea(testo, [OPZIONE_APPROVA, OPZIONE_RIFIUTA],
                             tipo="piano")
        except ValueError as e:
            return f"ERRORE: {e}"
        if not domande.invia(d):
            # Senza canale non si puo' approvare niente. Il turno resta
            # bloccato: e' la scelta giusta in CLI e nel benchmark, dove
            # non c'e' nessuno che possa dire "va bene".
            domande.annulla(d["id"])
            return (
                "PIANO NON APPROVATO: qui non c'e' nessuno a cui chiedere "
                "(CLI, benchmark o test). Non eseguire modifiche. Scrivi il "
                "piano come risposta finale, in una riga per passo, e "
                "fermati: l'utente lo leggerà e rilancerà con le "
                "indicazioni."
            )
        risposta = domande.attendi(d["id"])
        if risposta is None:
            return (
                "PIANO NON APPROVATO: nessuna risposta entro cinque minuti. "
                "Non eseguire modifiche. Chiudi il turno spiegando in una "
                "riga il piano e cosa manca per partire."
            )
        if _approvato(risposta):
            piano_mod.approva()
            extra = ""
            if risposta.strip().lower() != OPZIONE_APPROVA.lower():
                extra = (f"\nNota dell'utente da rispettare: {risposta}\n"
                         f"Se la nota cambia il piano, segui la nota.")
            return (
                "PIANO APPROVATO. Da adesso, per questo turno, i tool che "
                "modificano sono disponibili." + extra + "\n"
                "Esegui i passi. Non rifare la stessa domanda, non "
                "allargarti oltre il piano approvato."
            )
        return (
            f"PIANO NON APPROVATO. L'utente ha risposto: «{risposta}».\n"
            "Non eseguire modifiche. Se la risposta chiede cambiamenti, "
            "proponi un piano aggiornato con `proponi_piano`; se chiede di "
            "fermarti, chiudi il turno con una riga. Non insistere con lo "
            "stesso piano."
        )

    return Tool(
        name="proponi_piano",
        description=(
            "Shows the user the work plan and waits for approval, inside the "
            "same turn. Required when plan mode is on and you want to change "
            "files or run commands: until the plan is approved those tools "
            "stay locked. Use it outside plan mode too for work that touches "
            "several files or changes something the user can see."
        ),
        schema={
            "type": "object",
            "properties": {
                "piano": {
                    "type": "string",
                    "description": ("The plan, in readable text: what you "
                                    "understood and what you will do. One "
                                    "line per point."),
                },
                "passi": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("The concrete steps, one per item: files "
                                    "touched, commands, what changes."),
                },
            },
            "required": ["piano"],
        },
        handler=handler,
    )
