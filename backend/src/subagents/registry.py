"""Subagent registry for managing available subagents."""

import logging
from dataclasses import replace

from src.subagents.builtins import BUILTIN_SUBAGENTS
from src.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


def get_subagent_config(name: str) -> SubagentConfig | None:
    """Get a subagent configuration by name, with config.yaml overrides applied.

    Args:
        name: The name of the subagent.

    Returns:
        SubagentConfig if found (with any config.yaml overrides applied), None otherwise.
    """
    config = BUILTIN_SUBAGENTS.get(name)
    if config is None:
        return None

    # Apply timeout override from config.yaml (lazy import to avoid circular deps)
    from src.config.subagents_config import get_subagents_app_config

    app_config = get_subagents_app_config()
    effective_timeout = app_config.get_timeout_for(name)
    effective_model = app_config.get_model_for(name)
    effective_thinking_enabled = app_config.get_thinking_enabled_for(name)

    replacements = {}
    if effective_timeout != config.timeout_seconds:
        logger.debug(f"Subagent '{name}': timeout overridden by config.yaml ({config.timeout_seconds}s -> {effective_timeout}s)")
        replacements["timeout_seconds"] = effective_timeout
    if effective_model is not None and effective_model != config.model:
        logger.debug(f"Subagent '{name}': model overridden by config.yaml ({config.model} -> {effective_model})")
        replacements["model"] = effective_model
    if effective_thinking_enabled is not None and effective_thinking_enabled != config.thinking_enabled:
        logger.debug(
            "Subagent '%s': thinking overridden by config.yaml (%s -> %s)",
            name,
            config.thinking_enabled,
            effective_thinking_enabled,
        )
        replacements["thinking_enabled"] = effective_thinking_enabled

    if replacements:
        config = replace(config, **replacements)

    return config


def list_subagents() -> list[SubagentConfig]:
    """List all available subagent configurations (with config.yaml overrides applied).

    Returns:
        List of all registered SubagentConfig instances.
    """
    return [get_subagent_config(name) for name in BUILTIN_SUBAGENTS]


def get_subagent_names() -> list[str]:
    """Get all available subagent names.

    Returns:
        List of subagent names.
    """
    return list(BUILTIN_SUBAGENTS.keys())
