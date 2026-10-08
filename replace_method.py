with open('orchestra/agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Replace lines 358-396 (1-indexed) = indices 357-395
new_method = '''    def _call_model_with_retry(self) -> LLMResponse:
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
        raise RuntimeError("Nessun provider disponibile nella fallback chain")
'''

# Replace lines 358-396 (1-indexed) = indices 357-395
lines[357:396] = [new_method + '\n']

with open('orchestra/agent.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Done')