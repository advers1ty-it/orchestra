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
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from .context import Summarizer, count_tokens, fit_context
from .providers import ProviderError
from .types import LLMResponse, Message, ToolRegistry


@dataclass
class LoopConfig:
    """Parametri del loop. I default sono scelti, non arbitrari."""

    max_iterations: int = 12
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
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.system_prompt = system_prompt
        self.config = config or LoopConfig()
        self.summarize = summarize
        self.on_event = on_event or (lambda kind, data: None)
        self.state = AgentState(messages=[Message(role="system", content=system_prompt)])

    # -- utility interne ---------------------------------------------------

    def _emit(self, kind: str, **data: Any) -> None:
        self.on_event(kind, data)

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
            result = tool.handler(**args)
            if hasattr(result, "__await__"):
                import asyncio

                result = asyncio.run(result)
            text = result if isinstance(result, str) else json.dumps(result, default=str)
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

    def _aggiorna_prompt(self) -> None:
        """Riscrive il messaggio di sistema con le skill di adesso.

        Ma solo se ce ne sono. Senza skill il prompt resta identico,
        carattere per carattere: un test che verifica "il system
        prompt non e' mai perso" confronta l'uguaglianza esatta, e
        aggiungere anche solo una riga vuota lo faceva fallire — e il
        sintomo sarebbe stato "la compaction perde il prompt", che e'
        falso. In quel caso si faceva cercare un bug nella
        compattazione, che era perfettamente funzionante.

        Fallisce in silenzio e lascia il prompt come era: un errore
        qui non deve fermare il turno.
        """
        try:
            import orchestra.skills as sk
            ultimo = ""
            for m in reversed(self.state.messages):
                if m.role == "user" and m.content:
                    ultimo = m.content
                    break
            extra = sk.Indice().prompt(ultimo[:2000])
        except Exception:
            return
        if not extra:
            return                      # nessuna skill: prompt identico
        nuovo = self.system_prompt + extra
        for m in self.state.messages:
            if m.role == "system":
                m.content = nuovo
                return
        self.state.messages.insert(0, Message(role="system", content=nuovo))

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

        for self.state.iterations in range(1, self.config.max_iterations + 1):
            if should_continue and not should_continue(self.state):
                self.state.stopped_because = "canceled_da_should_continue"
                return self.state

            self._maybe_compact()

            # --- chiamata al modello, con retry su errori transitori
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

            # --- caso 1: il modello ha chiesto tool -> esegui e continua
            if resp.wants_tools:
                for tc in resp.tool_calls:
                    args = tc.parsed_args()
                    self.state.tool_calls_made += 1
                    # `id` va nei due eventi: e' il modo perche' la UI
                    # abbini il risultato al tool giusto quando in un turno
                    # ce n'e' piu' di uno con lo stesso nome.
                    self._emit("tool_start", name=tc.name, args=args, id=tc.id)

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
            self.state.stopped_because = "risposta_finale"
            return self.state

        self.state.stopped_because = "max_iterations"
        return self.state

    def _call_model_with_retry(self) -> LLMResponse:
        """Retry sui soli errori transitori (429/5xx/rete).

        Non ritentiamo sui 4xx di autenticazione: quelli non passano col tempo,
        e insistere su una chiave invalida è solo rumore nei log.

        4 tentativi con backoff esponenziale: i gateway pubblici come
        OpenRouter restituiscono 502 «provider unavailable» anche per decine
        di secondi, e con 2 tentativi finiamo spesso per fallire un compito
        che sarebbe andato a buon fine. Ogni tentativo costa un round-trip,
        che è molto meno di una risposta persa.
        """
        last: ProviderError | None = None
        for attempt in range(4):
            try:
                return self.provider.chat(
                    self.state.messages,
                    self.registry.api_payload(),
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
            except ProviderError as e:
                last = e
                if not e.retryable or attempt == 3:
                    raise
                self._emit("retry", attempt=attempt + 1, error=str(e))
                import time

                # backoff esponenziale con tetto: 0.5, 1, 2 secondi
                time.sleep(min(2 ** attempt * 0.5, 4.0))
        assert last is not None
        raise last

    # -- output ------------------------------------------------------------

    def final_text(self) -> str:
        for m in reversed(self.state.messages):
            if m.role == "assistant" and m.content.strip():
                return m.content.strip()
        return ""

    def transcript(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.state.messages]
