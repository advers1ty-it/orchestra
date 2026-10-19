"""
Il tool `memoria`: l'agente cerca quello che gli serve, quando gli serve.

PERCHÉ NON SI INIETTA PIÙ TUTTO

Iniettare la memoria intera nel system prompt costa token in proporzione
a quanto ricordi. Un `memory.md` che cresce per mesi avvelena il
contesto di OGNI richiesta — comprese quelle che non c'entrano niente con
quello che c'è salvato. Il costo è pagato sempre, il beneficio quasi mai.

Adesso nel system prompt finisce solo una riga che dice che la memoria
esiste e come si consulta. Il contenuto lo tira fuori l'agente con una
ricerca, e paga solo per quello che gli serve.

Un sottoinsieme breve — i fatti con priorità — lo inietta ancora, perché
c'è un pugno di cose che devono essere vere sempre (chi sei, su cosa
stiamo lavorando). Sono quelle marcate `alta` e stanno sotto un tetto
stretto: se sforano, escono dal prompt e restano trovabili per ricerca.
"""

from __future__ import annotations

from typing import Any

from ..memoria import memoria as _memoria_file
from ..memoria_indice import indice_memoria


def memoria():
    """La memoria con l'indice FTS5, se c'è; altrimenti il file.

    L'indice è uno strato SOPRA il file, non un sostituto: se il database
    non si può aprire si torna al file e la memoria funziona lo stesso,
    solo con la ricerca per sottostringa. Un'indisponibilità dell'indice
    non deve far perdere i fatti.
    """
    try:
        return indice_memoria()
    except Exception:
        return _memoria_file()


from ..types import Tool

# Quanto entra nel system prompt senza che nessuno chieda niente.
# TETTO_CARATTERI in memoria.py è 20.000: qui siamo a un ventesimo, ed è
# voluto. Quella è la dimensione massima della memoria, questa è quanto
# possiamo permetterci di ripetere a ogni turno.
TETTO_PROMPT = 1_000


def fatti_importanti() -> list[str]:
    """I fatti da iniettare sempre: quelli marcati `alta`.

    Non è una classifica di importanza decisa da noi: è una marcatura che
    mette chi scrive il fatto. Se uno non l'ha marcato, non è che valga
    meno — è che non va ripetuto a ogni turno.
    """
    try:
        m = memoria()
    except Exception:
        return []
    # separazione per posizione, non per marcatura: i fatti importanti
    # stanno nella loro sezione del file
    return m.importanti()


def blocco_prompt() -> str:
    """Il pezzo di memoria che entra nel system prompt.

    Vuoto se non c'è niente marcato: una sezione "preferenze" vuota
    insegna al modello a parlare della memoria invece di usarla.
    """
    importanti = fatti_importanti()
    if not importanti:
        return ""
    testo = "\n".join(f"- {f}" for f in importanti)
    if len(testo) > TETTO_PROMPT:
        testo = testo[:TETTO_PROMPT] + "\n- [altri fatti: cerca nella memoria]"
    return testo


def tool_memoria() -> Tool:
    """Il tool. Quattro azioni, una per domanda diversa."""

    def cerca(query: str = "", limite: int = 10) -> str:
        """Cerca fra i fatti. È l'azione che sostituisce l'iniezione totale."""
        m = memoria()
        tutti = m.fatti()
        if not tutti:
            return "Nessun fatto in memoria."
        q = (query or "").strip().lower()
        if not q:
            # senza query non è una ricerca: sono i più recenti, che è
            # quello che serve a chi non sa ancora cosa c'è
            ultimi = tutti[-limite:]
            return "\n".join(f"- {f}" for f in ultimi)
        # le parole contano tutte: una ricerca a una sola parola su una
        # memoria lunga torna troppo, e torna roba che non c'entra
        parole = [p for p in q.split() if p]
        trovati = [
            f for f in tutti
            if all(p in f.lower() for p in parole)
        ]
        if not trovati:
            # nessun risultato con tutte le parole: si riprova con una
            # sola, che è la ricerca che l'agente fa davvero
            trovati = [f for f in tutti if any(p in f.lower() for p in parole)]
        if not trovati:
            return f"Nessun fatto trovato per: {query}"
        return "\n".join(f"- {f}" for f in trovati[:limite])

    def aggiungi(fatto: str = "", priorita: str = "") -> str:
        """Aggiunge un fatto. `priorita` = "alta" lo mette nel prompt."""
        fatto = (fatto or "").strip()
        if not fatto:
            return "Fatto vuoto: non ho niente da ricordare."
        m = memoria()
        alta = priorita.strip().lower() == "alta"
        nuovo = m.aggiungi(fatto, origine="agente", importante=alta)
        if not nuovo:
            return f"Era già in memoria: {fatto}"
        return ("Ricordato" + (" (priorità alta)" if alta else "") + f": {fatto}")

    def elimina(fatto: str = "") -> str:
        """Toglie un fatto. Non chiede conferma: la memoria è dell'utente."""
        fatto = (fatto or "").strip()
        if not fatto:
            return "Quale fatto? Serve il testo."
        if memoria().elimina(fatto):
            return f"Dimenticato: {fatto}"
        return f"Non l'ho trovato in memoria: {fatto}"

    def modifica(vecchio: str = "", nuovo: str = "") -> str:
        """Riscrive un fatto esistente, tenendo data e origine."""
        if not (vecchio or "").strip() or not (nuovo or "").strip():
            return "Servono il fatto da cambiare e il testo nuovo."
        if memoria().modifica(vecchio, nuovo):
            return f"Modificato: {nuovo}"
        return f"Non l'ho trovato in memoria: {vecchio}"

    def elenca(limite: int = 30) -> str:
        """Tutta la memoria, per chi vuole vedere cosa c'è."""
        m = memoria()
        tutti = m.fatti()
        if not tutti:
            return "Nessun fatto in memoria."
        return "\n".join(f"- {f}" for f in tutti[-limite:])

    def handler(azione: str = "cerca", query: str = "", fatto: str = "",
                priorita: str = "", limite: int = 10,
                vecchio: str = "", nuovo: str = "") -> str:
        try:
            azione = (azione or "cerca").strip().lower()
            if azione == "cerca":
                return cerca(query, limite)
            if azione == "aggiungi":
                return aggiungi(fatto, priorita)
            if azione == "elimina":
                return elimina(query or fatto)
            if azione == "modifica":
                return modifica(vecchio or fatto, nuovo or query)
            if azione == "elenca":
                return elenca(limite)
            return (f"Azione non riconosciuta: {azione}. "
                    f"Puoi fare: cerca, aggiungi, elimina, modifica, elenca.")
        except Exception as e:
            # Un errore qui non deve far cadere il turno: l'agente deve
            # poter dire "non riesco a cercare" e continuare.
            return f"Errore nella memoria: {type(e).__name__}: {e}"

    return Tool(
        name="memoria",
        description=(
            "Cerca, aggiunge, toglie o riscrive fatti nella memoria a "
            "lungo termine. "
            "Usa 'cerca' PRIMA di chiedere qualcosa che potresti già sapere "
            "dalle conversazioni precedenti, e 'aggiungi' quando l'utente "
            "dice di ricordare qualcosa o prende una decisione che varrà "
            "anche domani. Con priorita='alta' il fatto viene ripetuto "
            "in ogni conversazione: usala solo per il pochissimo che deve "
            "essere vero sempre."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {
                    "type": "string",
                    "enum": ["cerca", "aggiungi", "elimina", "modifica", "elenca"],
                    "description": "Cosa fare. Default: cerca.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Testo da cercare. Per 'elimina' e 'modifica' puo' "
                        "essere anche il fatto da togliere o da cambiare."
                    ),
                },
                "fatto": {
                    "type": "string",
                    "description": (
                        "Il fatto da ricordare (per 'aggiungi'), oppure il "
                        "fatto attuale da cambiare (per 'modifica')."
                    ),
                },
                "vecchio": {
                    "type": "string",
                    "description": "Il fatto attuale, per azione=modifica.",
                },
                "nuovo": {
                    "type": "string",
                    "description": "Il testo nuovo, per azione=modifica.",
                },
                "priorita": {
                    "type": "string",
                    "enum": ["", "alta"],
                    "description": "'alta' lo inietta in ogni conversazione.",
                },
                "limite": {
                    "type": "integer",
                    "description": "Quanti risultati. Default 10.",
                },
            },
        },
        handler=handler,
    )
