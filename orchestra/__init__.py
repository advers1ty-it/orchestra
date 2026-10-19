"""Orchestra — orchestratore agentico scritto da zero.

Fatto da zero di proposito: loop, tool, context e provider sono nostri.
Nessuna dipendenza esterna a runtime (solo stdlib), per cui l'unica cosa
che ci separa da un prodotto è il codice che c'è dentro.
"""

# Migrazione dal percorso dati vecchio (hermes) al nuovo (orchestra).
# Deve partire prima di tutto: se i file non sono al loro posto, il resto
# dell'app li cerca dove non sono e li ritrova vuoti.
try:
    from .dati import migra_da_vecchio
    _migrati = migra_da_vecchio()
except Exception:
    _migrati = []

from .types import (
    LLMResponse,
    Message,
    Tool,
    ToolCall,
    ToolRegistry,
)
from .providers import (
    KNOWN_PROVIDERS,
    OpenAICompatAdapter,
    ProviderError,
    build_provider,
    load_env,
)
from .context import (
    compact_history,
    compact_tools,
    count_tokens,
    fit_context,
)
from .agent import Agent, AgentState, LoopConfig
from .tools import SYSTEM_PROMPT, default_registry

__version__ = "0.5.14"

__all__ = [
    "LLMResponse", "Message", "Tool", "ToolCall", "ToolRegistry",
    "OpenAICompatAdapter", "ProviderError", "build_provider", "load_env",
    "KNOWN_PROVIDERS", "compact_history", "compact_tools", "count_tokens",
    "fit_context", "Agent", "AgentState", "LoopConfig",
    "SYSTEM_PROMPT", "default_registry", "__version__",
]
