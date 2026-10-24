"""Il loop agentico.

Il cuore sono poche righe: chiama il modello, esegui i tool richiesti,
rimetti i risultati, ripeti. Tutta la sostanza sta nelle invarianti attorno.

Invarianti che ci siamo dati, da mantenere nei refactor:

  1. Un tool call che fallisce NON uccide il turno. Restituiamo l'errore
     come contenuto del messaggio `tool`: il modello può correggere. Questo
     e' la differenza tra un agente che recupera e uno che si blocca.
  2. Ogni tool_call del modello riceve SEMPRE un risultato, anche se vuoto
     o in errore. Altrimenti la prossima richiesta ha un buco nella
     sequenza e molti provider la rifiutano.
  3. Gli ultimi `keep_recent` messaggi non si compattano mai.
  4. Il loop è cancellabile: `should_continue` lo può fermare a meta' di un
     task, e lo stato è ispezionabile dall'esterno.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

from .context import Summarizer, count_tokens, fit_context
from .providers import ProviderError
from .fallback import (
    ChainEntry, FallbackState, FallbackReason,
    get_chain_for_provider, should_fallback
)
from .budget import budget_guard, BudgetLimits
from .types import LLMResponse, Message, ToolRegistry, new_id

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")


@dataclass
class LoopConfig:
    """Parametri del loop. I default sono scelti, non arbitrari."""

    max_iterations: int = 20
    context_limit: int = 120_000
    keep_recent: int = 8
    temperature: float = 0.7
    max_tokens: int = 4096
    # un singolo tool non può superare questo, o siamo vulnerabili a un
    # `cat` su file da 4GB che blocca tutto
    tool_timeout_chars: int = 20_000
    # quanti errori consecutivi tolleriamo prima di mollare: oltre, il
    # modello sta girando in tondo e continuare costa soldi senza avanzare
    max_consecutive_errors: int = 3
    # reasoning effort: none | minimal | low | medium | high | xhigh | max
    # None = usa default per provider/category
    reasoning_level: str | None = None
    # Profilo strumenti opzionale. None = registro intatto (default,
    # massima disponibilita'). "auto" = scelta dall'input; altrimenti nome
    # profilo esplicito ("base", "ricerca", "skill", "pieno").
    tool_profile: str | None = None
    # Budget limits per questa run (None = usa default)
    budget_limits: BudgetLimits | None = None
    # Loop di self-correzione: quando il modello chiide con risposta
    # finale, se `verifica_compito` è impostata Orchestra controlla
    # OGGETTIVAMENTE il risultato e, se non torna, rimanda il modello
    # indietro col motivo esatto. None = nessuna verifica (task
    # conversazionali, o chi non ne ha bisogno).
    verifica_compito: Any = None
    # Tetto ai tentativi di self-correzione: un modello che non ce la fa
    # in N giri, con l'errore sotto il naso, non ce la farà al N+1 — e
    # ogni giro costa token. Meglio il lavoro imperfetto col motivo che
    # girare in tondo.
    max_tentativi_verifica: int = 3


@dataclass
class AgentState:
    """Stato ispezionabile della run. Lo teniamo esplicito perché un
    orchestratore senza stato introspettabile è una scatola nera."""

    messages: list[Message] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    tool_calls_made: int = 0
    tool_errors: int = 0
    # quali strumenti hanno fallito, non solo quanti: 'con errore: 1'
    # non dice se il modello ha sbagliato una chiamata o se c'e' un
    # bug in uno strumento — che sono due cose da sistemare in due
    # posti diversi.
    tool_error_names: list[str] = field(default_factory=list)
    consecutive_errors: int = 0
    compactions: int = 0
    stopped_because: str = ""
    usage_by_model: dict[str, int] = field(default_factory=dict)
    # Steer: messaggi iniettati durante il turno
    steer_queue: list[str] = field(default_factory=list)
    steer_count: int = 0
    steer_max: int = 5


class Agent:
    """L'orchestratore.

    Un `Agent` = system prompt + tool + provider. Il loop è in `run()`.
    """

    def __init__(
            self,
            provider: Any,
            registry: ToolRegistry,
            system_prompt: str,
            config: LoopConfig | None = None,
            *,
            summarize: Summarizer | None = None,
            on_event: Callable[[str, dict[str, Any]], None] | None = None,
            fallback_chain: list[ChainEntry] | None = None,
        ) -> None:
            self._cancel_flag = False
            self.provider = provider
            self.registry = registry
            self.system_prompt = system_prompt
            # Il progetto su cui si lavora. Va sull'agente e non solo sulla
            # sessione perche' e' l'agente a dover cercare i fatti giusti:
            # la sessione etichetta quelli che nascono, l'agente deve
            # sapere quale filtro usare per recuperarli.
            self.progetto: str = ""
            self.config = config or LoopConfig()
            self.summarize = summarize
            self.on_event = on_event or (lambda kind, data: None)
            self.state = AgentState(messages=[Message(role="system", content=system_prompt)])
            # Fallback chain: if provider is a string, it's the primary provider name
            # and we build the chain automatically. If it's a list, use as-is.
            if fallback_chain is None and hasattr(provider, 'name'):
                # Build default chain from provider name and model
                provider_name = provider.name
                model = getattr(provider, 'model', '')
                self.fallback_chain = get_chain_for_provider(provider_name, model)
                # Update first entry with actual provider instance
                if self.fallback_chain:
                    self.fallback_chain[0] = ChainEntry(
                        provider=provider_name,
                        model=model,
                        name=f"{provider_name}/{model}",
                    )
            else:
                self.fallback_chain = fallback_chain or []
            self._fallback_state: FallbackState | None = None
            # Nudge anti-bocca-vuota: un solo promemoria per turno, non
            # per sempre. Si azzera a ogni `run`, così una domanda futura
            # che ricasca nello stesso annuncio viene corretta di nuovo —
            # ma lo STESSO turno non si auto-nudga all'infinito.
            self._nudge_fatto = False
            # Turni di sole parole: quante risposte solo-testo di fila
            # senza nessun tool. Alla terza si chiude onestamente invece
            # di spacciare narrazione per lavoro fatto.
            self._vuote_di_fila = 0
            # Self-correzione: contatore dei tentativi di verifica per
            # questo turno, e bandiera che scatta quando il tetto è stato
            # raggiunto (oltre, si chiude col lavoro imperfetto).
            self._verifica_tentativo = 0
            self._verifica_esaurita = False
            # Anti-gira-a-vuoto: quante volte ho già visto QUESTA identica
            # chiamata (nome+argomenti). Un modello piccolo che si incanta
            # su un tool che fallisce lo riprova tale e quale, e ogni giro
            # costa token per tornare allo stesso errore. Dopo due colpi
            # gli si dice di smettere; dopo tre si chiude col lavoro fatto.
            self._chiamate_identiche: dict[str, int] = {}
            # Budget. Lo stato si crea SEMPRE, anche senza limiti espliciti:
            # saltare la creazione perche' "non mi hanno passato niente"
            # faceva leggere il .env a BudgetGuard senza che nessuno gli
            # chiedesse niente -- il limite era salvato, mostrato nel
            # pannello, e non applicato da nessuna parte.
            #
            # Lo stato e' uno solo, trasversale a tutti i modelli: il tetto
            # risponde a "quanto ho speso", e la bolletta non distingue.
            # `session_id` non serve piu' a niente, resta per la firma.
            self._budget_state = budget_guard().get_or_create_session(
                self.config.budget_limits)

            # -- utility interne ---------------------------------------------------

    def _cancel_requested(self) -> bool:
        """Verifica se è stata richiesta la cancellazione."""
        return self._cancel_flag

    def _emit(self, kind: str, **data: Any) -> None:
        self.on_event(kind, data)

    def _on_stream(self, kind: str, data: dict[str, Any]) -> None:
        """Un pezzo di ragionamento o di contenuto, mentre arriva.

        Eventi separati da `thinking`: `thinking` dice "ho cominciato",
        questi dicono cosa sta uscendo. Uno solo dei due sarebbe stato o
        muto all'inizio o ripetitivo dopo.

        Non si accumula in un campo dell'agente: il ragionamento completo
        è già in `LLMResponse.reasoning`, che torna da `chat_stream`. Un
        secondo accumulo sarebbe la stessa informazione in due posti, e
        quello dell'agente si sbaglia — provato, teneva 40 caratteri su
        105 eventi perché lo azzeravo a ogni iterazione del loop.
        """
        testo = data.get("testo") or ""
        if not testo:
            return
        if kind == "ragionamento":
            self._emit("ragionamento", testo=testo)
        elif kind == "contenuto":
            self._emit("contenuto", testo=testo)

    def _maybe_compact(self) -> None:
        report = fit_context(
            self.state.messages,
            limit=self.config.context_limit,
            keep_recent=self.config.keep_recent,
            summarize=self.summarize,
        )
        if report["tools_pruned"] or report["history_merged"]:
            self.state.compactions += 1
            self._emit("compaction", **report)
        else:
            # Niente da potare: quasi sempre il contesto e' sotto soglia
            # (e l'utente vede solo "piantato", quindi lo si dice). Ma i
            # token giusti sono quelli ATTUALI (tokens_before), non il
            # cumulato del turno: confrontare il totale con la finestra
            # dice "605k/384k" e sembra sopra soglia mentre e' sotto.
            # Se invece e' davvero sopra e non si puo' potare, lo si
            # dice: e' un guaio diverso dal "tutto bene".
            sopra = report["tokens_before"] > self.config.context_limit
            self._emit("compaction_attempt",
                       tokens=report["tokens_before"],
                       limit=self.config.context_limit,
                       sopra_soglia=sopra)

    def _execute_tool(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Esegue un tool e restituisce (testo, riuscito).

        Restituisce SEMPRE una stringa, mai solleva. Vedi invariante 1: è
        deliberato, un agente che si blocca su un errore recuperabile è un
        agente che spreca soldi.

        Il secondo valore serve al chiamante: `riuscito` è False anche quando
        il testo è un messaggio d'errore, e senza questo il circuit breaker
        non ha modo di sapere che il modello sta sbagliando.
        """
        tool = self.registry.get(name)
        if tool is None:
            return (
                f"ERRORE: tool inesistente '{name}'. "
                f"Disponibili: {', '.join(self.registry.all_names())}",
                False,
            )

        try:
            # Cache sui tool puri: se lo stesso calcolo è già stato fatto,
            # si restituisce quello invece di ricalcolarlo. Solo per i tool
            # PURE (il risultato dipende solo dagli argomenti) — su
            # read_file o web_cerca servirebbe roba vecchia. Vedi cache_tool.
            from .cache_tool import cache_tool
            cache = cache_tool()
            cached = cache.prendi(name, args)
            if cached is not None:
                self._emit("tool_cache", name=name, hit=True)
                text = cached
                if len(text) > self.config.tool_timeout_chars:
                    text = text[: self.config.tool_timeout_chars]
                return text, True

            result = tool.handler(**args)
            if hasattr(result, "__await__"):
                import asyncio

                result = asyncio.run(result)
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            # Si cachea solo il successo: un errore transitorio inchiodato
            # per 5 minuti sarebbe peggio che ricalcolarlo.
            cache.metti(name, args, text)
        except TypeError as e:
            # quasi sempre argomenti sbagliati: lo riportiamo con
            # precisione. È un errore del modello, quindi conta verso
            # il breaker.
            #
            # Il nome del parametro atteso è la parte che serve: senza,
            # il modello riceve "unexpected keyword argument 'file_path'"
            # e un nome interno di Python, e non ha modo di capire che
            # il parametro giusto e' un altro. Su un benchmark la
            # differenza e' visibile: tre chiamate con il nome del
            # parametro sbagliato sembrano tre strumenti rotti.
            attesi = ""
            try:
                import inspect
                attesi = ", ".join(
                    str(p) for p in inspect.signature(tool.handler).parameters
                    if p not in ("self",))
            except (TypeError, ValueError):
                pass
            dettaglio = f" Accetta: {attesi}." if attesi else ""
            return (f"ERRORE DI ARGOMENTI per '{name}': {e}."
                    f"{dettaglio}"), False
        except Exception as e:
            self._emit(
                "tool_error",
                tool=name,
                error=f"{type(e).__name__}: {e}",
                trace=traceback.format_exc(limit=3),
            )
            return f"ERRORE durante l'esecuzione di '{name}': {type(e).__name__}: {e}", False

        if len(text) > self.config.tool_timeout_chars:
            text = (
                text[: self.config.tool_timeout_chars]
                + f"\n\n[TRONCATO: {len(text)} caratteri totali, mostro i primi "
                f"{self.config.tool_timeout_chars}]"
            )
        return text, True

    # -- il loop -----------------------------------------------------------

    def _blocco_progetto(self) -> str:
        """Il pezzo di prompt che dice su quale progetto si lavora.

        E' quello che rende il progetto utile al MODELLO, e non solo
        alla memoria. Senza questa riga l'agente non sa che sta
        lavorando al sito del ristorante: la memoria ha i fatti
        etichettati, ma il modello non sa di doverli cercare — e quindi
        non li cerca.

        Dice anche che il progetto si puo' cambiare. Senza, un modello
        che vede "progetto: sito-ristorante" puo' pensare che non si
        possa cambiare, e l'utente che dice "adesso passiamo
        all'app parrucchieri" riceve un "non posso".

        Vuoto se non c'e' un progetto: e' il caso normale, e in quel
        caso il prompt resta identico carattere per carattere.
        """
        progetto = (getattr(self, "progetto", "") or "").strip()
        if not progetto:
            return ""
        return (
            f"\n\n---\n"
            f"Stai lavorando al progetto «{progetto}», e i tuoi file "
            f"vanno in quella cartella: e' li' che il tool `read_file` "
            f"e `write_file` leggono e scrivono, senza che tu debba "
            f"scrivere il percorso per esteso.\n"
            f"I fatti di memoria che appartengono a questo progetto "
            f"sono marcati [progetto:{progetto}]. Il tool `memoria` "
            f"li cerca gia' col filtro giusto da solo: non devi "
            f"passare progetto='{progetto}' — ma se lo passi, e' la "
            f"stessa cosa. I fatti senza progetto valgono per "
            f"ogni progetto, e tornano insieme a quelli giusti.\n"
            f"Se l'utente cambia progetto, lo dice: e' il momento in "
            f"cui la cartella e i fatti cambiano."
        )

    def _ha_i_tool_skill(self) -> bool:
        """I tool per leggere e cercare le skill sono attivi?

        Il prompt delle skill e' un insieme di istruzioni ("skill_leggi
        <nome>"), e un'istruzione che punta a un tool assente non e'
        un'istruzione: e' una promessa che il sistema non puo' mantenere.
        Il modello la segue, e riceve "tool inesistente" — che sembra un
        bug dell'agente, ma e' il prompt che ha sbagliato.

        Il caso in cui accade: il profilo "auto" sceglie "base" per un
        testo che non parla di skill, e "base" non contiene i tool skill.
        Il prompt li elencava lo stesso, e ogni turno ricominciava cosi'.
        """
        try:
            attivi = {t.name for t in self.registry.active}
        except Exception:
            # Se non si puo' sapere, si presume che ci siano: senza tool
            # skill il prompt e' un pezzo in piu', e il modello puo'
            # ignorarlo. Il contrario (bloccare le skill quando i tool
            # ci sono) toglierebbe una capacita' che funziona.
            return True
        return bool(attivi & {"skill_leggi", "skill_cerca"})

    def _aggiorna_prompt(self) -> None:
        """Riscrive il messaggio di sistema con le skill e il progetto.

        Ma solo se ce ne sono. Senza skill E senza progetto il prompt
        resta identico, carattere per carattere: un test che verifica
        "il system prompt non e' mai perso" confronta l'uguaglianza
        esatta, e aggiungere anche solo una riga vuota lo faceva
        fallire — e il sintomo sarebbe stato "la compaction perde il
        prompt", che e' falso. In quel caso si faceva cercare un bug
        nella compattazione, che era perfettamente funzionante.

        Fallisce in silenzio e lascia il prompt come era: un errore
        qui non deve fermare il turno.
        """
        # Le skill si annunciano SOLO se i loro tool sono attivi.
        #
        # Il prompt delle skill dice "skill_leggi <nome>" e "skill_cerca
        # <parole>": sono istruzioni, non informazioni. Se il tool non e'
        # fra gli attivi, l'agente le esegue e riceve "tool inesistente" —
        # un'istruzione che il sistema stesso ha scritto e che il sistema
        # rende impossibile da seguire.
        #
        # Il caso reale: con il profilo "auto", profilo_per_testo sceglie
        # "base" per un testo che non parla di skill, e "base" non
        # contiene i tool skill. Il prompt li elencava lo stesso.
        try:
            import orchestra.skills as sk
            ultimo = ""
            for m in reversed(self.state.messages):
                if m.role == "user" and m.content:
                    ultimo = m.content
                    break
            if self._ha_i_tool_skill():
                extra = sk.Indice().prompt(ultimo[:2000])
            else:
                extra = ""
        except Exception:
            extra = ""
        try:
            progetto = self._blocco_progetto()
        except Exception:
            progetto = ""
        if not extra and not progetto:
            return                      # niente da aggiungere: identico
        # Il progetto viene DOPO le skill: le skill dicono COME
        # lavorare, il progetto dice SU COSA.
        nuovo = self.system_prompt + extra + progetto
        for m in self.state.messages:
            if m.role == "system":
                m.content = nuovo
                return
        self.state.messages.insert(0, Message(role="system", content=nuovo))

    def steer(self, testo: str) -> bool:
        """Inietta un messaggio durante il turno in corso."""
        if len(self.state.steer_queue) >= self.state.steer_max:
            return False
        self.state.steer_queue.append(testo)
        return True

    def request_cancel(self) -> None:
        """Richiede la cancellazione del turno in corso."""
        self._cancel_flag = True

    def run(
        self,
        user_input: str,
        *,
        allegati: list | None = None,
        should_continue: Callable[[AgentState], bool] | None = None,
    ) -> AgentState:
        """Esegue il loop fino a risposta finale, budget esaurito o stop esterno.

        `should_continue` permette il cancel: se restituisce False, il loop
        si ferma e lo stato è coerente. È il gancio per il task lungo.
        """
        # Gli allegati finiscono SULL'ULTIMO messaggio utente, non su uno
        # nuovo. Due messaggi separati fanno leggere all'agente
        # l'istruzione senza l'allegato: "estrai i prezzi" e poi
        # l'immagine come messaggio a se' e' una domanda senza
        # domanda.
        #
        # Un PDF con testo entra nel `content`, non nelle immagini: costa
        # zero token ed e' esatto.
        testo = user_input
        immagini: list[str] = []
        for a in (allegati or []):
            if getattr(a, "testo", ""):
                testo += ("\n\n" if testo else "") + (
                    f"[{a.nome}]\n{a.testo}"
                )
            immagini.extend(getattr(a, "immagini", []) or [])

        msg = Message(role="user", content=testo, images=immagini)
        self.state.messages.append(msg)
        self._emit("user_message", text=user_input,
                   allegati=[a.nome for a in (allegati or [])])

        # Il prompt di sistema si ricalcola a ogni turno, perche' le
        # skill cambiano durante la sessione: l'agente ne genera una,
        # tu ne importi una. Senza questo, la skill appena scritta non
        # entrerebbe fino al riavvio — l'agente la salva e poi non la
        # usa mai, e il motivo resta invisibile.
        #
        # Si aggiorna il MESSAGGIO di sistema in place invece di
        # prependerne uno nuovo: due messaggi system nello stesso
        # contesto confondono i provider che prendono solo il primo,
        # e la lezione si impara da quello che succede con i doppi.
        self._aggiorna_prompt()

        # Il cancel riguarda il turno IN CORSO, non tutti i turni futuri.
        #
        # `request_cancel()` accende `_cancel_flag`, e senza questo reset
        # il flag restava acceso per sempre: dal primo stop in poi, ogni
        # tool_call veniva annullato PRIMA di partire ("Cancellato
        # dall'utente prima dell'esecuzione"). Il sintomo per l'utente
        # era che dopo aver fermato una conversazione l'agente non potesse
        # piu' fare niente tranne chattare, e che i permessi sembrassero
        # rifiutati all'istante.
        #
        # Si resetta qui, all'inizio del turno, e non in `Session.send()`:
        # l'agent puo' essere usato anche senza sessione (CLI, benchmark,
        # delega), e il flag deve stare a posto ovunque.
        self._cancel_flag = False

        if self._budget_state:
            self._budget_state.reset_task()
        # Il nudge e la verifica ripartono puliti a ogni turno: appartenevano
        # alla domanda di prima.
        self._nudge_fatto = False
        self._vuote_di_fila = 0
        self._verifica_tentativo = 0
        self._verifica_esaurita = False
        self._chiamate_identiche = {}

        for self.state.iterations in range(1, self.config.max_iterations + 1):
            if should_continue and not should_continue(self.state):
                self.state.stopped_because = "canceled_da_should_continue"
                return self.state

            self._maybe_compact()

            # --- steer: inietta messaggi esistenti dal queue ---
            if self.state.steer_queue:
                testo = self.state.steer_queue.pop(0)
                self.state.steer_count += 1
                self.state.messages.append(Message(
                    role="tool",
                    content=(
                        f"[MESSAGGIO DURANTE IL LAVORO — steer #{self.state.steer_count}]\n"
                        f"{testo}\n"
                        f"\n"
                        f"Riconsidera il tuo lavoro alla luce di questa informazione. "
                        f"Continua da dove eri rimasto."
                    ),
                    tool_call_id=new_id("steer"),
                    name="__steer__",
                ))
                self._emit("steer", testo=testo, count=self.state.steer_count)
                # Se il modello stava per concludere, lo steer lo fa ripensare:
                # non fare il check di chiusura, vai direttamente alla chiamata
                continue

            # --- chiamata al modello, con retry su errori transitori
            #
            # L'evento va PRIMA della chiamata, non dopo. Una chiamata
            # che ragiona puo' durare 40 secondi — e quei 40 secondi
            # erano la cosa piu' lunga e piu' vuota dello schermo: la
            # UI non sapeva niente, il pulsante non si muoveva, e
            # sembrava che Orchestra avesse smesso di funzionare.
            #
            # Il messaggio dice cosa sta per succedere, non cosa è
            # successo: e' l'unica informazione utile durante
            # un'attesa.
            self._emit("thinking", iteration=self.state.iterations)
            resp = self._call_model_with_retry()
            self.state.total_tokens += resp.total_tokens
            self.state.usage_by_model[resp.model] = (
                self.state.usage_by_model.get(resp.model, 0) + resp.total_tokens
            )

            self.state.messages.append(
                Message(
                    role="assistant",
                    content=resp.content,
                    tool_calls=resp.tool_calls,
                    tokens=resp.total_tokens,
                    # Il ragionamento va conservato: i modelli che ragionano
                    # sempre lo richiedono indietro ai turni successivi, e
                    # senza il campo in `to_api()` rispondono 400.
                    reasoning=resp.reasoning,
                )
            )
            self._emit(
                "assistant",
                iteration=self.state.iterations,
                content=resp.content,
                # `id` per ogni tool call: e' la chiave con cui la UI
                # abbina `tool_end` al tool giusto. Senza, due tool con lo
                # stesso nome nello stesso turno finivano sulla stessa riga.
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "args": tc.parsed_args()}
                    for tc in resp.tool_calls
                ],
                tokens=resp.total_tokens,
            )

            # Budget: passa da record_usage, non da add_usage diretto.
            # record_usage aggiorna anche i contatori giorno/mese, che
            # vivono fuori dallo stato e su disco: sommandoli qui restavano
            # a zero e il tetto giornaliero non veniva mai applicato.
            if self._budget_state and resp.total_tokens > 0:
                prompt_tokens = getattr(resp, 'prompt_tokens', 0)
                completion_tokens = getattr(resp, 'completion_tokens', 0)
                if prompt_tokens == 0 and completion_tokens == 0:
                    prompt_tokens = resp.total_tokens // 2
                    completion_tokens = resp.total_tokens - prompt_tokens
                cost_usd = (prompt_tokens + completion_tokens) / 1000 * 0.001
                violations = budget_guard().record_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    model=resp.model,
                    category="",
                )
                if violations:
                    self._emit("budget_violation", violations=violations)
                    self.state.stopped_because = "budget_exceeded"
                    return self.state

            # --- anti-gira-a-vuoto: la stessa identica chiamata ripetuta --
            #
            # Un modello piccolo che si incanta su un tool che fallisce lo
            # riprova TALE E QUALE: stesso nome, stessi argomenti, stesso
            # errore, un giro di token speso per tornare al punto di
            # partenza. Questa guardia lo becca.
            #
            # La soglia è max_consecutive_errors + 2, NON un numero fisso:
            # sotto quella del breaker, ruberebbe il suo lavoro (il breaker
            # già ferma i loop degenerati, ed è testato). Questo è il caso
            # che il breaker NON copre — la stessa chiamata identica — e sta
            # SOPRA, come rete di sicurezza quando il breaker per qualche
            # motivo non è scattato.
            if resp.tool_calls:
                soglia_ripetuta = self.config.max_consecutive_errors + 2
                ripetuta_troppo = None
                for tc in resp.tool_calls:
                    chiave = f"{tc.name}|{tc.arguments or ''}"
                    self._chiamate_identiche[chiave] = \
                        self._chiamate_identiche.get(chiave, 0) + 1
                    if self._chiamate_identiche[chiave] >= soglia_ripetuta:
                        ripetuta_troppo = (tc.name, tc.arguments)
                        break
                if ripetuta_troppo:
                    nome_rip, args_rip = ripetuta_troppo
                    self._emit("gira_a_vuoto", tool=nome_rip, args=args_rip)
                    self.state.messages.append(Message(
                        role="tool",
                        name="__sistema__",
                        tool_call_id=new_id("sistema"),
                        content=(
                            f"STAI RIPETENDO la stessa chiamata `{nome_rip}` con gli "
                            f"stessi argomenti e torna sempre lo stesso errore. "
                            f"Smetti di riprovarla: è un vicolo cieco. Rispondi "
                            f"adesso con quello che sei riuscito a fare finora, e "
                            f"dì in una riga cosa non ha funzionato e perché. "
                            f"Un «non ce l'ho fatta su {nome_rip}» è una risposta "
                            f"utile; ritentare la stessa chiamata non lo è."),
                    ))
                    self.state.stopped_because = "gira_a_vuoto"
                    return self.state

            # --- caso 1: il modello ha chiesto tool -> esegui e continua
            if resp.wants_tools:
                chiamate = list(resp.tool_calls)
                for i, tc in enumerate(chiamate):
                    if self._cancel_requested():
                        # Ogni tool_call deve avere il suo risultato,
                        # anche quelle mai eseguite: un cancel non puo'
                        # lasciare buchi nella sequenza.
                        for pendente in chiamate[i:]:
                            self.state.messages.append(
                                Message(
                                    role="tool",
                                    content="Cancellato dall'utente prima dell'esecuzione.",
                                    tool_call_id=pendente.id,
                                    name=pendente.name,
                                )
                            )
                            self._emit(
                                "tool_end",
                                name=pendente.name,
                                result="cancellato",
                                ok=False,
                                id=pendente.id,
                                consecutive_errors=self.state.consecutive_errors,
                            )
                        self.state.stopped_because = "canceled_da_should_continue"
                        return self.state
                    args = tc.parsed_args()
                    self.state.tool_calls_made += 1
                    self._vuote_di_fila = 0  # ha agito: la fila riparte
                    # `id` va nei due eventi: e' il modo perche' la UI
                    # abbini il risultato al tool giusto quando in un turno
                    # ce n'e' piu' di uno con lo stesso nome.
                    self._emit("tool_start", name=tc.name, args=args, id=tc.id)

                    if tc.args_non_validi():
                        # JSON rotto: NON eseguire. Eseguire con `{}`
                        # sarebbe peggio che non eseguire (write_file
                        # riscriverebbe il file vuoto), e eseguire con
                        # gli argomenti grezzi darebbe un TypeError che
                        # non dice nulla al modello.
                        result = (
                            f"ERRORE DI ARGOMENTI per '{tc.name}': il JSON "
                            f"degli argomenti non e' valido. "
                            f"Inizio: {str(tc.arguments)[:120]!r}")
                        ok = False
                    else:
                        result, ok = self._execute_tool(tc.name, args)

                    # il conteggio errori si azzera SOLO su un tool riuscito.
                    # Azzerarlo sempre — come faceva prima — rendeva il
                    # circuit breaker irraggiungibile: il modelo poteva
                    # sbagliare per sempre fintanto che ogni chiamata
                    # 'riusciva' nel senso debole di aver restituito una
                    # stringa.
                    if ok:
                        self.state.consecutive_errors = 0
                    else:
                        self.state.tool_errors += 1
                        self.state.tool_error_names.append(tc.name)
                        self.state.consecutive_errors += 1

                    self.state.messages.append(
                        Message(
                            role="tool",
                            content=result,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
                    self._emit(
                        "tool_end",
                        name=tc.name,
                        result=result[:500],
                        ok=ok,
                        id=tc.id,
                        consecutive_errors=self.state.consecutive_errors,
                    )

                if self.state.consecutive_errors >= self.config.max_consecutive_errors:
                    self.state.stopped_because = "troppi_errori_consecutivi"
                    return self.state
                continue

            # --- caso 2: risposta testuale -> finito
            #
            # NUDGE ANTI-BOCCA-VUOTA: se il modello chiude il turno
            # annunciando che farà un lavoro ("analizzo il progetto...")
            # ma NON ha eseguito nessun tool, è il sintomo del modello
            # piccolo che, con un contesto ripetitivo, descrive invece di
            # fare. Una volta sola si rimanda indietro con un messaggio
            # esplicito: se il lavoro richiede davvero gli strumenti, deve
            # chiamarli. Il flag `_nudge_fatto` garantisce che sia UNA
            # volta — un loop che si auto-nudga all'infinito sprecherebbe
            # token senza aggiungere niente.
            #
            # Ma UN nudge non basta al narratore a puntate ("cerco...",
            # "ora aggiungo...", "ecco il piano..."): ogni giro sembra
            # quasi lavoro e nessuno lo e'. Dopo il nudge, un secondo
            # annuncio di fila chiude onestamente con "solo_parole":
            # meglio un fallimento dichiarato che un "completato" che
            # non ha completato niente. Le risposte vere (senza annunci,
            # o dopo aver usato tool) non passano di qui.
            if self.state.tool_calls_made == 0:
                self._vuote_di_fila += 1
                annuncio = self._annuncia_senza_fare(resp.content)
                if annuncio and not self._nudge_fatto:
                    self._nudge_fatto = True
                    self.state.messages.append(Message(
                        role="tool",
                        tool_call_id=new_id("nudge"),
                        content=(
                            "NOTA DEL SISTEMA: hai descritto il lavoro ma non hai "
                            "ancora usato nessuno strumento. Se la richiesta "
                            "richiede dati che non hai a memoria — il contenuto di "
                            "file, lo stato del progetto, un fatto da verificare — "
                            "chiama gli strumenti (list_dir, read_file, web_cerca) "
                            "ORA. Se invece puoi rispondere solo con quello che sai, "
                            "rispondi e basta: non serve ripetere l'annuncio."),
                        name="__nudge__",
                    ))
                    self._emit("nudge", testo=resp.content[:120])
                    continue
                if annuncio and self._nudge_fatto:
                    # Secondo annuncio di fila dopo il nudge: non agira',
                    # sta narrando. Chiudere come risposta_finale
                    # mentirebbe ("completato" senza aver completato).
                    self._emit("solo_parole",
                               testo=resp.content[:120],
                               giri=self._vuote_di_fila)
                    self.state.stopped_because = "solo_parole"
                    return self.state
                if self._vuote_di_fila >= 4:
                    # Rete di sicurezza per i giri con verifica: testi
                    # veri ma mai un tool, a ripetizione, non e' lavoro.
                    self._emit("solo_parole",
                               testo=resp.content[:120],
                               giri=self._vuote_di_fila)
                    self.state.stopped_because = "solo_parole"
                    return self.state

            # --- self-correzione: verificare prima di chiudere -------------
            #
            # Il modello dice "fatto". Prima di accettarlo, se questo task
            # ha una specifica di verifica, la eseguiamo: controlli
            # OGGETTIVI sul risultato (file c'è, JSON valido, codice
            # eseguito dà il numero atteso). Se non torna, NON chiudere:
            # inietta l'errore esatto e rimanda il modello indietro.
            #
            # Mai un modello che giudica un modello — quello premia il più
            # verboso. Qui si controlla il risultato, e il motivo è la
            # prova. Tetto ai tentativi: oltre, il lavoro imperfetto col
            # motivo vince su un loop che brucia token.
            if self.config.verifica_compito is not None and not self._verifica_esaurita:
                self._verifica_tentativo += 1
                from .autoverifica import verifica_compito, nota_per_modello
                specifica = self.config.verifica_compito
                esito = verifica_compito(
                    verificatori=specifica.get("verificatori", []),
                    work=specifica.get("work", ""),
                )
                self._emit("verifica", ok=esito.ok, motivo=esito.motivo,
                           tentativo=self._verifica_tentativo,
                           verificatore=esito.verificatore)
                if esito.ok:
                    self.state.stopped_because = "risposta_finale"
                    return self.state
                if self._verifica_tentativo >= specifica.get(
                        "max_tentativi", self.config.max_tentativi_verifica):
                    self._verifica_esaurita = True
                    self._emit("verifica_esaurita",
                               motivo=esito.motivo,
                               tentativi=self._verifica_tentativo)
                    self.state.stopped_because = "verifica_fallita"
                    return self.state
                self.state.messages.append(Message(
                    role="tool",
                    content=nota_per_modello(
                        esito, self._verifica_tentativo,
                        specifica.get("max_tentativi",
                                      self.config.max_tentativi_verifica)),
                    tool_call_id=new_id("verifica"),
                    name="__verifica__",
                ))
                continue

            self.state.stopped_because = "risposta_finale"
            return self.state

        self.state.stopped_because = "max_iterations"
        return self.state

    @staticmethod
    def _annuncia_senza_fare(testo: str) -> bool:
        """Riconosce una pura annunciazione di lavoro, non una risposta.

        Distingue "analizzo il progetto e ti dico" (bocca vuota) da "ecco
        la valutazione, punto 1..." (risposta vera). Euristiche dichiarate,
        non magia: cerca il verbo all'inizio con un ANCORAGGIO, così
        "Punto 1: devo verificare" NON scatta — là il verbo è a metà e c'è
        contenuto. Sottile per costruzione: meglio un falso negativo (il
        modello parla a vuoto una volta) che un falso positivo (Orchestra
        interrompe una risposta vera perché conteneva la parola
        "analizzo").
        """
        if not testo:
            return False
        t = testo.strip()
        # corta e con verbo annuncia in testa -> bocca vuota. Lunga o con
        # sostanza -> vera risposta, anche se contiene "analizzo".
        ANNUNCI = (
            "analizz", "valuterò", "valutero", "iniziamo", "procedo",
            "esaminerò", "esaminero", "controllo", "verifico il",
            "leggo il", "esplor", "occupo la sessione", "mi occupo",
            "cerco", "eseguo", "ecco il piano",
        )
        testa = t[:40].lower()
        if any(a in testa for a in ANNUNCI):
            pass
        else:
            # Promessa di lavoro futuro a meta' frase ("ho il quadro, ora
            # applico...", "provvedo subito"): il verbo non e' in testa ma
            # il turno chiude lo stesso senza aver fatto niente. Si cerca
            # nei primi 160 caratteri dei testi corti: una risposta vera e'
            # piu' lunga o non promette azioni.
            corpo = t[:160].lower()
            if not (len(t) <= 220 and t.count("\n") < 3 and (
                    any("ora " + v in corpo for v in (
                        "applico", "applicare", "procedo", "modifico",
                        "aggiorno", "sistemo", "correggo", "aggiungo",
                        "creo", "scrivo", "leggo", "controllo", "verifico",
                        "esamino", "inizio"))
                    or any(p in corpo for p in (
                        "sto per", "provvedo", "applico", "modifico",
                        "aggiorno", "sistemo", "correggo", "aggiungo",
                        "creo", "scrivo")))):
                return False
        # se è lunga e ha struttura (elenchi, più righe), è una risposta
        if len(t) > 220 or t.count("\n") >= 3:
            return False
        return True

    def _call_model_with_retry(self) -> LLMResponse:
            """Retry sui soli errori transitori (429/5xx/rete) con fallback chain.

            Se il provider corrente fallisce in modo non recuperabile,
            passa al prossimo nella catena di fallback.
            """
            # Inizializza lo stato di fallback se non esiste
            if self._fallback_state is None:
                self._fallback_state = FallbackState(entries=self.fallback_chain)

            fs = self._fallback_state
            last_error: Exception | None = None

            while fs.current:
                entry = fs.current
                self._emit("fallback_attempt", provider=entry.provider, model=entry.model,
                           attempt=fs.attempts_on_current + 1, index=fs.current_index)

                # Crea il provider per questa entry se non è il primo (che abbiamo già)
                if fs.current_index == 0:
                    provider = self.provider
                else:
                    from .providers import build_provider, ambiente
                    env = ambiente(ENV_PATH)
                    try:
                        provider = build_provider(
                            entry.provider,
                            model=entry.model,
                            env=env,
                        )
                        provider.timeout = entry.timeout
                    except Exception as e:
                        self._emit("fallback_provider_error", provider=entry.provider,
                                   error=str(e))
                        if not fs.advance(FallbackReason.UNAVAILABLE, str(e)):
                            break
                        continue

                # Retry loop per questo provider
                for attempt in range(entry.max_retries + 1):
                    try:
                        # Lo streaming: i pezzi del ragionamento arrivano
                        # mentre il modello li scrive. Verificato — 2240
                        # eventi e 14068 caratteri su una domanda di fisica,
                        # tutti buttati prima perché `chat()` prendeva la
                        # risposta in blocco.
                        #
                        # Il fallback sul metodo in blocco è dentro
                        # `chat_stream`, quindi un provider che non lo fa
                        # non rompe niente.
                        if hasattr(provider, "chat_stream"):
                            return provider.chat_stream(
                                self.state.messages,
                                self.registry.api_payload(),
                                temperature=entry.temperature,
                                max_tokens=entry.max_tokens,
                                reasoning_level=self.config.reasoning_level,
                                on_event=self._on_stream,
                            )
                        return provider.chat(
                            self.state.messages,
                            self.registry.api_payload(),
                            temperature=entry.temperature,
                            max_tokens=entry.max_tokens,
                            reasoning_level=self.config.reasoning_level,
                        )
                    except ProviderError as e:
                        last_error = e
                        reason = should_fallback(e)

                        if reason is None or not e.retryable:
                            # Errore non recuperabile -> fallback immediato
                            self._emit("fallback_triggered", provider=entry.provider,
                                       reason=reason.value if reason else "non_retryable",
                                       error=str(e))
                            break

                        if attempt == entry.max_retries:
                            # Retry esauriti su questo provider -> fallback
                            reason = FallbackReason.MAX_RETRIES
                            self._emit("fallback_triggered", provider=entry.provider,
                                       reason=reason.value, error=str(e))
                            break

                        # Retry con backoff
                        import time
                        attesa = min(max(getattr(e, "retry_after", 0.0),
                                         2.0 ** attempt * 0.5), 120.0)
                        self._emit("retry", provider=entry.provider,
                                   attempt=attempt + 1, error=str(e), attesa=attesa)
                        time.sleep(attesa)
                    except Exception as e:
                        # Errore di rete generico
                        last_error = e
                        reason = FallbackReason.NETWORK_ERROR
                        if attempt == entry.max_retries:
                            self._emit("fallback_triggered", provider=entry.provider,
                                       reason=reason.value, error=str(e))
                            break
                        import time
                        attesa = min(2.0 ** attempt * 0.5, 30.0)
                        self._emit("retry", provider=entry.provider,
                                   attempt=attempt + 1, error=str(e), attesa=attesa)
                        time.sleep(attesa)

                # Se arriviamo qui, tutti i retry per questo provider hanno fallito
                fs.attempts_on_current += 1
                if not fs.advance(reason or FallbackReason.MAX_RETRIES, str(last_error)):
                    break  # niente più fallback

            # Tutti i fallback esauriti
            self._emit("fallback_exhausted", history=fs.history)
            if last_error:
                raise last_error
            # Catena vuota dall'inizio: nessun provider provato, nessun
            # errore da riportare. Il messaggio generico nascondeva il
            # vero problema — catena non costruita o modello primario
            # assente — e per chi guardava era un vicolo cieco muto.
            # Qui si dice quale provider si stava usando e cosa manca,
            # che è l'unica informazione utile per rimediare.
            primario = self.fallback_chain[0] if self.fallback_chain else None
            raise RuntimeError(
                "Nessun provider disponibile: la catena di fallback è vuota "
                f"(provider attivo: {primario.provider if primario else 'nessuno'}, "
                f"modello: {getattr(self.provider, 'model', '?')}). "
                "Controlla in Opzioni che il provider e il modello siano validi "
                "e che la chiave del provider sia configurata.")

        # -- output ------------------------------------------------------------

    def final_text(self) -> str:
        for m in reversed(self.state.messages):
            if m.role == "assistant" and m.content.strip():
                return m.content.strip()
        return ""

    def transcript(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.state.messages]
