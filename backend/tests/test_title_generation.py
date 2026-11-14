"""Tests for automatic thread title generation."""

import pytest
from types import SimpleNamespace

from src.agents.middlewares.title_middleware import TitleMiddleware, generate_title_candidate
from src.config.title_config import TitleConfig, get_title_config, set_title_config


class TestTitleConfig:
    """Tests for TitleConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TitleConfig()
        assert config.enabled is True
        assert config.max_words == 6
        assert config.max_chars == 60
        assert config.model_name is None

    def test_custom_config(self):
        """Test custom configuration."""
        config = TitleConfig(
            enabled=False,
            max_words=10,
            max_chars=100,
            model_name="gpt-4",
        )
        assert config.enabled is False
        assert config.max_words == 10
        assert config.max_chars == 100
        assert config.model_name == "gpt-4"

    def test_config_validation(self):
        """Test configuration validation."""
        # max_words should be between 1 and 20
        with pytest.raises(ValueError):
            TitleConfig(max_words=0)
        with pytest.raises(ValueError):
            TitleConfig(max_words=21)

        # max_chars should be between 10 and 200
        with pytest.raises(ValueError):
            TitleConfig(max_chars=5)
        with pytest.raises(ValueError):
            TitleConfig(max_chars=201)

    def test_get_set_config(self):
        """Test global config getter and setter."""
        original_config = get_title_config()

        # Set new config
        new_config = TitleConfig(enabled=False, max_words=10)
        set_title_config(new_config)

        # Verify it was set
        assert get_title_config().enabled is False
        assert get_title_config().max_words == 10

        # Restore original config
        set_title_config(original_config)


class TestTitleMiddleware:
    """Tests for TitleMiddleware."""

    def test_middleware_initialization(self):
        """Test middleware can be initialized."""
        middleware = TitleMiddleware()
        assert middleware is not None
        assert middleware.state_schema is not None

    def test_extracts_clean_title_from_reasoning_output(self):
        middleware = TitleMiddleware()

        text = """
Thinking Process:
Analyze the Request:
Task: Generate a concise title.
Selection: 晚清六部紊乱

晚清六部紊乱
"""

        title = middleware._extract_title_from_response(text, max_chars=60, max_words=6)

        assert title == "晚清六部紊乱"

    def test_generate_title_uses_configured_model_name_and_strips_reasoning(self, monkeypatch):
        middleware = TitleMiddleware()
        original_config = get_title_config()
        set_title_config(TitleConfig(model_name="title-model"))

        captured: dict[str, object] = {}

        class _FakeModel:
            def invoke(self, prompt):
                captured["prompt"] = prompt
                return SimpleNamespace(content="Thinking Process:\nTitle: 晚清六部变局")

        def _fake_create_chat_model(*, name=None, thinking_enabled=False, **kwargs):
            captured["name"] = name
            captured["thinking_enabled"] = thinking_enabled
            return _FakeModel()

        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", _fake_create_chat_model)

        state = {
            "messages": [
                SimpleNamespace(type="human", content="用户问题"),
                SimpleNamespace(type="ai", content="助手回答"),
            ]
        }

        try:
            user_msg = middleware._get_user_msg(state)
            title = generate_title_candidate(user_msg)
        finally:
            set_title_config(original_config)

        assert captured["name"] == "title-model"
        assert captured["thinking_enabled"] is False
        assert title == "晚清六部变局"

    # TODO: Add integration tests with mock Runtime
    # def test_should_generate_title(self):
    #     """Test title generation trigger logic."""
    #     pass

    # def test_generate_title(self):
    #     """Test title generation."""
    #     pass

    # def test_after_agent_hook(self):
    #     """Test after_agent hook."""
    #     pass


# TODO: Add integration tests
# - Test with real LangGraph runtime
# - Test title persistence with checkpointer
# - Test fallback behavior when LLM fails
# - Test concurrent title generation
