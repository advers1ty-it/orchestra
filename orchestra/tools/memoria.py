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
from ..memoria import sembra_regola
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


def _coppie_importanti() -> list[tuple[str, str]]:
    """(testo, origine) dei fatti che vanno nel prompt, se si sa.

    L'origine serve a decidere CHI resta fuori quando lo spazio finisce.
    Un backend che non la conosce (un plugin futuro) non deve rompere il
    prompt: si ripiega sull'elenco nudo, trattato come scelto a mano.
    """
    try:
        m = memoria()
        # Il ripiego vive qui e non in ogni backend: se il metodo manca o
        # fallisce si legge l'elenco nudo e si tratta tutto come scelto a
        # mano. Due memorie che dicono cose diverse sarebbero peggio di
        # una che non distingue.
        try:
            return list(m.importanti_con_origine())
        except Exception:  # noqa: BLE001 - backend senza il metodo
            return [(testo, "mano") for testo in m.importanti()]
    except Exception:  # noqa: BLE001 - senza memoria il prompt resta
        return []


def _righe_entro_tetto(elenco: list[str]) -> tuple[list[str], int]:
    """Righe che entrano in TETTO_PROMPT, e quante restano fuori.

    Si tiene un fatto INTERO: tagliare a meta' carattere lascia nel
    prompt una regola mutilata, che il modello legge come completa.

    E si continua dopo uno scarto: un fatto corto che viene dopo uno
    lungo ci sta lo stesso, e fermarsi al primo che non entra perderebbe
    roba che entrava.
    """
    righe: list[str] = []
    usati = 0
    fuori = 0
    for testo in elenco:
        riga = f"- {testo}"
        costo = len(riga) + (1 if righe else 0)
        if usati + costo > TETTO_PROMPT:
            fuori += 1
            continue
        righe.append(riga)
        usati += costo
    return righe, fuori


def blocco_prompt() -> str:
    """Il pezzo di memoria che entra nel system prompt.

    Vuoto se non c'è niente marcato: una sezione "preferenze" vuota
    insegna al modello a parlare della memoria invece di usarla.

    L'ordine e' una priorita': prima le regole marcate a mano, poi quelle
    promosse dall'euristica. Quando lo spazio finisce deve uscire una
    promozione automatica, non una preferenza che qualcuno ha scritto e
    marcato apposta.

    E il taglio si DICE. Prima il testo veniva troncato a 1.000
    caratteri in silenzio: una regola vera spariva dal prompt e nessuno
    lo sapeva — ne' il modello, che non cerca quello che non sa di
    avere, ne' chi guarda il prompt e crede che quelle siano tutte le
    regole. La riga di avviso sta FUORI dal tetto: serve proprio a dire
    che il tetto ha tagliato, e tagliarla sarebbe il difetto di prima.
    """
    coppie = _coppie_importanti()
    if not coppie:
        return ""
    mano = [testo for testo, origine in coppie if origine != "auto"]
    auto = [testo for testo, origine in coppie if origine == "auto"]
    righe, fuori = _righe_entro_tetto(mano + auto)
    if fuori:
        righe.append(
            f"- [altre {fuori} regole fuori da questo elenco: sono in "
            f"memoria, cercale con `memoria` (azione \"cerca\")]")
    return "\n".join(righe)


INTRO_PROMPT = (
    "Cose che valgono in ogni conversazione. Non ripeterle se non "
    "servono. Per tutto il resto hai il tool `memoria`: cerca quello che "
    "ti serve invece di assumere di non saperlo."
)


def blocco_prompt_completo() -> str:
    """Il blocco memoria con la sua introduzione, o ''.

    L'introduzione sta qui e non nel prompt di base perche' i fatti e
    l'introduzione devono viaggiare INSIEME: un prompt che spiega come
    usare la memoria quando la memoria non c'e' e' una riga in piu' che
    non serve a niente. E il blocco viene ricalcolato a ogni turno
    (vedi `Agent._aggiorna_prompt`), quindi una regola salvata durante
    la sessione entra dal messaggio successivo, senza riavviare.
    """
    fatti = blocco_prompt()
    if not fatti:
        return ""
    return f"## Cose che valgono sempre (memoria)\n\n{INTRO_PROMPT}\n\n{fatti}"


def tool_memoria() -> Tool:
    """Il tool. Quattro azioni, una per domanda diversa."""

    def cerca(query: str = "", limite: int = 10,
               progetto: str = "") -> str:
        """Cerca fra i fatti. È l'azione che sostituisce l'iniezione totale.

        `progetto` restringe la ricerca a un progetto. Vuoto = tutti, che
        è il default: la memoria è condivisa e chiedere "tutto" è una
        domanda legittima.

        MA se c'e' un progetto attivo, il default non e' "tutti": e' il
        progetto attivo. E' il punto di tutto il meccanismo — l'agente
        che lavora sul sito del ristorante deve vedere i fatti del sito
        del ristorante, senza dover dire "cerca con progetto=..." ogni
        volta. Un modello che deve ricordarsi di passare un filtro
        sbaglia: lo salta, e legge la memoria sbagliata.

        Il filtro automatico e' pero' solo sul progetto: i fatti senza
        progetto restano raggiungibili, perche' valgono per tutti.
        """
        progetto = (progetto or "").strip()
        if not progetto:
            try:
                from .. import progetti as _pr
                progetto = (_pr._root_progetto() or "").strip()
            except Exception:  # noqa: BLE001
                progetto = ""
        m = memoria()
        q = (query or "").strip().lower()
        # L'indice FTS5 quando c'è: il backend su file non ha la
        # ricerca per sottostringa, e su una memoria lunga scaricare
        # tutto per ogni ricerca è il costo che l'indice serve a
        # evitare. Se l'indice non c'è, si torna al file: meglio
        # lento che muto.
        cerca_indice = getattr(m, "cerca", None)
        if callable(cerca_indice):
            try:
                righe = cerca_indice(q, limite=limite, progetto=progetto)
                if righe:
                    return "\n".join(f"- {r['testo']}" for r in righe[:limite])
            except Exception:
                pass
        # L'indice non ha trovato niente: si prova sul file, e NON si
        # dice subito "non trovato". L'FTS cerca tutte le parole insieme
        # (AND), mentre il filtro sul file riprova anche con una parola
        # sola: una domanda con due parole puo' benissimo trovare un
        # fatto per la via corta. Dire "non trovato" dopo il solo primo
        # tentativo e' dire una falsita' — e il modello smette di
        # chiedere perche' e conclude che il fatto non esista.
        # Il filtro per progetto vale anche nel percorso di riserva: se
        # l'indice non ha trovato niente, il fallback sul file non deve
        # tirare fuori i fatti degli ALTRI progetti. Se lo facesse, una
        # ricerca per "sito-ristorante" mostrerebbe anche i fatti
        # dell'app parrucchieri — e l'agente leggerebbe roba che non
        # c'entra come se c'entrasse.
        if progetto:
            tutti = m.fatti_per_progetto(progetto)
        else:
            tutti = m.fatti()
        if not tutti:
            return "Nessun fatto in memoria."
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

    def aggiungi(fatto: str = "", priorita: str = "",
                progetto: str = "") -> str:
        """Aggiunge un fatto. `priorita` = "alta" lo mette nel prompt.

        Se il progetto non e' indicato, si usa quello attivo: e' il
        progetto su cui l'agente sta lavorando, ed e' quello a cui il
        fatto appartiene. Chiedere al modello di specificarlo ogni
        volta e' chiedergli di ricordarsi una cosa che il sistema
        gia' sa — e un modello che deve ricordarsi una cosa sbaglia.
        """
        fatto = (fatto or "").strip()
        if not fatto:
            return "Fatto vuoto: non ho niente da ricordare."
        progetto = (progetto or "").strip()
        if not progetto:
            try:
                from .. import progetti as _pr
                progetto = (_pr._root_progetto() or "").strip()
            except Exception:  # noqa: BLE001
                progetto = ""
        m = memoria()
        # Una regola vale anche se il modello non ha pensato a marcarla:
        # la promuove `Memoria.aggiungi`, che lascia anche il marcatore
        # `[auto]` nella riga.
        #
        # Qui `importante` si passa SOLO se l'ha chiesto chi scrive: con
        # `importante=True` il file non ha piu' modo di distinguere una
        # scelta a mano da una promozione, e nel taglio del prompt la
        # prima sarebbe finita dietro la seconda.
        regola = sembra_regola(fatto)
        esplicita = priorita.strip().lower() == "alta"
        nuovo = m.aggiungi(fatto, origine="agente", importante=esplicita,
                           progetto=progetto)
        if not nuovo:
            return f"Era già in memoria: {fatto}"
        coda = (" (priorità alta: è una regola, resta nel prompt)"
                if regola
                else " (priorità alta)" if esplicita else "")
        return ("Ricordato" + coda
                + (f" [progetto: {progetto}]" if progetto else "")
                + f": {fatto}")

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

    def ottimizza(dry_run: bool = True, giorni_grazia: int = 30,
                  progetto: str = "", unisci: bool = False) -> str:
        """Potatura della memoria: toglie i fatti mai usati e vecchi.

        `dry_run=True` (default) mostra solo cosa verrebbe fatto.
        """
        m = memoria()
        ott = getattr(m, "ottimizza_memoria", None)
        if not callable(ott):
            return "Ottimizzatore non disponibile (indice assente)."
        progetto = (progetto or "").strip()
        if not progetto:
            try:
                from .. import progetti as _pr
                progetto = (_pr._root_progetto() or "").strip()
            except Exception:  # noqa: BLE001
                progetto = ""
        provider = None
        if unisci:
            try:
                # nessun provider nel tool: l'unione resta disabilitata
                unisci = False
            except Exception:
                unisci = False
        res = ott(provider=provider, dry_run=dry_run,
                  giorni_grazia=giorni_grazia, progetto=progetto,
                  unisci=unisci)
        if res.get("errore"):
            return f"Errore ottimizzatore: {res['errore']}"
        righe = []
        righe.append(f"Ottimizzazione {'(anteprima)' if res.get('dry_run') else '(applicata)'}: "
                     f"{res.get('rimossi', 0)} fatti rimossi "
                     f"({res.get('fatti_prima', 0)} -> {res.get('fatti_dopo', res.get('fatti_prima', 0))}).")
        for c in (res.get("candidati") or [])[:20]:
            righe.append(f"- {c.get('testo')} ({c.get('motivo')})")
        if res.get("proposte_unione"):
            righe.append(f"Unioni proposte: {len(res['proposte_unione'])}")
        return "\n".join(righe) if righe else "Niente da ottimizzare."

    def handler(azione: str = "cerca", query: str = "", fatto: str = "",
                priorita: str = "", limite: int = 10,
                vecchio: str = "", nuovo: str = "",
                progetto: str = "", dry_run: bool = True,
                giorni_grazia: int = 30, unisci: bool = False) -> str:
        try:
            azione = (azione or "cerca").strip().lower()
            if azione == "cerca":
                return cerca(query, limite, progetto)
            if azione == "aggiungi":
                return aggiungi(fatto, priorita, progetto)
            if azione == "elimina":
                return elimina(query or fatto)
            if azione == "modifica":
                return modifica(vecchio or fatto, nuovo or query)
            if azione == "elenca":
                return elenca(limite)
            if azione == "ottimizza":
                return ottimizza(dry_run=dry_run, giorni_grazia=giorni_grazia,
                                 progetto=progetto, unisci=unisci)
            return (f"Azione non riconosciuta: {azione}. "
                    f"Puoi fare: cerca, aggiungi, elimina, modifica, elenca, ottimizza.")
        except Exception as e:
            # Un errore qui non deve far cadere il turno: l'agente deve
            # poter dire "non riesco a cercare" e continuare.
            return f"Errore nella memoria: {type(e).__name__}: {e}"

    return Tool(
        name="memoria",
        description=(
            "Searches, adds, removes or rewrites facts in long-term "
            "memory. Use 'cerca' BEFORE asking for something you may "
            "already know from earlier conversations, and 'aggiungi' when "
            "the user says to remember something or takes a decision that "
            "will still hold tomorrow. With priorita='alta' the fact is "
            "repeated in every conversation: use it only for the very few "
            "things that must always be true."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {
                    "type": "string",
                    "enum": ["cerca", "aggiungi", "elimina", "modifica", "elenca", "ottimizza"],
                    "description": (
                        "What to do: cerca (search), aggiungi (add), "
                        "elimina (delete), modifica (edit), elenca (list), "
                        "ottimizza (dedupe). Default: cerca."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Text to search for. For 'elimina' and 'modifica' "
                        "it can also be the fact to remove or to change."
                    ),
                },
                "fatto": {
                    "type": "string",
                    "description": (
                        "The fact to remember (for 'aggiungi'), or the "
                        "current fact to change (for 'modifica')."
                    ),
                },
                "vecchio": {
                    "type": "string",
                    "description": "The current fact, for azione=modifica.",
                },
                "nuovo": {
                    "type": "string",
                    "description": "The new text, for azione=modifica.",
                },
                "priorita": {
                    "type": "string",
                    "enum": ["", "alta"],
                    "description": (
                        "'alta' (high) injects the fact into every "
                        "conversation."
                    ),
                },
                "limite": {
                    "type": "integer",
                    "description": "How many results. Default 10.",
                },
                "progetto": {
                    "type": "string",
                    "description": (
                        "The project the fact belongs to. Optional: empty "
                        "means 'all projects'. Use it to separate one "
                        "project's facts from the others, so you can later "
                        "ask only for the one you are working on."
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Only meaningful for azione='ottimizza': when true "
                        "(default) it reports what would be pruned or "
                        "merged without touching memory. 'aggiungi', "
                        "'modifica' and 'elimina' always act, whatever "
                        "this says — do not set it expecting a preview "
                        "of them."
                    ),
                },
                "giorni_grazia": {
                    "type": "integer",
                    "description": (
                        "Grace days before pruning a fact never used. "
                        "Default 30."
                    ),
                },
                "unisci": {
                    "type": "boolean",
                    "description": (
                        "When true, merges similar facts (needs a "
                        "provider)."
                    ),
                },
            },
        },
        handler=handler,
    )
