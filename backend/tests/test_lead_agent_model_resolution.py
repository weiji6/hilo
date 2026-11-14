"""Tests for lead agent runtime model resolution behavior."""

from __future__ import annotations

import pytest

from src.agents.lead_agent import agent as lead_agent_module
from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.sandbox_config import SandboxConfig


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )


def _make_model(name: str, *, supports_thinking: bool) -> ModelConfig:
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use="langchain_openai:ChatOpenAI",
        model=name,
        supports_thinking=supports_thinking,
        supports_vision=False,
    )


def test_resolve_model_name_falls_back_to_default(monkeypatch, caplog):
    app_config = _make_app_config(
        [
            _make_model("default-model", supports_thinking=False),
            _make_model("other-model", supports_thinking=True),
        ]
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    with caplog.at_level("WARNING"):
        resolved = lead_agent_module._resolve_model_name("missing-model")

    assert resolved == "default-model"
    assert "fallback to default model 'default-model'" in caplog.text


def test_resolve_model_name_uses_default_when_none(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model("default-model", supports_thinking=False),
            _make_model("other-model", supports_thinking=True),
        ]
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    resolved = lead_agent_module._resolve_model_name(None)

    assert resolved == "default-model"


def test_resolve_model_name_raises_when_no_models_configured(monkeypatch):
    app_config = _make_app_config([])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)

    with pytest.raises(
        ValueError,
        match="No chat models are configured",
    ):
        lead_agent_module._resolve_model_name("missing-model")


def test_make_lead_agent_disables_thinking_when_model_does_not_support_it(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import src.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "_build_middlewares", lambda config, model_name: [])

    captured: dict[str, object] = {}

    def _fake_create_chat_model(*, name, thinking_enabled):
        captured["name"] = name
        captured["thinking_enabled"] = thinking_enabled
        return object()

    monkeypatch.setattr(lead_agent_module, "create_chat_model", _fake_create_chat_model)
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    result = lead_agent_module.make_lead_agent(
        {
            "configurable": {
                "model_name": "safe-model",
                "thinking_enabled": True,
                "is_plan_mode": False,
                "subagent_enabled": False,
            }
        }
    )

    assert captured["name"] == "safe-model"
    assert captured["thinking_enabled"] is False
    assert result["model"] is not None


def test_make_lead_agent_hides_raw_task_tool_in_plan_mode(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import src.tools as tools_module

    captured_tool_kwargs: dict[str, object] = {}

    def _fake_get_available_tools(**kwargs):
        captured_tool_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", _fake_get_available_tools)
    monkeypatch.setattr(lead_agent_module, "_build_middlewares", lambda config, model_name: [])
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    lead_agent_module.make_lead_agent(
        {
            "configurable": {
                "model_name": "safe-model",
                "thinking_enabled": False,
                "is_plan_mode": True,
                "subagent_enabled": True,
            }
        }
    )

    assert captured_tool_kwargs["subagent_enabled"] is True
    assert captured_tool_kwargs["include_task_tool"] is False
    # Direct reading is registered for overview turns; the runtime middleware
    # hides it during detailed research.
    assert captured_tool_kwargs["allowed_tool_names"] == {"book_search", "knowledge_locate"}
    assert "book_search" in captured_tool_kwargs["allowed_tool_names"]


def test_make_lead_agent_registers_overview_reading_when_subagents_enabled_outside_plan_mode(monkeypatch):
    app_config = _make_app_config([_make_model("safe-model", supports_thinking=False)])

    import src.tools as tools_module

    captured_tool_kwargs: dict[str, object] = {}

    def _fake_get_available_tools(**kwargs):
        captured_tool_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_available_tools", _fake_get_available_tools)
    monkeypatch.setattr(lead_agent_module, "_build_middlewares", lambda config, model_name: [])
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    lead_agent_module.make_lead_agent(
        {
            "configurable": {
                "model_name": "safe-model",
                "thinking_enabled": False,
                "is_plan_mode": False,
                "subagent_enabled": True,
            }
        }
    )

    assert captured_tool_kwargs["subagent_enabled"] is True
    assert captured_tool_kwargs["include_task_tool"] is True
    assert captured_tool_kwargs["allowed_tool_names"] == {"book_search", "knowledge_locate", "task"}
    assert "book_search" in captured_tool_kwargs["allowed_tool_names"]


def test_build_middlewares_uses_resolved_model_name_for_vision(monkeypatch):
    app_config = _make_app_config(
        [
            _make_model("stale-model", supports_thinking=False),
            ModelConfig(
                name="vision-model",
                display_name="vision-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="vision-model",
                supports_thinking=False,
                supports_vision=True,
            ),
        ]
    )

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode, **kwargs: None)

    middlewares = lead_agent_module._build_middlewares(
        {"configurable": {"model_name": "stale-model", "is_plan_mode": False, "subagent_enabled": False}},
        model_name="vision-model",
    )

    assert any(isinstance(m, lead_agent_module.ViewImageMiddleware) for m in middlewares)


def test_build_middlewares_includes_book_coverage_middleware(monkeypatch):
    app_config = _make_app_config([_make_model("default-model", supports_thinking=False)])

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode, **kwargs: None)

    middlewares = lead_agent_module._build_middlewares(
        {"configurable": {"model_name": "default-model", "is_plan_mode": False, "subagent_enabled": False}},
        model_name="default-model",
    )

    assert any(type(m).__name__ == "BookCoverageMiddleware" for m in middlewares)


def test_build_middlewares_omits_book_coverage_when_subagents_enabled(monkeypatch):
    app_config = _make_app_config([_make_model("default-model", supports_thinking=False)])
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode, **kwargs: None)

    middlewares = lead_agent_module._build_middlewares(
        {"configurable": {"model_name": "default-model", "is_plan_mode": False, "subagent_enabled": True}},
        model_name="default-model",
    )

    assert not any(type(m).__name__ == "BookCoverageMiddleware" for m in middlewares)


def test_create_todo_list_middleware_uses_parallel_batch_language_when_subagents_enabled(monkeypatch):
    captured: dict[str, str] = {}

    class DummyTodoListMiddleware:
        def __init__(self, system_prompt: str, tool_description: str, **kwargs):
            captured["system_prompt"] = system_prompt
            captured["tool_description"] = tool_description

    monkeypatch.setattr(lead_agent_module, "TodoListMiddleware", DummyTodoListMiddleware)

    middleware = lead_agent_module._create_todo_list_middleware(
        True,
        subagent_enabled=True,
        max_concurrent_subagents=3,
    )

    assert middleware is not None
    assert "execution board" in captured["system_prompt"]
    assert "parallel batch" in captured["system_prompt"]
    assert "up to 3" in captured["system_prompt"]
    assert "will drain the queued todos" in captured["system_prompt"]
    assert "the lead agent runs one `book_search` routing pass" in captured["system_prompt"]
    assert "each carrying its assigned doc_ids" in captured["system_prompt"]
    assert "任务目标 / 探索方向" in captured["system_prompt"]
    assert "`write_todos` is the dispatch point" in captured["system_prompt"]
    assert "Do NOT mirror the same batch with manual `task` calls" in captured["system_prompt"]
    assert "Parallel batches" in captured["tool_description"]
    assert "Evidence-gap retrieval with subtasks" in captured["tool_description"]
    assert "Pair each historical retrieval todo with the specific `doc_id`(s)" in captured["tool_description"]
    assert "mark multiple items as `in_progress` together in one `write_todos` call" in captured["tool_description"]
    assert "run that parallel batch and return findings before you continue" in captured["tool_description"]
