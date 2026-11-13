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
    # Qui c'erano `temperature`, `max_tokens` e `reasoning_level` della
    # entry, e il loop le usava al posto di `LoopConfig`: ORCHESTRA_MAX_TOKENS
    # non aveva effetto su nessuna chiamata. La configurazione
    # dell'agente e' l'unica fonte; una entry non porta parametri suoi.
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


# Qui c'era `DEFAULT_CHAINS`: una tabella di catene per provider con
# ripieghi su servizi altrui (Groq, Together, Cerebras). Nomina servizi
# che chi usa Orchestra puo' non avere, non conosce `nous`, e faceva
# partire tentativi su provider senza chiave. Il fallback e' manuale:
# vedi `catena_manuale` in fondo al file.


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


# ---------------------------------------------------------------------------
# Fallback MANUALE
#
# La catena la decide l'utente: il modello in uso piu' i ripieghi che ha
# scelto (al massimo tre), e nient'altro. Veniva da una tabella scritta a
# mano, che nominava servizi che chi usa Orchestra puo' non avere
# (Together, Cerebras) e non conosceva quelli che ha davvero (nous,
# google). Misurato, non ipotizzato:
#
# - con `nous` come primario la catena restava di UN elemento — nessun
#   ripiego, mai; l'errore del modello arrivava dritto all'utente;
# - con OpenRouter come primario i tentativi si spendevano su Groq,
#   Together e Cerebras, che senza chiave falliscono al `build_provider`,
#   e il turno finiva con "Nessun provider disponibile" invece che con
#   l'errore vero.
#
# Da qui in giu' la catena la decide l'utente e contiene solo cose che ha.
MAX_RIPIEGHI = 3


def ripieghi_da_stringa(valore: str) -> list[tuple[str, str]]:
    """`provider/modello,provider/modello` -> [(provider, modello), ...]

    Si divide sul PRIMO `/`: gli id veri ne contengono altri
    (`openrouter/openai/gpt-oss-120b`), e dividere su tutti trasformerebbe
    meta' degli id in nomi di provider.
    """
    out: list[tuple[str, str]] = []
    for pezzo in (valore or "").split(","):
        pezzo = pezzo.strip()
        if not pezzo or "/" not in pezzo:
            continue
        provider, modello = pezzo.split("/", 1)
        provider, modello = provider.strip(), modello.strip()
        if provider and modello:
            out.append((provider, modello))
    return out[:MAX_RIPIEGHI]


def stringa_da_ripieghi(ripieghi) -> str:
    """Il formato del `.env`: una riga, virgole, nessun a capo."""
    return ",".join(f"{p}/{m}" for p, m in list(ripieghi)[:MAX_RIPIEGHI])


def config_da_env(env) -> tuple[bool, list[tuple[str, str]]]:
    """Stato del fallback come sta scritto nel `.env`."""
    grezzo = str(env.get("ORCHESTRA_FALLBACK", "") or "").strip().lower()
    return (grezzo in ("1", "on", "true", "si", "sì", "yes"),
            ripieghi_da_stringa(env.get("ORCHESTRA_FALLBACK_MODELS", "")))


def catena_manuale(provider: str, model: str, ripieghi,
                   *, attivo: bool) -> list[ChainEntry]:
    """Il modello in uso, piu' i ripieghi scelti a mano (max 3).

    Con `attivo` spento la catena e' il SOLO primario: nessun provider
    viene provato al posto suo, cosi' l'errore che arriva e' quello vero
    del modello scelto. Un fallback che parte da solo su servizi non
    configurati non e' un ripiego: e' un secondo guasto che nasconde il
    primo.
    """
    catena = [ChainEntry(provider, model)]
    if attivo:
        catena.extend(ChainEntry(p, m) for p, m in list(ripieghi)[:MAX_RIPIEGHI])
    return catena


def catena_per_agente(agente, env) -> list[ChainEntry]:
    """La catena manuale di un agente gia' costruito.

    Un solo posto che legge la configurazione e un solo posto che la
    trasforma in catena: CLI, web e goal la chiamano tutti qui. Il
    provider dell'agente e' l'unica verita' su servizio e modello (il
    percorso di cambio modello lo assegna prima di ricostruire la
    catena), quindi non si passa un nome che potrebbe essere vecchio.
    """
    attivo, ripieghi = config_da_env(env)
    prov = getattr(agente, "provider", None)
    return catena_manuale(getattr(prov, "name", "") or "",
                          getattr(prov, "model", "") or "",
                          ripieghi, attivo=attivo)