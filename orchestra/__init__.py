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

# Pulizia automatica: se esiste sia il vecchio orchestra/tools.py (file)
# che la nuova orchestra/tools/ (cartella package), Python sceglie il file
# e ignora la cartella, rompendo gli import da orchestra.tools.memoria etc.
# Rimuove il file obsoleto se la cartella package esiste già.
import os as _os
_tools_dir = _os.path.join(_os.path.dirname(__file__), "tools")
_tools_file = _tools_dir + ".py"
if _os.path.isdir(_tools_dir) and _os.path.isfile(_tools_file):
    try:
        _os.remove(_tools_file)
    except Exception:
        pass

# Se la cartella orchestra/tools/ esiste ma manca __init__.py (es. aggiornamento
# parziale da GitHub), la crea vuota così Python la riconosce come package.
_tools_init = _os.path.join(_tools_dir, "__init__.py")
if _os.path.isdir(_tools_dir) and not _os.path.isfile(_tools_init):
    try:
        open(_tools_init, "w", encoding="utf-8").close()
    except Exception:
        pass

from .tools import SYSTEM_PROMPT, default_registry

__version__ = "0.5.56"

__all__ = [
    "LLMResponse", "Message", "Tool", "ToolCall", "ToolRegistry",
    "OpenAICompatAdapter", "ProviderError", "build_provider", "load_env",
    "KNOWN_PROVIDERS", "compact_history", "compact_tools", "count_tokens",
    "fit_context", "Agent", "AgentState", "LoopConfig",
    "SYSTEM_PROMPT", "default_registry", "__version__",
]
