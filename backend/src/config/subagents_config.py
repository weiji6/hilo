"""Configuration for the subagent system loaded from config.yaml."""

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SubagentOverrideConfig(BaseModel):
    """Per-agent configuration overrides."""

    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Timeout in seconds for this subagent (None = use global default)",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name for this subagent (None = use global default or builtin behavior)",
    )
    thinking_enabled: bool | None = Field(
        default=None,
        description="Whether to enable thinking for this subagent (None = use global default or builtin behavior)",
    )


class SubagentsAppConfig(BaseModel):
    """Configuration for the subagent system."""

    timeout_seconds: int = Field(
        default=3600,
        ge=1,
        description="Default timeout in seconds for all subagents (default: 3600 = 1 hour)",
    )
    model_name: str | None = Field(
        default=None,
        description="Default model name for all subagents (None = preserve builtin subagent model behavior)",
    )
    thinking_enabled: bool | None = Field(
        default=None,
        description="Default thinking mode for all subagents (None = preserve builtin subagent behavior)",
    )
    agents: dict[str, SubagentOverrideConfig] = Field(
        default_factory=dict,
        description="Per-agent configuration overrides keyed by agent name",
    )

    def get_timeout_for(self, agent_name: str) -> int:
        """Get the effective timeout for a specific agent.

        Args:
            agent_name: The name of the subagent.

        Returns:
            The timeout in seconds, using per-agent override if set, otherwise global default.
        """
        override = self.agents.get(agent_name)
        if override is not None and override.timeout_seconds is not None:
            return override.timeout_seconds
        return self.timeout_seconds

    def get_model_for(self, agent_name: str) -> str | None:
        """Get the effective model name for a specific agent.

        Args:
            agent_name: The name of the subagent.

        Returns:
            The configured model name, using per-agent override first, then global
            default, otherwise None to preserve builtin behavior.
        """
        override = self.agents.get(agent_name)
        if override is not None and override.model_name is not None:
            return override.model_name
        return self.model_name

    def get_thinking_enabled_for(self, agent_name: str) -> bool | None:
        """Get the effective thinking mode for a specific agent."""
        override = self.agents.get(agent_name)
        if override is not None and override.thinking_enabled is not None:
            return override.thinking_enabled
        return self.thinking_enabled


_subagents_config: SubagentsAppConfig = SubagentsAppConfig()


def get_subagents_app_config() -> SubagentsAppConfig:
    """Get the current subagents configuration."""
    return _subagents_config


def load_subagents_config_from_dict(config_dict: dict) -> None:
    """Load subagents configuration from a dictionary."""
    global _subagents_config
    _subagents_config = SubagentsAppConfig(**config_dict)

    overrides_summary = {}
    for name, override in _subagents_config.agents.items():
        parts: list[str] = []
        if override.timeout_seconds is not None:
            parts.append(f"timeout={override.timeout_seconds}s")
        if override.model_name is not None:
            parts.append(f"model={override.model_name}")
        if override.thinking_enabled is not None:
            parts.append(f"thinking={override.thinking_enabled}")
        if parts:
            overrides_summary[name] = ", ".join(parts)
    if overrides_summary:
        logger.info(
            "Subagents config loaded: default timeout=%ss, default model=%s, default thinking=%s, per-agent overrides=%s",
            _subagents_config.timeout_seconds,
            _subagents_config.model_name or "<builtin>",
            _subagents_config.thinking_enabled if _subagents_config.thinking_enabled is not None else "<builtin>",
            overrides_summary,
        )
    else:
        logger.info(
            "Subagents config loaded: default timeout=%ss, default model=%s, default thinking=%s, no per-agent overrides",
            _subagents_config.timeout_seconds,
            _subagents_config.model_name or "<builtin>",
            _subagents_config.thinking_enabled if _subagents_config.thinking_enabled is not None else "<builtin>",
        )
