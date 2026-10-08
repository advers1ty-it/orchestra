# Read the original agent.py
with open('orchestra/agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add imports at the top
old_imports = """from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from .context import Summarizer, count_tokens, fit_context
from .providers import ProviderError
from .types import LLMResponse, Message, ToolRegistry"""

new_imports = """from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from .context import Summarizer, count_tokens, fit_context
from .providers import ProviderError
from .fallback import (
    ChainEntry, FallbackState, FallbackReason,
    get_chain_for_provider, should_fallback
)
from .types import LLMResponse, Message, ToolRegistry

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")"""

content = content.replace(old_imports, new_imports)

# 2. Update __init__ to support fallback_chain
old_init = """    def __init__(
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
        self.state = AgentState(messages=[Message(role="system", content=system_prompt)])"""

new_init = """    def __init__(
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
        self._fallback_state: FallbackState | None = None"""

content = content.replace(old_init, new_init)

# 3. Replace _call_model_with_retry
old_call = """    def _call_model_with_retry(self) -> LLMResponse:
        \"\"\"Retry sui soli errori transitori (429/5xx/rete).

        Non ritentiamo sui 4xx di autenticazione: quelli non passano col tempo,
        e insistere su una chiave invalida è solo rumore nei log.

        4 tentativi con backoff esponenziale: i gateway pubblici come
        OpenRouter restituiscono 502 \u00abprovider unavailable\u00bb anche per decine
        di secondi, e con 2 tentativi finiamo spesso per fallire un compito
        che sarebbe andato a buon fine. Ogni tentativo costa un round-trip,
        che è molto meno di una risposta persa.
        \"\"\"
        last: ProviderError | None = None
        for attempt in range(4):
            try:
                return self.provider.chat(
                    self.state.messages,
                    self.registry.api_payload(),
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    reasoning_level=self.config.reasoning_level,
                )
            except ProviderError as e:
                last = e
                if not e.retryable or attempt == 3:
                    raise
                import time

                # quanto aspettare: prima si chiede al server, e il
                # backoff e' il minimo quando non risponde. Su un 429
                # il provider scrive quanto aspettare; noi lo
                # ignoravamo e ripartivamo dentro la sua finestra.
                attesa = min(max(getattr(e, "retry_after", 0.0),
                                 2.0 ** attempt * 0.5), 120.0)
                self._emit("retry", attempt=attempt + 1,
                           error=str(e), attesa=attesa)
                time.sleep(attesa)
        assert last is not None
        raise last"""

new_call = """    def _call_model_with_retry(self) -> LLMResponse:
        \"\"\"Retry sui soli errori transitori (429/5xx/rete) con fallback chain.

        Se il provider corrente fallisce in modo non recuperabile,
        passa al prossimo nella catena di fallback.
        \"\"\"
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
        raise RuntimeError("Nessun provider disponibile nella fallback chain")"""

content = content.replace(old_call, new_call)

with open('orchestra/agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')