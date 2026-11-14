from __future__ import annotations

from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.sandbox_config import SandboxConfig
from src.models import factory as factory_module


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )


def _make_model(
    name: str,
    *,
    supports_thinking: bool,
    extra_fields: dict | None = None,
) -> ModelConfig:
    payload = {
        "name": name,
        "display_name": name,
        "description": None,
        "use": "tests.fake:FakeModel",
        "model": name,
        "supports_thinking": supports_thinking,
        "supports_vision": False,
    }
    if extra_fields:
        payload.update(extra_fields)
    return ModelConfig(**payload)


def test_create_chat_model_injects_reasoning_none_when_thinking_disabled(monkeypatch):
    app_config = _make_app_config([_make_model("demo-model", supports_thinking=True)])
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda use, base: FakeModel)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    factory_module.create_chat_model(name="demo-model", thinking_enabled=False)

    assert captured["model"] == "demo-model"
    assert captured["extra_body"] == {"reasoning": {"effort": "none"}}


def test_create_chat_model_merges_extra_body_and_forces_reasoning_none(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model(
                "demo-model",
                supports_thinking=True,
                extra_fields={"extra_body": {"provider": {"sort": "latency"}}},
            )
        ]
    )
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda use, base: FakeModel)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    factory_module.create_chat_model(
        name="demo-model",
        thinking_enabled=False,
        extra_body={"metadata": {"source": "test"}},
    )

    assert captured["extra_body"] == {
        "provider": {"sort": "latency"},
        "metadata": {"source": "test"},
        "reasoning": {"effort": "none"},
    }


def test_create_chat_model_uses_when_thinking_enabled_without_injecting_none(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model(
                "demo-model",
                supports_thinking=True,
                extra_fields={"when_thinking_enabled": {"extra_body": {"include_reasoning": True}}},
            )
        ]
    )
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda use, base: FakeModel)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    factory_module.create_chat_model(name="demo-model", thinking_enabled=True)

    assert captured["extra_body"] == {"include_reasoning": True}


def test_create_chat_model_wraps_anthropic_with_minimax_compat(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model(
                "anthropic-compatible",
                supports_thinking=True,
                extra_fields={"use": "langchain_anthropic:ChatAnthropic"},
            )
        ]
    )

    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    model = factory_module.create_chat_model(
        name="anthropic-compatible",
        api_key="dummy",
        thinking_enabled=True,
    )

    assert model.__class__.__name__ == "MiniMaxAnthropicCompatChatAnthropic"


def test_create_chat_model_when_thinking_disabled_overrides_default_patch(monkeypatch):
    # MiniMax's correct disable parameter is the flat `reasoning_effort: "none"`, not
    # OpenAI's nested `reasoning: {effort: "none"}`. when_thinking_disabled lets each
    # provider declare its own disable patch instead of relying on the generic default.
    app_config = _make_app_config(
        [
            _make_model(
                "minimax-model",
                supports_thinking=True,
                extra_fields={
                    "extra_body": {"reasoning_split": True},
                    "when_thinking_disabled": {"extra_body": {"reasoning_effort": "none"}},
                },
            )
        ]
    )
    captured: dict = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda use, base: FakeModel)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    factory_module.create_chat_model(name="minimax-model", thinking_enabled=False)

    assert captured["extra_body"] == {
        "reasoning_split": True,
        "reasoning_effort": "none",
    }


def test_create_chat_model_falls_back_to_default_reasoning_patch_when_no_when_thinking_disabled(monkeypatch):
    # Models without when_thinking_disabled still get the generic reasoning.effort:none patch.
    app_config = _make_app_config(
        [_make_model("other-model", supports_thinking=True)]
    )
    captured: dict = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(factory_module, "resolve_class", lambda use, base: FakeModel)
    monkeypatch.setattr(factory_module, "is_tracing_enabled", lambda: False)

    factory_module.create_chat_model(name="other-model", thinking_enabled=False)

    assert captured["extra_body"] == {"reasoning": {"effort": "none"}}


def test_subagent_config_defaults_thinking_disabled():
    from src.subagents.config import SubagentConfig

    cfg = SubagentConfig(name="t", description="t", system_prompt="t")
    assert cfg.thinking_enabled is False, (
        "Subagents default to thinking_enabled=False — reasoning overhead belongs in "
        "the lead agent, not in tool-heavy subtasks."
    )
