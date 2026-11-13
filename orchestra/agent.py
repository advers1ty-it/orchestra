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
import re
import time
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

from .context import Summarizer, count_tokens, fit_context
from .providers import ProviderError
from .fallback import (
    ChainEntry, FallbackState, FallbackReason,
    should_fallback
)
from .budget import budget_guard, BudgetLimits
from . import piano as piano_mod
from . import parallelo as parallelo_mod
from . import redazione
from .types import (
    LLMResponse, Message, ToolCall, ToolRegistry, ToolResult, new_id,
)

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
    # Le chiamate di sola lettura di uno stesso giro partono insieme
    # (vedi orchestra/parallelo.py). Spegnibile perche' e' un'ottimizzazione
    # di tempo, non una funzione: chi vuole la sequenza esatta la chiede.
    parallelo: bool = True
    # Tetto di OROLOGIO al turno, in secondi. 0 o negativo = nessun tetto.
    #
    # Le iterazioni erano limitate, il tempo no: venti giri con dentro
    # `esegui_test` da due minuti, un browser da quaranta secondi e un MCP
    # da trenta fanno un turno da mezz'ora. Il sintomo per l'utente e' "si
    # e' impallato", e l'unica uscita era premere stop. Il tetto serve a
    # questo, non a risparmiare token: a contare le chiamate c'e' gia'
    # `max_iterations`.
    max_secondi_turno: float = 900.0


def impostazioni(env: dict[str, str] | None = None) -> dict[str, str]:
    """La configurazione effettiva: il `.env` sotto, l'ambiente sopra.

    Un solo posto che decide la precedenza, e vale per tutti. L'ambiente
    di sistema vince — come in `cli._env()` — perche' un valore esportato
    per una sola esecuzione deve contare, mentre il `.env` resta la fonte
    salvata dalle impostazioni.

    Passare un dizionario gia' letto NON scavalca la regola: chi tiene
    `self.env` (il server, letto all'avvio) altrimenti non vedrebbe una
    variabile esportata dopo, e la stessa impostazione varrebbe in un
    percorso e non in un altro.
    """
    if env is None:
        from .providers import ambiente
        return ambiente(ENV_PATH)
    return {**env, **os.environ}


def valore_da_env(env, chiave: str, default, cast):
    """Un valore tipizzato dalle impostazioni, o il default se manca/storto.

    `cast` e' `int` o `float`: un `ORCHESTRA_MAX_TOKENS=boh` deve tornare
    al default, non far saltare l'avvio dell'agente.
    """
    try:
        return cast(impostazioni(env).get(chiave, default))
    except (TypeError, ValueError):
        return default


def parametri_da_env(env=None) -> dict[str, Any]:
    """`temperature` e `max_tokens` come li imposta l'utente.

    Chi costruisce un `LoopConfig` per conto suo — il goal, i figli della
    delega — li passa con `**parametri_da_env(env)` invece di ricopiare
    i default. Senza, quei percorsi restavano a 4096 qualunque cosa
    dicesse il `.env`: con `reasoning: max` il tetto si esauriva dentro
    il ragionamento e la risposta arrivava troncata anche dopo aver
    alzato la variabile.
    """
    return {"temperature": valore_da_env(env, "ORCHESTRA_TEMPERATURE",
                                       0.7, float),
            "max_tokens": valore_da_env(env, "ORCHESTRA_MAX_TOKENS",
                                        4096, int)}


@dataclass
class AgentState:
    """Stato ispezionabile della run. Lo teniamo esplicito perché un
    orchestratore senza stato introspettabile è una scatola nera."""

    messages: list[Message] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    # Il costo stimato del turno, in dollari. Si accumula a ogni risposta
    # col tariffario, non solo quando c'e' un budget da controllare: il
    # riepilogo di fine turno lo mostra, e senza questo resterebbe zero
    # per chi non ha budget configurati.
    total_cost_usd: float = 0.0
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


# ------------------------------------------------------ annuncio a vuoto
#
# Il vocabolario del nudge anti-bocca-vuota. Sta qui, fuori dalla classe,
# perche' e' un dato: si legge e si corregge senza toccare la logica.
#
# Perche' e' cosi' largo: ogni forma mancante e' un turno in cui il
# modello promette e chiude, e l'utente vede "risponde a caso". E'
# successo con "Faccio le modifiche vere ora" e "Prima indago il modal
# tracce" — due frasi normali, e nessuna delle due era in elenco.

# Verbi d'azione in prima persona che aprono il testo.
_ANNUNCI_IN_TESTA = (
    "analizz", "valuterò", "valutero", "iniziamo", "procedo",
    "esaminerò", "esaminero", "controllo", "verifico il",
    "leggo il", "esplor", "occupo la sessione", "mi occupo",
    "cerco", "eseguo", "ecco il piano",
    # le forme che Beam usa davvero
    "indago", "indagherò", "indaghero", "comincio", "inizio",
    "passo a", "mi metto", "vado a", "diamo un'occhiata",
    "torno con", "guardo il", "apro il", "provo a", "lancio",
)

# Verbi d'azione in prima persona, ovunque nel testo (presente o futuro).
# Con \b, o "ancora" conterebbe come "ora".
_AZIONI = re.compile(
    r"\b(faccio|farò|faro|indago|indagherò|indaghero|comincio|inizio|"
    r"passo a|mi metto|vado a|modifico|modificherò|modifichero|sistemo|"
    r"sistemerò|sistemero|correggo|correggerò|correggero|aggiungo|"
    r"aggiungerò|aggiorno|aggiornerò|applico|applicherò|creo|creerò|"
    r"scrivo|scriverò|leggo|leggerò|controllo|controllerò|verifico|"
    r"verificherò|eseguo|eseguirò|provo|proverò|apro|aprirò|lancio|"
    r"lancerò|guardo|guarderò|analizzo|analizzerò|esamino|esaminerò|"
    r"esploro|esplorerò|procedo|mi occupo|torno con)\b"
)

# Marcatori di tempo: la promessa e' "adesso/ora/poi", non un risultato.
_TEMPO = re.compile(
    r"\b(ora|adesso|subito|prima|poi|dopo|step by step|a breve|"
    r"in questo momento|a seguire)\b"
)

# Promesse che il tempo non ce l'hanno: da sole bastano.
_PROMESSE = (
    "sto per", "provvedo", "mi metto", "vado a", "comincio",
    "inizio a", "passo a", "ecco il piano", "diamo un'occhiata",
    "torno con",
)

# I due testi del nudge. Sono due perche' il caso e' diverso: dopo venti
# tool, "non hai ancora usato nessuno strumento" sarebbe falso, e un
# messaggio falso e' peggio di nessun messaggio.
_NUDGE_SENZA_TOOL = (
    "NOTA DEL SISTEMA: hai descritto il lavoro ma non hai ancora usato "
    "nessuno strumento. Se la richiesta richiede dati che non hai a "
    "memoria — il contenuto di file, lo stato del progetto, un fatto da "
    "verificare — chiama gli strumenti (list_dir, read_file, web_cerca) "
    "ORA. Se invece puoi rispondere solo con quello che sai, rispondi e "
    "basta: non serve ripetere l'annuncio."
)

_NUDGE_DOPO_LAVORO = (
    "NOTA DEL SISTEMA: hai annunciato altro lavoro, ma il turno sta per "
    "chiudere senza farlo. Se c'e' ancora qualcosa da fare, chiama gli "
    "strumenti ORA e fallo. Se hai finito, dillo in modo esplicito — cosa "
    "hai fatto e cosa resta — senza promettere altro: un annuncio non e' "
    "un risultato."
)


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
            # Modalita' piano: i tool che modificano sono bloccati finche'
            # `proponi_piano` non ottiene un'approvazione. Vive sull'agente
            # (non sulla sessione) perche' vale anche per CLI, benchmark e
            # delega, dove una Session non c'e'.
            self.modalita_piano = False
            self.provider = provider
            self.registry = registry
            self.system_prompt = system_prompt
            # Da quale porta e' arrivato il turno in corso: vuoto per la
            # finestra, "Telegram (chat ...)" per il ponte. Non e' un
            # dettaglio di UI — e' l'unica cosa che permette all'agente di
            # sapere dove sta scrivendo, perche' il turno Telegram e' lo
            # stesso turno della finestra.
            self.canale: str = ""
            # Il progetto su cui si lavora. Va sull'agente e non solo sulla
            # sessione perche' e' l'agente a dover cercare i fatti giusti:
            # la sessione etichetta quelli che nascono, l'agente deve
            # sapere quale filtro usare per recuperarli.
            self.progetto: str = ""
            self.config = config or LoopConfig()
            self.summarize = summarize
            self.on_event = on_event or (lambda kind, data: None)
            self.state = AgentState(messages=[Message(role="system", content=system_prompt)])
            # Catena di fallback: se nessuno ne passa una, il SOLO
            # primario. La catena con i ripieghi la impone chi la sa —
            # web, CLI, goal, figlio della delega — con
            # `catena_per_agente`.
            #
            # Prima qui si costruiva da `DEFAULT_CHAINS`, una tabella che
            # nomina servizi che chi usa Orchestra puo' non avere (chi ha
            # solo Nous si vedeva fallire ogni tentativo). In benchmarking
            # e council era peggio che inutile: un ripiego su un altro
            # provider attribuisce la risposta al modello sotto test —
            # `RunResult` porta l'id misurato — quindi il numero
            # descriverebbe un altro modello.
            if fallback_chain is None:
                self.fallback_chain = [ChainEntry(
                    provider=str(getattr(provider, "name", "") or ""),
                    model=str(getattr(provider, "model", "") or ""),
                )]
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
            # Quante volte la risposta e' arrivata troncata dal tetto di
            # output. Serve al tetto dei "continua": senza, un modello con
            # max_tokens basso brucerebbe tutte le iterazioni a riprovare.
            self._troncamenti: int = 0
            # Budget. Lo stato si crea SEMPRE, anche senza limiti espliciti:
            # saltare la creazione perche' "non mi hanno passato niente"
            # faceva leggere il .env a BudgetGuard senza che nessuno gli
            # chiedesse niente -- il limite era salvato, mostrato nel
            # pannello, e non applicato da nessuna parte.
            #
            # Lo stato e' uno solo, trasversale a tutti i modelli: il tetto
            # risponde a "quanto ho speso", e la bolletta non distingue.
            # `session_id` non serve piu' a niente, resta per la firma.
            # `limits=` per nome, non posizionale: il primo parametro e'
            # `session_id` (ora ignorato ma ancora nella firma), quindi
            # passare i limiti come primo argomento li buttava via e
            # lasciava leggere il .env. Un limite scritto nella config e
            # mai applicato e' peggio di nessun limite, perche' sembra
            # esserci.
            self._budget_state = budget_guard().get_or_create_session(
                limits=self.config.budget_limits)

            # -- utility interne ---------------------------------------------------

    def _cancel_requested(self) -> bool:
        """Verifica se è stata richiesta la cancellazione."""
        return self._cancel_flag

    def _tempo_scaduto(self) -> bool:
        """True se il turno ha superato il suo tetto di orologio.

        Il valore si legge a ogni chiamata, non si cattura all'init: una
        config cambiata a caldo (o un test) deve valere subito, e con il
        valore catturato un `max_secondi_turno=0` deciso dopo l'avvio
        continuerebbe a fermare i turni.
        """
        try:
            limite = float(self.config.max_secondi_turno or 0)
        except (TypeError, ValueError):
            return False
        if limite <= 0:
            return False
        inizio = getattr(self, "_inizio_turno", None)
        if inizio is None:
            return False
        return (time.monotonic() - inizio) > limite

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

    def _prepara_parallelo(
        self, chiamate: list[ToolCall]
    ) -> tuple[dict[str, tuple], set[str]]:
        """Esegue insieme le chiamate di sola lettura di questo giro.

        Ritorna ({id: esito}, {id gia' avviati}). Vuoto vuol dire "in
        fila": un giro misto (legge e scrive) non e' parallelizzabile,
        perche' l'ordine e' informazione e due scritture sullo stesso file
        sarebbero una corsa. Anche un argomento rotto manda tutto in fila:
        quel ramo deve produrre l'errore nell'ordine giusto.

        Il cancel si controlla PRIMA di partire: annullare a meta' batch
        lascerebbe tool gia' in volo senza un posto dove scrivere l'esito.
        """
        if not getattr(self.config, "parallelo", True) or len(chiamate) < 2:
            return {}, set()
        if self._cancel_requested():
            return {}, set()
        for tc in chiamate:
            tool = self.registry.get(tc.name)
            if (tool is None or tc.args_non_validi()
                    or not parallelo_mod.sola_lettura(tc.name)):
                return {}, set()
            # La modalita' piano non c'entra con la lettura, ma se un
            # giorno un tool finisse in entrambi gli elenchi il blocco
            # deve valere anche qui.
            if (self.modalita_piano and not piano_mod.approvato()
                    and tc.name in piano_mod.TOOL_CHE_CAMBIANO):
                return {}, set()

        # Tutti gli start subito: la UI deve vedere cinque righe che
        # partono insieme, non cinque che partono dopo che hanno finito.
        for tc in chiamate:
            self._emit("tool_start", name=tc.name, args=tc.parsed_args(),
                       id=tc.id)

        import concurrent.futures as cf

        esiti: dict[str, tuple] = {}
        with cf.ThreadPoolExecutor(max_workers=min(4, len(chiamate))) as pool:
            futuri = {
                pool.submit(self._execute_tool, tc.name, tc.parsed_args()): tc
                for tc in chiamate
            }
            for futuro, tc in futuri.items():
                try:
                    esiti[tc.id] = futuro.result()
                except Exception as e:  # noqa: BLE001 - un tool non uccide il turno
                    esiti[tc.id] = (
                        f"ERRORE nel tool '{tc.name}': {e}", False, [], [])
        return esiti, {tc.id for tc in chiamate}

    def _execute_tool(
        self, name: str, args: dict[str, Any]
    ) -> tuple[str, bool, list[str], list[str]]:
        """Esegue un tool e restituisce (testo, riuscito, immagini, anteprime).

        Restituisce SEMPRE una stringa, mai solleva. Vedi invariante 1: è
        deliberato, un agente che si blocca su un errore recuperabile è un
        agente che spreca soldi.

        Il secondo valore serve al chiamante: `riuscito` è False anche quando
        il testo è un messaggio d'errore, e senza questo il circuit breaker
        non ha modo di sapere che il modello sta sbagliando.

        Il terzo sono le immagini da mettere nel messaggio `tool`. Quasi
        sempre vuoto: solo i tool che devono far VEDERE qualcosa (uno
        screenshot, una pagina renderizzata) lo riempiono. Senza, il
        modello riceve "screenshot salvato in ..." e non ha modo di
        guardare lo schermo — il tool esiste ma è inutile.

        Il quarto sono le anteprime per la UI: stesse immagini, ma non
        tornano al modello. Un'immagine generata non serve rimandarla a chi
        l'ha chiesta per prompt, e un'immagine dentro un messaggio `tool` non
        e' accettata da tutti i provider compatibili.
        """
        tool = self.registry.get(name)
        if tool is None:
            return (
                f"ERRORE: tool inesistente '{name}'. "
                f"Disponibili: {', '.join(self.registry.all_names())}",
                False,
                [],
                [],
            )

        # Modalita' piano: il blocco sta QUI e non nei singoli tool.
        # Sparso nei tool, dimenticarsene in uno solo basta a rendere la
        # modalita' una promessa: un tool nuovo che scrive non la
        # rispetterebbe finche' qualcuno non si ricorda di aggiungerlo.
        if (self.modalita_piano and not piano_mod.approvato()
                and name in piano_mod.TOOL_CHE_CAMBIANO):
            return (piano_mod.BLOCCATO.format(nome=name), False, [], [])

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
                return text, True, [], []

            result = tool.handler(**args)
            if hasattr(result, "__await__"):
                import asyncio

                result = asyncio.run(result)
            if isinstance(result, ToolResult):
                text = result.text
                immagini = list(result.immagini)
                anteprime = list(result.anteprime)
                # Un'immagine non si cachea: dipende dal mondo (lo schermo
                # cambia), e il testo da solo non la riproduce. Metterla in
                # cache darebbe al modello lo schermo di cinque minuti fa.
                cachevole = not immagini and not anteprime
            else:
                text = (result if isinstance(result, str)
                        else json.dumps(result, default=str))
                immagini = []
                anteprime = []
                cachevole = True
            # Si cachea solo il successo: un errore transitorio inchiodato
            # per 5 minuti sarebbe peggio che ricalcolarlo.
            if cachevole:
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
                    f"{dettaglio}"), False, [], []
        except Exception as e:
            self._emit(
                "tool_error",
                tool=name,
                error=f"{type(e).__name__}: {e}",
                trace=traceback.format_exc(limit=3),
            )
            return (f"ERRORE durante l'esecuzione di '{name}': "
                    f"{type(e).__name__}: {e}"), False, [], []

        if len(text) > self.config.tool_timeout_chars:
            text = (
                text[: self.config.tool_timeout_chars]
                + f"\n\n[TRONCATO: {len(text)} caratteri totali, mostro i primi "
                f"{self.config.tool_timeout_chars}]"
            )
        return text, True, immagini, anteprime

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

    def _ha_il_tool(self, nome: str) -> bool:
        """Vero se quel tool e' fra gli attivi di questo turno."""
        try:
            return nome in {t.name for t in self.registry.active}
        except Exception:  # noqa: BLE001 - se non si sa, non si promette
            return False

    def _blocco_canale(self) -> str:
        """Da quale porta e' arrivato questo turno, quando non e' la finestra.

        Il messaggio che arriva dal ponte Telegram e' indistinguibile da
        uno scritto nella finestra: `Session.send` fa la stessa cosa nei
        due casi, stessa sessione e stessa cronologia. Senza questa riga
        l'agente non ha nessun modo di saperlo, e alla richiesta "mandami
        le previsioni su Telegram" risponde "non posso inviarti messaggi
        su Telegram" — mentre la risposta viaggia proprio su quel ponte.
        Non e' un'ipotesi: e' quello che e' successo davvero.

        Vuoto per un turno normale. La finestra non ha bisogno di
        presentarsi, e un blocco in piu' su ogni richiesta e' contesto
        pagato a ogni token per non dire niente di nuovo.
        """
        canale = (getattr(self, "canale", "") or "").strip()
        if not canale:
            return ""
        righe = [
            "## Da dove arriva questo turno",
            f"Questo messaggio arriva da {canale}, non dalla finestra di "
            "Orchestra: chi scrive ti legge da li', ma la macchina su cui "
            "lavori resta la sua. Il computer dove e' installato Orchestra "
            "E' il computer dell'utente: scrivere dal telefono non vuol dire "
            "essere su un'altra macchina, e i tool agiscono su quella.",
        ]
        if self._ha_il_tool("telegram_invia"):
            righe.append(
                "Se ti chiede di mandargli qualcosa piu' tardi o di tua "
                "iniziativa, il tool `telegram_invia` scrive in quella "
                "chat: non serve nessun token, il collegamento c'e' gia'.")
        return "\n".join(righe) + "\n\n"

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
        # Il progetto viene DOPO le skill: le skill dicono COME
        # lavorare, il progetto dice SU COSA.
        #
        # La modalita' piano viene PRIMA di tutto: cambia cosa puo'
        # fare l'agente, e leggerlo dopo le skill lo rende una nota a
        # pie' di pagina su un divieto che sta gia' incontrando.
        blocco_piano = ""
        if self.modalita_piano:
            blocco_piano = (
                "## Modalita' piano ATTIVA\n"
                "I tool che modificano (scritture, shell, test, cron, MCP) "
                "sono bloccati finche' `proponi_piano` non riceve "
                "un'approvazione. Leggi e cerca quanto basta a capire, poi "
                "proponi UN piano con `proponi_piano`: cosa hai capito, i "
                "file che tocchi, i comandi che esegui. Dopo "
                "l'approvazione esegui esattamente quei passi, senza "
                "allargarti. Se l'utente rifiuta, non insistere con lo "
                "stesso piano: chiedi cosa cambiare o fermati.\n\n")
        canale = self._blocco_canale()
        volatile = (blocco_piano + canale + extra + progetto).strip()
        # PERCHE' DUE MESSAGGI DI SISTEMA E NON UNO.
        #
        # Il primo blocco (regole, persona, memoria) e' il prefisso che i
        # provider mettono in cache. Le skill e il progetto cambiano con
        # l'ultimo messaggio utente: se stessero dentro quel blocco, ogni
        # turno cambierebbe il prefisso e la cache non colpirebbe MAI,
        # rendendo inutile marcare system e tool. Qui il blocco volatile
        # sta dopo il primo, quindi non invalida il prefisso.
        if not volatile:
            self._rimuovi_contesto_volatile()
            return
        contesto = None
        for m in self.state.messages:
            if m.role == "system" and m.name == "__contesto__":
                contesto = m
                break
        if contesto is None:
            inserimento = 0
            for i, m in enumerate(self.state.messages):
                if m.role == "system":
                    inserimento = i + 1
            contesto = Message(role="system", content=volatile,
                               name="__contesto__")
            self.state.messages.insert(inserimento, contesto)
        else:
            contesto.content = volatile
        # Il blocco stabile resta quello di partenza. Se l'identita' e'
        # cambiata, `self.system_prompt` e' gia' quello nuovo e va
        # riallineato qui: il vecchio contenuto potrebbe essere rimasto
        # nella lista da prima del cambio.
        for m in self.state.messages:
            if m.role == "system" and m.name != "__contesto__":
                m.content = self.system_prompt
                break

    def _rimuovi_contesto_volatile(self) -> None:
        """Toglie il blocco skill/progetto quando non c'e' piu' nulla.

        Senza, cambiando progetto verso una cartella senza istruzioni il
        modello continuerebbe a leggere quelle del progetto precedente.
        """
        rimasti = [m for m in self.state.messages
                   if not (m.role == "system" and m.name == "__contesto__")]
        if len(rimasti) != len(self.state.messages):
            self.state.messages[:] = rimasti
        for m in self.state.messages:
            if m.role == "system":
                m.content = self.system_prompt
                break

    def steer(self, testo: str) -> bool:
        """Inietta un messaggio durante il turno in corso."""
        if len(self.state.steer_queue) >= self.state.steer_max:
            return False
        self.state.steer_queue.append(testo)
        return True

    def _nota_sistema(self, testo: str, nome: str) -> None:
        """Appende una nota di sistema come coppia assistant/tool valida.

        I messaggi di sistema (nudge, verifica, steer, gira-a-vuoto) sono
        role="tool" con un tool_call_id inventato: non sono il risultato di
        una tool_call che il modello abbia fatto. I gateway permissivi
        (longcat, laguna) li accettano lo stesso; quelli stretti no:
        Beam 1.0 risponde 400 "messages[N] is a tool result, but it does
        not follow an assistant message with 'tool_calls' or its
        results", e il turno si interrompe senza riprendersi.

        Dare un id non basta: serve il PAIRING. La nota e' preceduta da
        un assistant con una tool_call fittizia che porta lo stesso id —
        il risultato segue la chiamata, e la sequenza e' valida ovunque.

        L'assistant fittizio ha content vuoto: non finisce nello storico
        (che tiene solo i messaggi con contenuto) e non genera eventi,
        quindi l'utente non lo vede mai.
        """
        nome = nome or "__sistema__"
        cid = new_id(nome.strip("_"))
        self.state.messages.append(Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=cid, name=nome, arguments="{}")],
            # `name` marca la coppia come sintetica: lo snapshot lo usa per
            # non disegnarla come un tool card "__nudge__" (vedi session.py).
            name=nome,
        ))
        self.state.messages.append(Message(
            role="tool",
            tool_call_id=cid,
            name=nome,
            content=testo,
        ))

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

        # Il ponte per la modifica: `immagine` non vede i messaggi, quindi
        # le immagini appena allegate restano raggiungibili da li'. Senza,
        # "modifica la foto che ti ho mandato" non avrebbe una foto.
        try:
            from .attachments import registra_immagini

            registra_immagini(immagini)
        except Exception:  # noqa: BLE001 - non deve fermare un turno
            pass

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
        # L'orologio del turno parte qui, insieme al flag di cancel: il
        # tempo si conta dall'inizio del lavoro, non dall'istanza
        # dell'agent, che sopravvive a molti turni.
        self._inizio_turno = time.monotonic()
        # L'approvazione di un piano vale per il turno in cui e' stata
        # data. Al turno dopo si torna a proporre: e' il senso della
        # modalita', e un'approvazione che resta accesa trasforma la
        # prima volta in un permesso permanente.
        piano_mod.nuovo_turno()
        # Il confine del diff multi-file: da qui in poi ogni scrittura
        # appartiene a questo turno, e la vista delle modifiche parte da
        # questo istante. Non azzera i backup, quindi l'undo continua a
        # funzionare anche su cio' che e' stato scritto prima.
        try:
            from . import checkpoint as checkpoint_mod
            checkpoint_mod.nuovo_turno()
        except Exception:  # noqa: BLE001 - un diff mancante non ferma il turno
            pass

        if self._budget_state:
            self._budget_state.reset_task()
        # Il nudge e la verifica ripartono puliti a ogni turno: appartenevano
        # alla domanda di prima.
        self._nudge_fatto = False
        self._vuote_di_fila = 0
        self._verifica_tentativo = 0
        self._verifica_esaurita = False
        self._chiamate_identiche = {}
        self._troncamenti = 0

        for self.state.iterations in range(1, self.config.max_iterations + 1):
            if should_continue and not should_continue(self.state):
                self.state.stopped_because = "canceled_da_should_continue"
                return self.state

            # Tetto di orologio. Si controlla all'inizio del giro, dove
            # costa niente e dove il turno e' in un punto coerente: fra
            # una richiesta al modello e il batch di tool. Il messaggio
            # resta nel contesto, cosi' il turno dopo sa perche' il
            # lavoro si e' fermato invece di ritrovarsi un buco.
            if self._tempo_scaduto():
                secondi = int(self.config.max_secondi_turno)
                self._nota_sistema(
                    f"[TEMPO MASSIMO DEL TURNO] Sono passati {secondi} "
                    f"secondi: il turno si ferma qui. Il lavoro fatto resta, "
                    f"ma quello che mancava va chiesto di nuovo — scegli un "
                    f"passo piu' piccolo, o alza ORCHESTRA_MAX_SECONDI_TURNO.",
                    "__sistema__",
                )
                self.state.stopped_because = "tempo_scaduto"
                return self.state

            self._maybe_compact()

            # --- steer: inietta messaggi esistenti dal queue ---
            if self.state.steer_queue:
                testo = self.state.steer_queue.pop(0)
                self.state.steer_count += 1
                self._nota_sistema(
                    f"[MESSAGGIO DURANTE IL LAVORO — steer #{self.state.steer_count}]\n"
                    f"{testo}\n"
                    f"\n"
                    f"Riconsidera il tuo lavoro alla luce di questa informazione. "
                    f"Continua da dove eri rimasto.",
                    "__steer__",
                )
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
            # Budget, PRIMA di spendere. Il controllo dopo la chiamata
            # registra il costo e poi si accorge dello sforamento: a quel
            # punto i soldi sono usciti, e la chiamata che sfora e' quasi
            # sempre la piu' cara del turno (contesto pieno + output
            # lungo). Qui si stima il caso peggiore col tariffario e si
            # decide se partire.
            if self._budget_state:
                limite_output = int(getattr(self.config, "max_tokens", 4096) or 0)
                # Il prompt si stima, non si conta: sotto di un fattore
                # costante va bene, e la stima e' gia' quella che usa la
                # compaction, quindi i due numeri non si contraddicono.
                token_prompt = count_tokens(self.state.messages)
                modello_now = getattr(self.provider, "model", "") or ""
                try:
                    previste = budget_guard().verifica_preventiva(
                        modello=modello_now,
                        prompt_tokens=token_prompt,
                        max_tokens=limite_output,
                    )
                except Exception:  # noqa: BLE001 - il budget non rompe il turno
                    previste = []
                if previste:
                    self._emit("budget_violation", violations=previste,
                               preventivo=True)
                    self.state.stopped_because = "budget_exceeded"
                    self._nota_sistema(
                        "[BUDGET] Il turno non parte: questa chiamata "
                        "supererebbe il tetto di spesa.\n"
                        + "\n".join(f"- {v}" for v in previste)
                        + "\nAlza il limite con ORCHESTRA_BUDGET, oppure "
                        "chiedi meno in un colpo solo.",
                        "__sistema__",
                    )
                    return self.state

            self._emit("thinking", iteration=self.state.iterations)
            resp = self._call_model_with_retry()
            self.state.total_tokens += resp.total_tokens
            self.state.usage_by_model[resp.model] = (
                self.state.usage_by_model.get(resp.model, 0) + resp.total_tokens
            )
            # Costo stimato: dal tariffario quando il modello c'e', con una
            # stima dichiarata ($1/M) quando non c'e'. Mai zero per un
            # modello a pagamento solo perche' non lo conosciamo.
            try:
                from .prezzi import costo as _costo_turno

                _pt = getattr(resp, "prompt_tokens", 0) or 0
                _ct = getattr(resp, "completion_tokens", 0) or 0
                if _pt == 0 and _ct == 0:
                    _pt = resp.total_tokens // 2
                    _ct = resp.total_tokens - _pt
                _c = _costo_turno(resp.model, _pt, _ct)
            except Exception:  # noqa: BLE001
                _c = None
            if _c is None:
                _c = resp.total_tokens / 1_000_000
            self.state.total_cost_usd += float(_c or 0.0)

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
                # Il prezzo vero, dal tariffario popolato dal catalogo.
                # Se il modello non e' nel tariffario si usa una stima
                # dichiarata ($1 per milione): e' meglio di una costante
                # uguale per tutti, che faceva sembrare caro un modello
                # gratuito e gratis uno da $15/M. La stima resta un
                # ripiego, non la regola.
                try:
                    from .prezzi import costo as _costo

                    cost_usd = _costo(resp.model, prompt_tokens,
                                      completion_tokens)
                except Exception:  # noqa: BLE001
                    cost_usd = None
                if cost_usd is None:
                    cost_usd = (prompt_tokens + completion_tokens) / 1_000_000
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

            # --- risposta troncata dal tetto di output --------------------
            #
            # `finish_reason=length` vuol dire "mi sono fermato perche' non
            # avevo piu' token", NON "ho finito". Trattarla come risposta
            # finale chiude il turno su un testo a meta' e nessuno lo dice:
            # l'utente vede un file che si interrompe a meta' riga e un
            # "completato" sopra. Si continua dal punto in cui il modello
            # si e' fermato, con un tetto ai "continua" per non bruciare il
            # turno se il modello non riesce a stare nel limite.
            motivo_fine = (getattr(resp, "finish_reason", "") or "").lower()
            if (motivo_fine in {"length", "max_tokens", "max_output_tokens"}
                    and not resp.wants_tools):
                self._troncamenti += 1
                self._emit(
                    "troncato",
                    motivo=motivo_fine,
                    tentativo=self._troncamenti,
                    completion_tokens=getattr(resp, "completion_tokens", 0),
                )
                if self._troncamenti <= 2:
                    self._nota_sistema(
                        "LA TUA ULTIMA RISPOSTA E' STATA TRONCATA dal tetto "
                        "di token di output: il testo si interrompe a meta'.\n"
                        "Non ripetere quello che hai gia' scritto e non "
                        "ricominciare da capo. CONTINUA esattamente dal punto "
                        "in cui ti sei fermato, senza preamboli. Se stavi "
                        "ragionando e non hai ancora scritto la risposta, "
                        "chiudi il ragionamento e scrivi la risposta adesso, "
                        "in modo piu' breve.",
                        "__troncato__",
                    )
                    continue

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
                    self._nota_sistema(
                        f"STAI RIPETENDO la stessa chiamata `{nome_rip}` con gli "
                        f"stessi argomenti e torna sempre lo stesso errore. "
                        f"Smetti di riprovarla: è un vicolo cieco. Rispondi "
                        f"adesso con quello che sei riuscito a fare finora, e "
                        f"dì in una riga cosa non ha funzionato e perché. "
                        f"Un «non ce l'ho fatta su {nome_rip}» è una risposta "
                        f"utile; ritentare la stessa chiamata non lo è.",
                        "__sistema__",
                    )
                    self.state.stopped_because = "gira_a_vuoto"
                    return self.state

            # --- caso 1: il modello ha chiesto tool -> esegui e continua
            if resp.wants_tools:
                chiamate = list(resp.tool_calls)
                esiti, avviate = self._prepara_parallelo(chiamate)
                for i, tc in enumerate(chiamate):
                    # Il tempo si controlla come il cancel, e per lo
                    # stesso motivo: ogni tool_call deve avere il suo
                    # risultato, anche quelle mai partite.
                    if self._tempo_scaduto():
                        for pendente in chiamate[i:]:
                            self.state.messages.append(
                                Message(
                                    role="tool",
                                    content=("Tempo massimo del turno raggiunto "
                                             "prima dell'esecuzione."),
                                    tool_call_id=pendente.id,
                                    name=pendente.name,
                                )
                            )
                            self._emit(
                                "tool_end",
                                name=pendente.name,
                                result="tempo_scaduto",
                                ok=False,
                                id=pendente.id,
                                consecutive_errors=self.state.consecutive_errors,
                            )
                        self._nota_sistema(
                            f"[TEMPO MASSIMO DEL TURNO] Sono passati "
                            f"{int(self.config.max_secondi_turno)} secondi "
                            f"durante un'esecuzione: il turno si ferma qui "
                            f"e i comandi non ancora partiti NON sono stati "
                            f"eseguiti.",
                            "__sistema__",
                        )
                        self.state.stopped_because = "tempo_scaduto"
                        return self.state
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
                    if tc.id not in avviate:
                        self._emit("tool_start", name=tc.name, args=args,
                                   id=tc.id)

                    # Valori di partenza: il ramo degli argomenti rotti non
                    # esegue nessun tool, ma il messaggio e l'evento li
                    # leggono lo stesso. Senza, il turno cade con
                    # UnboundLocalError invece di riportare l'errore al
                    # modello — il difetto peggiore, perché nasconde la
                    # causa e sembra un guasto del programma.
                    immagini: list[str] = []
                    anteprime: list[str] = []

                    if tc.id in esiti:
                        # Gia' eseguito dal batch di sola lettura: qui si
                        # fa solo la contabilita', nello stesso ordine in
                        # cui il modello ha chiesto le chiamate.
                        result, ok, immagini, anteprime = esiti[tc.id]
                    elif tc.args_non_validi():
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
                        result, ok, immagini, anteprime = self._execute_tool(
                            tc.name, args)

                    # Redazione PRIMA che il risultato diventi un fatto:
                    # da qui va al modello, alla UI in streaming, allo
                    # storico su disco e alla traccia. `echo $API_KEY` e'
                    # un comando legittimo, e senza questo la chiave
                    # restava scritta nello storico per sempre.
                    if isinstance(result, str):
                        result = redazione.redigi(result)

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
                            images=immagini,
                        )
                    )
                    self._emit(
                        "tool_end",
                        name=tc.name,
                        result=result[:500],
                        ok=ok,
                        id=tc.id,
                        # Anteprime per la UI (immagini generate). Non
                        # vanno al modello: servono a chi guarda.
                        images=anteprime,
                        consecutive_errors=self.state.consecutive_errors,
                    )

                if self.state.consecutive_errors >= self.config.max_consecutive_errors:
                    self.state.stopped_because = "troppi_errori_consecutivi"
                    return self.state
                continue

            # Uno steer puo' arrivare MENTRE il modello sta generando
            # l'ultima risposta: la coda viene letta in cima al ciclo,
            # quindi fino a qui non e' mai stata guardata. Senza questo
            # controllo resterebbe in coda per il turno successivo —
            # cioe' verrebbe applicata alla domanda sbagliata. Si torna
            # in cima, dove viene iniettata, e il modello ripensa la
            # risposta appena abbozzata.
            if not resp.wants_tools and self.state.steer_queue:
                continue

            # --- caso 2: risposta testuale -> finito
            #
            # NUDGE ANTI-BOCCA-VUOTA: se il modello chiude il turno
            # annunciando che farà un lavoro ("analizzo il progetto...")
            # invece di farlo, si rimanda indietro con un messaggio
            # esplicito: se il lavoro richiede gli strumenti, deve
            # chiamarli. Il flag `_nudge_fatto` garantisce che sia UNA
            # volta — un loop che si auto-nudga all'infinito sprecherebbe
            # token senza aggiungere niente.
            #
            # L'annuncio si controlla SEMPRE, non solo nei turni senza
            # tool. Prima il controllo stava dentro `tool_calls_made == 0`:
            # un turno che aveva già fatto venti tool e poi chiudeva con
            # "ora faccio il resto" non veniva ripreso da nessuno, e il
            # lavoro restava a metà senza che niente lo dicesse. Il testo
            # del nudge cambia nei due casi, perché "non hai ancora usato
            # nessuno strumento" dopo venti tool sarebbe falso.
            #
            # Ma UN nudge non basta al narratore a puntate ("cerco...",
            # "ora aggiungo...", "ecco il piano..."): ogni giro sembra
            # quasi lavoro e nessuno lo e'. Dopo il nudge, un secondo
            # annuncio di fila chiude: "solo_parole" se non è stato fatto
            # niente, "annuncio_finale" se il turno ha comunque prodotto
            # lavoro. Sono due cose diverse, e chiamarle con lo stesso nome
            # sarebbe la bugia che questo blocco esiste per evitare.
            if self.state.tool_calls_made == 0:
                self._vuote_di_fila += 1
            annuncio = self._annuncia_senza_fare(resp.content)
            if annuncio and not self._nudge_fatto:
                self._nudge_fatto = True
                dopo_lavoro = self.state.tool_calls_made > 0
                self._nota_sistema(
                    _NUDGE_DOPO_LAVORO if dopo_lavoro else _NUDGE_SENZA_TOOL,
                    "__nudge__",
                )
                self._emit("nudge", testo=resp.content[:120],
                           dopo_lavoro=dopo_lavoro)
                continue
            if annuncio and self._nudge_fatto:
                # Secondo annuncio di fila dopo il nudge: non agira',
                # sta narrando. Chiudere come risposta_finale
                # mentirebbe ("completato" senza aver completato).
                if self.state.tool_calls_made == 0:
                    self._emit("solo_parole",
                               testo=resp.content[:120],
                               giri=self._vuote_di_fila)
                    self.state.stopped_because = "solo_parole"
                else:
                    self._emit("annuncio_finale",
                               testo=resp.content[:120],
                               tool=self.state.tool_calls_made)
                    self.state.stopped_because = "annuncio_finale"
                return self.state
            if self.state.tool_calls_made == 0 and self._vuote_di_fila >= 4:
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
                self._nota_sistema(
                    nota_per_modello(
                        esito, self._verifica_tentativo,
                        specifica.get("max_tentativi",
                                      self.config.max_tentativi_verifica)),
                    "__verifica__",
                )
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
        non magia.

        Il difetto che questa lista ha gia' pagato: un modello che chiude
        con "Faccio le modifiche vere ora. Prima indago il modal tracce."
        non veniva riconosciuto — "faccio" e "indago" non erano in elenco —
        quindi il nudge non partiva e l'annuncio passava per risposta
        finale. Osservato su Beam 1.0: sette turni di fila a una
        iterazione, zero tool, esito "risposta_finale". Per l'utente il
        sintomo era "risponde a caso", e il modello stava solo promettendo.

        Tre strade, dalla piu' forte alla piu' debole:
        1. verbo d'azione in testa, con l'ANCORAGGIO: cosi' "Punto 1: devo
           verificare" NON scatta — la' il verbo e' a meta' e c'e'
           contenuto;
        2. verbo d'azione + marcatore di tempo ("faccio ... adesso",
           "indago ... poi"): la promessa a meta' frase. Servono ENTRAMBI,
           o "faccio notare che il file non esiste" (risposta vera) verrebbe
           preso per un annuncio;
        3. forme di promessa che non hanno bisogno del tempo ("sto per",
           "provvedo", "mi metto").

        Il testo deve restare corto e piano: una risposta vera e' lunga o
        strutturata. E un verbo negato ("non faccio nulla ora") non e' una
        promessa. Resta il compromesso dichiarato: meglio un falso negativo
        (il modello parla a vuoto una volta) che un falso positivo
        (Orchestra interrompe una risposta vera perche' conteneva
        "analizzo") — ma i falsi negativi si sono visti costare un turno
        intero di lavoro mai fatto, quindi l'elenco e' largo.
        """
        if not testo:
            return False
        t = testo.strip()
        # Lunga o con struttura (elenchi, piu' righe): e' una risposta,
        # anche se contiene "analizzo".
        if len(t) > 220 or t.count("\n") >= 3:
            return False
        basso = t.lower()

        # 1. verbo d'azione in testa.
        testa = basso[:40]
        if any(a in testa for a in _ANNUNCI_IN_TESTA):
            return True

        # 2. promessa a meta' frase: verbo d'azione E marcatore di tempo.
        corpo = basso[:200]
        if _TEMPO.search(corpo):
            for m in _AZIONI.finditer(corpo):
                prima = corpo[max(0, m.start() - 6):m.start()]
                if prima.endswith("non "):
                    continue      # "non faccio nulla ora": non promette
                return True

        # 3. promesse esplicite, che il tempo non ce l'hanno.
        return any(p in corpo for p in _PROMESSE)

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
                        # Temperatura e tetto di output vengono dalla
                        # CONFIGURAZIONE dell'agente, non dalla entry.
                        # La entry aveva i suoi (4096/0.7) e li usava al
                        # posto della config: `ORCHESTRA_MAX_TOKENS` non
                        # aveva effetto su nessuna chiamata, e con
                        # `reasoning: max` i 4096 finivano dentro il
                        # ragionamento lasciando la risposta troncata.
                        # Due posti per lo stesso numero non sono un
                        # doppione innocuo: uno dei due vince in
                        # silenzio, e non e' quello che l'utente ha
                        # impostato.
                        if hasattr(provider, "chat_stream"):
                            return provider.chat_stream(
                                self.state.messages,
                                self.registry.api_payload(),
                                temperature=self.config.temperature,
                                max_tokens=self.config.max_tokens,
                                reasoning_level=self.config.reasoning_level,
                                on_event=self._on_stream,
                            )
                        return provider.chat(
                            self.state.messages,
                            self.registry.api_payload(),
                            temperature=self.config.temperature,
                            max_tokens=self.config.max_tokens,
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
