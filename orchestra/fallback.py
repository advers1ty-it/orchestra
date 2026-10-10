"""
Fallback chain system for Orchestra.

When a provider fails, automatically try the next one in the chain.
Each chain entry has: provider, model, max_retries, timeout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class FallbackReason(Enum):
    """Why we fell back to the next provider."""
    RATE_LIMITED = "rate_limited"           # 429
    SERVER_ERROR = "server_error"           # 5xx
    NETWORK_ERROR = "network_error"         # connection failed
    UNAVAILABLE = "unavailable"             # model not found / 404
    AUTH_ERROR = "auth_error"               # 401/403 - don't retry, fall back
    MAX_RETRIES = "max_retries"             # retries exhausted
    UNUSABLE = "unusable"                   # provider marked unusable (e.g., harness-locked)


@dataclass
class ChainEntry:
    """One step in the fallback chain."""
    provider: str
    model: str
    name: str = ""                    # display name
    max_retries: int = 3              # retries on this provider before falling back
    timeout: int = 120                # seconds
    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_level: str | None = None
    # Only try this entry if the request matches these categories
    # Empty = matches all categories
    categories: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.name:
            self.name = f"{self.provider}/{self.model}"


@dataclass
class FallbackState:
    """Tracks fallback state during a request."""
    entries: list[ChainEntry] = field(default_factory=list)
    current_index: int = 0
    attempts_on_current: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)  # {entry, reason, error}

    @property
    def current(self) -> ChainEntry | None:
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None

    @property
    def has_next(self) -> bool:
        return self.current_index + 1 < len(self.entries)

    def advance(self, reason: FallbackReason, error: str) -> bool:
        """Move to next entry. Returns True if there's a next entry."""
        if self.current:
            self.history.append({
                "provider": self.current.provider,
                "model": self.current.model,
                "reason": reason.value,
                "error": error,
                "attempts": self.attempts_on_current,
            })
        self.current_index += 1
        self.attempts_on_current = 0
        return self.current is not None


# Default fallback chains per primary provider
# Ordered: primary first, then fallbacks
DEFAULT_CHAINS: dict[str, list[ChainEntry]] = {
    "openrouter": [
        ChainEntry("openrouter", "", name="OpenRouter (auto)"),  # model will be filled by routing
        ChainEntry("groq", "openai/gpt-oss-120b", name="Groq GPT-OSS"),
        ChainEntry("nvidia", "nvidia/llama-3.1-nemotron-70b-instruct", name="NVIDIA Nemotron 70B"),
        ChainEntry("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", name="Together Llama"),
        ChainEntry("cerebras", "llama3.1-70b", name="Cerebras Llama"),
    ],
    "groq": [
        ChainEntry("groq", "", name="Groq (auto)"),
        ChainEntry("openrouter", "openai/gpt-oss-120b", name="OpenRouter GPT-OSS"),
        ChainEntry("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", name="Together Llama"),
    ],
    "nvidia": [
        ChainEntry("nvidia", "", name="NVIDIA (auto)"),
        ChainEntry("groq", "openai/gpt-oss-120b", name="Groq GPT-OSS"),
        ChainEntry("openrouter", "openai/gpt-oss-120b", name="OpenRouter GPT-OSS"),
    ],
    "together": [
        ChainEntry("together", "", name="Together (auto)"),
        ChainEntry("groq", "openai/gpt-oss-120b", name="Groq GPT-OSS"),
        ChainEntry("openrouter", "openai/gpt-oss-120b", name="OpenRouter GPT-OSS"),
    ],
    # Local providers don't fall back (they're the last resort)
    "ollama": [ChainEntry("ollama", "", name="Ollama (local)")],
    "lmstudio": [ChainEntry("lmstudio", "", name="LM Studio (local)")],
}


def should_fallback(error: Exception) -> FallbackReason | None:
    """Determine if an error should trigger fallback, and why."""
    from .providers import ProviderError
    
    if isinstance(error, ProviderError):
        if error.unusable:
            return FallbackReason.UNUSABLE
        if error.status == 429:
            return FallbackReason.RATE_LIMITED
        if error.status in (401, 403):
            return FallbackReason.AUTH_ERROR
        if error.status == 404:
            return FallbackReason.UNAVAILABLE
        if error.status == 400:
            # Model not found, invalid request - try next provider
            detail = str(error).lower()
            # Check for model-related errors (handles hyphens, spaces)
            if "model" in detail and (
                "not found" in detail or 
                "invalid" in detail or 
                "does not exist" in detail or
                "does-not-exist" in detail or
                "not a valid" in detail or
                "unknown" in detail
            ):
                return FallbackReason.UNAVAILABLE
        if error.status >= 500:
            return FallbackReason.SERVER_ERROR
        if error.retryable:
            return FallbackReason.SERVER_ERROR  # network/timeout
    return None


def get_chain_for_provider(primary: str, model: str = "", category: str = "") -> list[ChainEntry]:
    """Get the fallback chain for a primary provider, with model filled in."""
    base = DEFAULT_CHAINS.get(primary, [ChainEntry(primary, model or "")])
    chain = []
    for entry in base:
        # Create a copy with the actual model if provided
        e = ChainEntry(
            provider=entry.provider,
            model=model if entry.provider == primary and entry.model == "" else entry.model,
            name=entry.name,
            max_retries=entry.max_retries,
            timeout=entry.timeout,
            temperature=entry.temperature,
            max_tokens=entry.max_tokens,
            reasoning_level=entry.reasoning_level,
            categories=entry.categories.copy(),
        )
        # Filter by category if specified
        if e.categories and category and category not in e.categories:
            continue
        chain.append(e)
    return chain