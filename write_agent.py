# This script writes the complete agent.py file
new_content = '''"""Il loop agentico.

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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .context import Summarizer, count_tokens, fit_context
from .providers import ProviderError
from .fallback import (
    ChainEntry, FallbackState, FallbackReason,
    get_chain_for_provider, should_fallback
)
from .budget import budget_guard, BudgetLimits
from .types import LLMResponse, Message, ToolRegistry

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")


@dataclass
class LoopConfig:
    max_iterations: int = 12
    context_limit: int = 120_000
    keep_recent: int = 8
    temperature: float = 0.7
    max_tokens: int = 4096
    tool_timeout_chars: int = 20_000
    max_consecutive_errors: int = 3
    reasoning_level: str | None = None
    budget_limits: BudgetLimits | None = None


@dataclass
class AgentState:
    messages: list[Message] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    tool_calls_made: int = 0
    tool_errors: int = 0
    tool_error_names: list[str] = field(default_factory=list)
    consecutive_errors: int = 0
    compactions: int = 0
    stopped_because: str = ""
    usage_by_model: dict[str, int] = field(default_factory=dict)


class Agent:
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
        self.provider = provider
        self.registry = registry
        self.system_prompt = system_prompt
        self.config = config or LoopConfig()
        self.summarize = summarize
        self.on_event = on_event or (lambda kind, data: None)
        self.state = AgentState(messages=[Message(role="system", content=system_prompt)])
        if fallback_chain is None and hasattr(provider, 'name'):
            provider_name = provider.name
            model = getattr(provider, 'model', '')
            self.fallback_chain = get_chain_for_provider(provider_name, model)
            if self.fallback_chain:
                self.fallback_chain[0] = ChainEntry(
                    provider=provider_name,
                    model=model,
                    name=f"{provider_name}/{model}",
                )
        else:
            self.fallback_chain = fallback_chain or []
        self._fallback_state: FallbackState | None = None
        self._budget_state = None
        if self.config.budget_limits:
            session_id = f"{provider.name}_{getattr(provider, 'model', 'unknown')}_{int(datetime.now().timestamp())}"
            self._budget_state = budget_guard().get_or_create_session(session_id, self.config.budget_limits)

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
            attesi = ""
            try:
                import inspect
                attesi = ", ".join(
                    str(p) for p in inspect.signature(tool.handler).parameters
                    if p not in ("self",))
            except (TypeError, ValueError):
                pass
            dettaglio = f" Accetta: {attesi}." if attesi else ""
            return (f"ERRORE DI ARGOMENTI per '{name}': {e}." f"{dettaglio}"), False
        except Exception as e:
            self._emit("tool_error", tool=name, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc(limit=3))
            return f"ERRORE durante l'esecuzione di '{name}': {type(e).__name__}: {e}", False

        if len(text) > self.config.tool_timeout_chars:
            text = text[: self.config.tool_timeout_chars] + f"\\n\\n[TRONCATO: {len(text)} caratteri totali, mostro i primi {self.config.tool_timeout_chars}]"
        return text, True

    def _aggiorna_prompt(self) -> None:
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
            return
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
        if self._budget_state:
            self._budget_state.reset_task()

        testo = user_input
        immagini: list[str] = []
        for a in (allegati or []):
            if getattr(a, "testo", ""):
                testo += ("\\n\\n" if testo else "") + f"[{a.nome}]\\n{a.testo}"
            immagini.extend(getattr(a, "immagini", []) or [])

        msg = Message(role="user", content=testo, images=immagini)
        self.state.messages.append(msg)
        self._emit("user_message", text=user_input, allegati=[a.nome for a in (allegati or [])])

        self._aggiorna_prompt()

        for self.state.iterations in range(1, self.config.max_iterations + 1):
            if self._budget_state:
                self._budget_state.reset_task()

            if should_continue and not should_continue(self.state):
                self.state.stopped_because = "canceled_da_should_continue"
                return self.state

            self._maybe_compact()

            self._emit("thinking", iteration=self.state.iterations)
            resp = self._call_model_with_retry()
            self.state.total_tokens += resp.total_tokens
            self.state.usage_by_model[resp.model] = self.state.usage_by_model.get(resp.model, 0) + resp.total_tokens

            self.state.messages.append(Message(role="assistant", content=resp.content, tool_calls=resp.tool_calls, tokens=resp.total_tokens))
            self._emit("assistant", iteration=self.state.iterations, content=resp.content, tool_calls=[{"id": tc.id, "name": tc.name, "args": tc.parsed_args()} for tc in resp.tool_calls], tokens=resp.total_tokens)

            if self._budget_state and resp.total_tokens > 0:
                prompt_tokens = getattr(resp, 'prompt_tokens', 0)
                completion_tokens = getattr(resp, 'completion_tokens', 0)
                if prompt_tokens == 0 and completion_tokens == 0:
                    prompt_tokens = resp.total_tokens // 2
                    completion_tokens = resp.total_tokens - prompt_tokens
                cost_usd = (prompt_tokens + completion_tokens) / 1000 * 0.001
                self._budget_state.add_usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost_usd=cost_usd, model=resp.model, category="")
                violations = self._budget_state.check_limits()
                if violations:
                    self._emit("budget_violation", violations=violations)
                    self.state.stopped_because = "budget_exceeded"
                    return self.state

            if resp.wants_tools:
                for tc in resp.tool_calls:
                    args = tc.parsed_args()
                    self.state.tool_calls_made += 1
                    self._emit("tool_start", name=tc.name, args=args, id=tc.id)
                    result, ok = self._execute_tool(tc.name, args)
                    if ok:
                        self.state.consecutive_errors = 0
                    else:
                        self.state.tool_errors += 1
                        self.state.tool_error_names.append(tc.name)
                        self.state.consecutive_errors += 1
                    self.state.messages.append(Message(role="tool", content=result, tool_call_id=tc.id, name=tc.name))
                    self._emit("tool_end", name=tc.name, result=result[:500], ok=ok, id=tc.id, consecutive_errors=self.state.consecutive_errors)
                if self.state.consecutive_errors >= self.config.max_consecutive_errors:
                    self.state.stopped_because = "troppi_errori_consecutivi"
                    return self.state
                continue

            self.state.stopped_because = "risposta_finale"
            return self.state

        self.state.stopped_because = "max_iterations"
        return self.state

    def _call_model_with_retry(self) -> LLMResponse:
        if self._fallback_state is None:
            self._fallback_state = FallbackState(entries=self.fallback_chain)
        fs = self._fallback_state
        last_error: Exception | None = None

        while fs.current:
            entry = fs.current
            self._emit("fallback_attempt", provider=entry.provider, model=entry.model, attempt=fs.attempts_on_current + 1, index=fs.current_index)
            if fs.current_index == 0:
                provider = self.provider
            else:
                from .providers import build_provider, ambiente
                env = ambiente(ENV_PATH)
                try:
                    provider = build_provider(entry.provider, model=entry.model, env=env)
                    provider.timeout = entry.timeout
                except Exception as e:
                    self._emit("fallback_provider_error", provider=entry.provider, error=str(e))
                    if not fs.advance(FallbackReason.UNAVAILABLE, str(e)):
                        break
                    continue

            for attempt in range(entry.max_retries + 1):
                try:
                    return provider.chat(self.state.messages, self.registry.api_payload(), temperature=entry.temperature, max_tokens=entry.max_tokens, reasoning_level=self.config.reasoning_level)
                except ProviderError as e:
                    last_error = e
                    reason = should_fallback(e)
                    if reason is None or not e.retryable:
                        self._emit("fallback_triggered", provider=entry.provider, reason=reason.value if reason else "non_retryable", error=str(e))
                        break
                    if attempt == entry.max_retries:
                        reason = FallbackReason.MAX_RETRIES
                        self._emit("fallback_triggered", provider=entry.provider, reason=reason.value, error=str(e))
                        break
                    import time
                    attesa = min(max(getattr(e, "retry_after", 0.0), 2.0 ** attempt * 0.5), 120.0)
                    self._emit("retry", provider=entry.provider, attempt=attempt + 1, error=str(e), attesa=attesa)
                    time.sleep(attesa)
                except Exception as e:
                    last_error = e
                    reason = FallbackReason.NETWORK_ERROR
                    if attempt == entry.max_retries:
                        self._emit("fallback_triggered", provider=entry.provider, reason=reason.value, error=str(e))
                        break
                    import time
                    attesa = min(2.0 ** attempt * 0.5, 30.0)
                    self._emit("retry", provider=entry.provider, attempt=attempt + 1, error=str(e), attesa=attesa)
                    time.sleep(attesa)

            fs.attempts_on_current += 1
            if not fs.advance(reason or FallbackReason.MAX_RETRIES, str(last_error)):
                break

        self._emit("fallback_exhausted", history=fs.history)
        if last_error:
            raise last_error
        raise RuntimeError("Nessun provider disponibile nella fallback chain")

    def final_text(self) -> str:
        for m in reversed(self.state.messages):
            if m.role == "assistant" and m.content.strip():
                return m.content.strip()
        return ""

    def transcript(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.state.messages]
'''