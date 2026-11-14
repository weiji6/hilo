"""Subagent configuration definitions."""

from dataclasses import dataclass, field


@dataclass
class SubagentConfig:
    """Configuration for a subagent.

    Attributes:
        name: Unique identifier for the subagent.
        description: When Claude should delegate to this subagent.
        system_prompt: The system prompt that guides the subagent's behavior.
        tools: Optional list of tool names to allow. If None, inherits all tools.
        disallowed_tools: Optional list of tool names to deny.
        model: Model to use - 'inherit' uses parent's model.
        thinking_enabled: Whether to enable model thinking/reasoning mode for this subagent.
            Defaults to False — subagents are tool-call-heavy; reasoning overhead is better
            spent in the lead agent that orchestrates and synthesises results.
        max_turns: Maximum number of agent turns before stopping.
        timeout_seconds: Maximum execution time in seconds (default: 3600 = 1 hour).
    """

    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
    model: str = "inherit"
    thinking_enabled: bool = False
    max_turns: int = 200
    timeout_seconds: int = 3600
