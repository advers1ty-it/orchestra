"""
Reasoning effort configuration and payload building for Orchestra.

Maps unified reasoning levels to provider-specific API parameters.
If a provider/model doesn't support reasoning, returns empty payload (no 400).
"""

REASONING_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]

# Provider-specific reasoning configuration
PROVIDER_REASONING = {
    "openrouter": {
        "param": "reasoning",
        "format": "object",           # {"effort": "high"}
        "levels": ["minimal", "low", "medium", "high", "xhigh", "max"],
        "default": "medium",
    },
    "groq": {
        "param": "reasoning_effort",
        "format": "string",           # "high"
        "levels": ["low", "medium", "high"],          # GPT-OSS models
        "levels_qwen": ["none", "default", "low", "medium", "high"],  # Qwen 3.8
        "default": "medium",
        "model_overrides": {
            "qwen/qwen3.8-27b": ["none", "default", "low", "medium", "high"],
        },
    },
    "nvidia": {
        "param": "reasoning_effort",
        "format": "string",
        "levels": ["low", "medium", "high"],
        "default": "medium",
        "model_allowlist": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        "requires_nim_config": True,  # documentation flag
    },
}

# Task category → default reasoning level
TASK_CATEGORY_DEFAULTS = {
    "extraction": "low",
    "code": "high",
    "debugging": "high",
    "reasoning": "high",
    "instruction": "medium",
    "tool": "medium",
    "web": "medium",
    "app": "medium",
    "write": "medium",
}


def get_model_levels(provider: str, model_id: str) -> list[str]:
    """Get supported reasoning levels for a specific model on a provider."""
    cfg = PROVIDER_REASONING.get(provider)
    if not cfg:
        return []

    # NVIDIA: only specific models
    allowed = cfg.get("model_allowlist")
    if allowed and model_id not in allowed:
        return []

    # Groq: model-specific overrides
    if provider == "groq":
        return cfg.get("model_overrides", {}).get(model_id, cfg["levels"])

    return cfg["levels"]


def resolve_reasoning_level(
    provider: str,
    model_id: str,
    user_level: str | None,
    task_category: str | None = None,
) -> str | None:
    """
    Resolve the effective reasoning level.

    Priority:
    1. Explicit user level (from UI/command)
    2. Model-specific default (from catalog, future)
    3. Task category default
    4. Provider default
    5. None (no reasoning)
    """
    if user_level and user_level != "none":
        return user_level

    # Model-specific default would come from catalog here (future)

    if task_category and task_category in TASK_CATEGORY_DEFAULTS:
        return TASK_CATEGORY_DEFAULTS[task_category]

    cfg = PROVIDER_REASONING.get(provider)
    if cfg:
        return cfg["default"]

    return None


def build_reasoning_payload(
    provider: str,
    model_id: str,
    level: str | None,
) -> dict:
    """
    Build the reasoning payload fragment for the given provider/model/level.

    Returns empty dict if:
    - level is None or "none"
    - provider not configured
    - model not supported for reasoning on this provider
    - level not in model's supported levels (falls back to highest supported)
    """
    if not level or level == "none":
        return {}

    cfg = PROVIDER_REASONING.get(provider)
    if not cfg:
        return {}

    supported = get_model_levels(provider, model_id)
    if not supported:
        return {}

    # Clamp to supported levels
    if level not in supported:
        level = supported[-1]  # highest supported

    if cfg["format"] == "object":
        return {cfg["param"]: {"effort": level}}
    else:
        return {cfg["param"]: level}


def get_provider_reasoning_info(provider: str) -> dict | None:
    """Get full reasoning config for a provider (for UI/catalog)."""
    return PROVIDER_REASONING.get(provider)