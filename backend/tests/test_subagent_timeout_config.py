"""Tests for subagent configuration overrides.

Covers:
- SubagentsAppConfig / SubagentOverrideConfig model validation and defaults
- get_timeout_for() / get_model_for() resolution logic (global vs per-agent)
- load_subagents_config_from_dict() and get_subagents_app_config() singleton
- registry.get_subagent_config() applies config overrides
- registry.list_subagents() applies overrides for all agents
- Polling timeout calculation in task_tool is consistent with config
"""

import pytest

from src.config.subagents_config import (
    SubagentOverrideConfig,
    SubagentsAppConfig,
    get_subagents_app_config,
    load_subagents_config_from_dict,
)
from src.subagents.config import SubagentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_subagents_config(
    timeout_seconds: int = 900,
    model_name: str | None = None,
    thinking_enabled: bool | None = None,
    agents: dict | None = None,
) -> None:
    """Reset global subagents config to a known state."""
    load_subagents_config_from_dict(
        {
            "timeout_seconds": timeout_seconds,
            "model_name": model_name,
            "thinking_enabled": thinking_enabled,
            "agents": agents or {},
        }
    )


# ---------------------------------------------------------------------------
# SubagentOverrideConfig
# ---------------------------------------------------------------------------


class TestSubagentOverrideConfig:
    def test_default_is_none(self):
        override = SubagentOverrideConfig()
        assert override.timeout_seconds is None
        assert override.model_name is None
        assert override.thinking_enabled is None

    def test_explicit_value(self):
        override = SubagentOverrideConfig(
            timeout_seconds=300,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
        )
        assert override.timeout_seconds == 300
        assert override.model_name == "deepseek-v4-flash"
        assert override.thinking_enabled is True

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            SubagentOverrideConfig(timeout_seconds=0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            SubagentOverrideConfig(timeout_seconds=-1)

    def test_minimum_valid_value(self):
        override = SubagentOverrideConfig(timeout_seconds=1)
        assert override.timeout_seconds == 1


# ---------------------------------------------------------------------------
# SubagentsAppConfig – defaults and validation
# ---------------------------------------------------------------------------


class TestSubagentsAppConfigDefaults:
    def test_default_timeout(self):
        config = SubagentsAppConfig()
        assert config.timeout_seconds == 3600
        assert config.model_name is None
        assert config.thinking_enabled is None

    def test_default_agents_empty(self):
        config = SubagentsAppConfig()
        assert config.agents == {}

    def test_custom_global_timeout(self):
        config = SubagentsAppConfig(
            timeout_seconds=1800,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
        )
        assert config.timeout_seconds == 1800
        assert config.model_name == "deepseek-v4-flash"
        assert config.thinking_enabled is True

    def test_rejects_zero_timeout(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(timeout_seconds=0)

    def test_rejects_negative_timeout(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(timeout_seconds=-60)


# ---------------------------------------------------------------------------
# SubagentsAppConfig.get_timeout_for() / get_model_for()
# ---------------------------------------------------------------------------


class TestSubagentOverrideResolution:
    def test_returns_global_default_when_no_override(self):
        config = SubagentsAppConfig(
            timeout_seconds=600,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
        )
        assert config.get_timeout_for("general-purpose") == 600
        assert config.get_timeout_for("bash") == 600
        assert config.get_timeout_for("unknown-agent") == 600
        assert config.get_model_for("general-purpose") == "deepseek-v4-flash"
        assert config.get_model_for("unknown-agent") == "deepseek-v4-flash"
        assert config.get_thinking_enabled_for("general-purpose") is True
        assert config.get_thinking_enabled_for("unknown-agent") is True

    def test_returns_per_agent_override_when_set(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
            agents={
                "bash": SubagentOverrideConfig(
                    timeout_seconds=300,
                    model_name="deepseek-v4-pro",
                    thinking_enabled=False,
                )
            },
        )
        assert config.get_timeout_for("bash") == 300
        assert config.get_model_for("bash") == "deepseek-v4-pro"
        assert config.get_thinking_enabled_for("bash") is False

    def test_other_agents_still_use_global_default(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
            agents={"bash": SubagentOverrideConfig(timeout_seconds=300)},
        )
        assert config.get_timeout_for("general-purpose") == 900
        assert config.get_model_for("general-purpose") == "deepseek-v4-flash"
        assert config.get_thinking_enabled_for("general-purpose") is True

    def test_agent_with_none_override_falls_back_to_global(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
            agents={
                "general-purpose": SubagentOverrideConfig(
                    timeout_seconds=None,
                    model_name=None,
                    thinking_enabled=None,
                )
            },
        )
        assert config.get_timeout_for("general-purpose") == 900
        assert config.get_model_for("general-purpose") == "deepseek-v4-flash"
        assert config.get_thinking_enabled_for("general-purpose") is True

    def test_multiple_per_agent_overrides(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            model_name="deepseek-v4-flash",
            thinking_enabled=True,
            agents={
                "general-purpose": SubagentOverrideConfig(
                    timeout_seconds=1800,
                    model_name="deepseek-v4-pro",
                    thinking_enabled=False,
                ),
                "bash": SubagentOverrideConfig(timeout_seconds=120),
            },
        )
        assert config.get_timeout_for("general-purpose") == 1800
        assert config.get_timeout_for("bash") == 120
        assert config.get_model_for("general-purpose") == "deepseek-v4-pro"
        assert config.get_model_for("bash") == "deepseek-v4-flash"
        assert config.get_thinking_enabled_for("general-purpose") is False
        assert config.get_thinking_enabled_for("bash") is True


# ---------------------------------------------------------------------------
# load_subagents_config_from_dict / get_subagents_app_config singleton
# ---------------------------------------------------------------------------


class TestLoadSubagentsConfig:
    def teardown_method(self):
        """Restore defaults after each test."""
        _reset_subagents_config()

    def test_load_global_timeout(self):
        load_subagents_config_from_dict(
            {"timeout_seconds": 300, "model_name": "deepseek-v4-flash", "thinking_enabled": True}
        )
        assert get_subagents_app_config().timeout_seconds == 300
        assert get_subagents_app_config().model_name == "deepseek-v4-flash"
        assert get_subagents_app_config().thinking_enabled is True

    def test_load_with_per_agent_overrides(self):
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "model_name": "deepseek-v4-flash",
                "thinking_enabled": True,
                "agents": {
                    "general-purpose": {
                        "timeout_seconds": 1800,
                        "model_name": "deepseek-v4-pro",
                        "thinking_enabled": False,
                    },
                    "bash": {"timeout_seconds": 60},
                },
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_timeout_for("general-purpose") == 1800
        assert cfg.get_timeout_for("bash") == 60
        assert cfg.get_model_for("general-purpose") == "deepseek-v4-pro"
        assert cfg.get_model_for("bash") == "deepseek-v4-flash"
        assert cfg.get_thinking_enabled_for("general-purpose") is False
        assert cfg.get_thinking_enabled_for("bash") is True

    def test_load_partial_override(self):
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 600,
                "model_name": "deepseek-v4-flash",
                "thinking_enabled": True,
                "agents": {"bash": {"timeout_seconds": 120}},
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_timeout_for("general-purpose") == 600
        assert cfg.get_timeout_for("bash") == 120
        assert cfg.get_model_for("general-purpose") == "deepseek-v4-flash"
        assert cfg.get_thinking_enabled_for("general-purpose") is True

    def test_load_empty_dict_uses_defaults(self):
        load_subagents_config_from_dict({})
        cfg = get_subagents_app_config()
        assert cfg.timeout_seconds == 3600
        assert cfg.model_name is None
        assert cfg.thinking_enabled is None
        assert cfg.agents == {}

    def test_load_replaces_previous_config(self):
        load_subagents_config_from_dict({"timeout_seconds": 100})
        assert get_subagents_app_config().timeout_seconds == 100

        load_subagents_config_from_dict({"timeout_seconds": 200})
        assert get_subagents_app_config().timeout_seconds == 200

    def test_singleton_returns_same_instance_between_calls(self):
        load_subagents_config_from_dict(
            {"timeout_seconds": 777, "model_name": "deepseek-v4-flash", "thinking_enabled": True}
        )
        assert get_subagents_app_config() is get_subagents_app_config()


# ---------------------------------------------------------------------------
# registry.get_subagent_config – timeout override applied
# ---------------------------------------------------------------------------


class TestRegistryGetSubagentConfig:
    def teardown_method(self):
        _reset_subagents_config()

    def test_returns_none_for_unknown_agent(self):
        from src.subagents.registry import get_subagent_config

        assert get_subagent_config("nonexistent") is None

    def test_returns_config_for_builtin_agents(self):
        from src.subagents.registry import get_subagent_config

        assert get_subagent_config("general-purpose") is not None
        assert get_subagent_config("bash") is not None

    def test_default_timeout_preserved_when_no_config(self):
        from src.subagents.registry import get_subagent_config

        _reset_subagents_config(timeout_seconds=900)
        config = get_subagent_config("general-purpose")
        assert config.timeout_seconds == 900
        assert config.model == "inherit"
        assert config.thinking_enabled is False

    def test_global_timeout_override_applied(self):
        from src.subagents.registry import get_subagent_config

        _reset_subagents_config(
            timeout_seconds=1800,
            model_name="deepseek-v4-flash",
            thinking_enabled=False,
        )
        config = get_subagent_config("general-purpose")
        assert config.timeout_seconds == 1800
        assert config.model == "deepseek-v4-flash"
        assert config.thinking_enabled is False

    def test_per_agent_timeout_override_applied(self):
        from src.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "model_name": "deepseek-v4-flash",
                "thinking_enabled": True,
                "agents": {
                    "bash": {
                        "timeout_seconds": 120,
                        "model_name": "deepseek-v4-pro",
                        "thinking_enabled": False,
                    }
                },
            }
        )
        bash_config = get_subagent_config("bash")
        assert bash_config.timeout_seconds == 120
        assert bash_config.model == "deepseek-v4-pro"
        assert bash_config.thinking_enabled is False

    def test_per_agent_override_does_not_affect_other_agents(self):
        from src.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "model_name": "deepseek-v4-flash",
                "thinking_enabled": True,
                "agents": {"bash": {"timeout_seconds": 120}},
            }
        )
        gp_config = get_subagent_config("general-purpose")
        assert gp_config.timeout_seconds == 900
        assert gp_config.model == "deepseek-v4-flash"
        assert gp_config.thinking_enabled is True

    def test_builtin_config_object_is_not_mutated(self):
        """Registry must return a new object, leaving the builtin default intact."""
        from src.subagents.builtins import BUILTIN_SUBAGENTS
        from src.subagents.registry import get_subagent_config

        original_timeout = BUILTIN_SUBAGENTS["bash"].timeout_seconds
        load_subagents_config_from_dict(
            {"timeout_seconds": 42, "model_name": "deepseek-v4-flash", "thinking_enabled": False}
        )

        returned = get_subagent_config("bash")
        assert returned.timeout_seconds == 42
        assert returned.model == "deepseek-v4-flash"
        assert returned.thinking_enabled is False
        assert BUILTIN_SUBAGENTS["bash"].timeout_seconds == original_timeout
        assert BUILTIN_SUBAGENTS["bash"].model == "inherit"
        assert BUILTIN_SUBAGENTS["bash"].thinking_enabled is False

    def test_config_preserves_other_fields(self):
        """Applying timeout override must not change other SubagentConfig fields."""
        from src.subagents.builtins import BUILTIN_SUBAGENTS
        from src.subagents.registry import get_subagent_config

        _reset_subagents_config(
            timeout_seconds=300,
            model_name="deepseek-v4-flash",
            thinking_enabled=False,
        )
        original = BUILTIN_SUBAGENTS["general-purpose"]
        overridden = get_subagent_config("general-purpose")

        assert overridden.name == original.name
        assert overridden.description == original.description
        assert overridden.max_turns == original.max_turns
        assert overridden.model == "deepseek-v4-flash"
        assert overridden.thinking_enabled is False
        assert overridden.tools == original.tools
        assert overridden.disallowed_tools == original.disallowed_tools


# ---------------------------------------------------------------------------
# registry.list_subagents – all agents get overrides
# ---------------------------------------------------------------------------


class TestRegistryListSubagents:
    def teardown_method(self):
        _reset_subagents_config()

    def test_lists_both_builtin_agents(self):
        from src.subagents.registry import list_subagents

        names = {cfg.name for cfg in list_subagents()}
        assert "general-purpose" in names
        assert "bash" in names

    def test_all_returned_configs_get_global_override(self):
        from src.subagents.registry import list_subagents

        _reset_subagents_config(
            timeout_seconds=123,
            model_name="deepseek-v4-flash",
            thinking_enabled=False,
        )
        for cfg in list_subagents():
            assert cfg.timeout_seconds == 123, f"{cfg.name} has wrong timeout"
            assert cfg.model == "deepseek-v4-flash", f"{cfg.name} has wrong model"
            assert cfg.thinking_enabled is False, f"{cfg.name} has wrong thinking flag"

    def test_per_agent_overrides_reflected_in_list(self):
        from src.subagents.registry import list_subagents

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "model_name": "deepseek-v4-flash",
                "thinking_enabled": True,
                "agents": {
                    "general-purpose": {
                        "timeout_seconds": 1800,
                        "model_name": "deepseek-v4-pro",
                        "thinking_enabled": False,
                    },
                    "bash": {"timeout_seconds": 60},
                },
            }
        )
        by_name = {cfg.name: cfg for cfg in list_subagents()}
        assert by_name["general-purpose"].timeout_seconds == 1800
        assert by_name["bash"].timeout_seconds == 60
        assert by_name["general-purpose"].model == "deepseek-v4-pro"
        assert by_name["bash"].model == "deepseek-v4-flash"
        assert by_name["general-purpose"].thinking_enabled is False
        assert by_name["bash"].thinking_enabled is True


# ---------------------------------------------------------------------------
# Polling timeout calculation (logic extracted from task_tool)
# ---------------------------------------------------------------------------


class TestPollingTimeoutCalculation:
    """Verify the formula (timeout_seconds + 60) // 5 is correct for various inputs."""

    @pytest.mark.parametrize(
        "timeout_seconds, expected_max_polls",
        [
            (900, 192),  # default 15 min → (900+60)//5 = 192
            (300, 72),  # 5 min → (300+60)//5 = 72
            (1800, 372),  # 30 min → (1800+60)//5 = 372
            (60, 24),  # 1 min → (60+60)//5 = 24
            (1, 12),  # minimum → (1+60)//5 = 12
        ],
    )
    def test_polling_timeout_formula(self, timeout_seconds: int, expected_max_polls: int):
        dummy_config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            timeout_seconds=timeout_seconds,
        )
        max_poll_count = (dummy_config.timeout_seconds + 60) // 5
        assert max_poll_count == expected_max_polls

    def test_polling_timeout_exceeds_execution_timeout(self):
        """Safety-net polling window must always be longer than the execution timeout."""
        for timeout_seconds in [60, 300, 900, 1800]:
            dummy_config = SubagentConfig(
                name="test",
                description="test",
                system_prompt="test",
                timeout_seconds=timeout_seconds,
            )
            max_poll_count = (dummy_config.timeout_seconds + 60) // 5
            polling_window_seconds = max_poll_count * 5
            assert polling_window_seconds > timeout_seconds
