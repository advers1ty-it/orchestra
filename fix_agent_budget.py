with open('orchestra/agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add imports
old_imports = """from __future__ import annotations

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
from .types import LLMResponse, Message, Tool Registry"""

new_imports = """from __future__ import annotations

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
from .types import LLMResponse, Message, ToolRegistry"""

content = content.replace(old_imports, new_imports)

# 2. Add budget_limits to LoopConfig
old_config = """    # reasoning effort: none | minimal | low | medium | high | xhigh | max
    # None = usa default per provider/category
    reasoning_level: str | None = None


@dataclass"""

new_config = """    # reasoning effort: none | minimal | low | medium | high | xhigh | max
    # None = usa default per provider/category
    reasoning_level: str | None = None
    # Budget limits per questa run (None = usa default)
    budget_limits: BudgetLimits | None = None


@dataclass"""

content = content.replace(old_config, new_config)

# 3. Add budget state init in __init__
old_init = """            self._fallback_state: FallbackState | None = None

    # -- utility interne ---------------------------------------------------"""

new_init = """            self._fallback_state: FallbackState | None = None
        # Budget guard
        self._budget_state = None
        if self.config.budget_limits:
            # Use a session ID based on provider+model+timestamp
            session_id = f"{provider.name}_{getattr(provider, 'model', 'unknown')}_{int(datetime.now().timestamp())}"
            self._budget_state = budget_guard().get_or_create_session(session_id, self.config.budget_limits)

    # -- utility interne ---------------------------------------------------"""

content = content.replace(old_init, new_init)

with open('orchestra/agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done imports and init')