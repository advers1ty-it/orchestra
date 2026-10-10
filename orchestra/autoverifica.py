"""Loop di self-correzione: agisci -> verifica oggettiva -> correggi.

Il pezzo che mancava all'agente era chiudere il ciclo. I verificatori
esistono già (verificatori.py, verificatori_codice.py, verificatori_js.py)
ma servono al BENCHMARK: misurano un modello su un task preparato. Qui
servono a un task VERO, mentre l'agente ci lavora.

Il principio è lo stesso e va tenuto: la verifica è OGGETTIVA. Nessun
modello giudica il lavoro di un altro modello — sarebbe un giudice
travestito da test, e premia il più verboso. Qui si controlla il
RISULTATO: un file c'è, il JSON ha i campi, il codice eseguito dà il
numero atteso. Se non torna, si rimanda indietro il motivo esatto, e il
modello riprova sapendo cosa era sbagliato invece di indovinare.

Il contratto con l'agent è stretto per non rompere il loop esistente:
  - `verifica_compito(agent, specifica)` gira dopo che il modello ha
    risposto, prima che il turno si chiuda.
  - Torna `None` se non c'è niente da verificare (assenza di specifica
    = task conversazionale, non va toccato).
  - Torna un `EsitoVerifica`; se `ok` è False, l'agent NON chiude il
    turno ma inietta l'errore come messaggio tool e rifà partire il
    loop, con un tetto ai tentativi.

Il tetto è la parte che impedisce a questo di diventare un pozzo senza
fondo: `max_tentativi`. Un modello che non ce la fa in tre giri, con
l'errore sotto il naso, non ce la farà al quarto — e ogni giro costa
token. Meglio restituire il lavoro imperfetto con il motivo, che girare
in tondo bruciando budget.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


# La firma di un verificatore oggettivo, allineata a verificatori.py:
# prende la dir di lavoro, torna (superato, motivo). Il motivo serve
# SEMPRE, anche quando passa: è la prova, e una prova senza motivo è
# un'opinione.
Verificatore = Callable[[str], tuple[bool, str]]


@dataclass
class SpecificaVerifica:
    """Cosa va verificato su questo task.

    `verificatori` gira in ordine e si ferma al primo che fallisce: un
    errore per volta, chiaro, invece di una sfilza di lamentele che il
    modello non sa da dove iniziare.
    """
    verificatori: list[Verificatore]
    max_tentativi: int = 3
    work: str = ""              # dir di lavoro; "" = root dell'agente
    descrizione: str = ""       # per il log: cosa si sta verificando


@dataclass
class EsitoVerifica:
    ok: bool
    motivo: str = ""
    tentativo: int = 0
    verificatore: str = ""
    durata_s: float = 0.0
    storico: list[dict[str, Any]] = field(default_factory=list)


def verifica_compito(
    *,
    verificatori: list[Verificatore],
    work: str,
    max_tentativi: int = 3,
    descrizione: str = "",
) -> EsitoVerifica:
    """Esegue i verificatori una volta e torna l'esito.

    Non gira il loop: gira la VERIFICA. Il ciclo (riprova finché non
    passa o finisce il budget) vive nell'agent, che è l'unico che può
    rimandare il modello indietro. Questa separazione tiene la logica di
    verifica pura e testabile, senza dentro la macchina del turno.
    """
    esito = EsitoVerifica(ok=True, tentativo=1)
    if not verificatori:
        return esito
    t0 = time.monotonic()
    for v in verificatori:
        nome = getattr(v, "__name__", getattr(v, "name", "verificatore"))
        try:
            superato, motivo = v(work)
        except Exception as e:
            # Un verificatore che solleva non è un fallimento del modello:
            # è un difetto del controllo. Va distinto, o il modello si
            # affannerebbe a correggersi per un errore nostro.
            superato, motivo = False, f"verificatore guasto ({type(e).__name__}: {e})"
        esito.storico.append({"verificatore": nome, "ok": superato,
                              "motivo": motivo})
        if not superato:
            esito.ok = False
            esito.motivo = motivo
            esito.verificatore = nome
            break
    esito.durata_s = time.monotonic() - t0
    return esito


def nota_per_modello(esito: EsitoVerifica, tentativo: int, max_tentativi: int) -> str:
    """Il messaggio iniettato nel contesto quando la verifica fallisce.

    Scritto per il MODELLO, non per il log. Deve dire tre cose e basta:
    cosa non ha superato la verifica, il motivo esatto, quanti tentativi
    restano. Senza "quanti restano" un modello persevera sullo stesso
    errore; senza il motivo esatto indovina, ed è quello che costa.
    """
    restanti = max(0, max_tentativi - tentativo)
    return (
        f"VERIFICA OGGETTIVA FALLITA (tentativo {tentativo}/{max_tentativi}, "
        f"ne restano {restanti}).\n"
        f"Controllo non superato: {esito.verificatore or 'n/d'}.\n"
        f"Motivo: {esito.motivo}\n"
        f"Correggi il problema segnalato e riprova. "
        f"Se il motivo ti sembra sbagliato, dillo invece di inseguirlo."
    )
