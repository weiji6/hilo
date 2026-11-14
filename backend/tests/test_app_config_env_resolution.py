"""Tests for AppConfig environment-variable resolution."""

from __future__ import annotations

import logging

import src.config.app_config as app_config_module
from src.config.app_config import AppConfig
from src.config.extensions_config import ExtensionsConfig


def test_resolve_env_variables_supports_default_value(monkeypatch):
    monkeypatch.delenv("QDRANT_MODE", raising=False)

    resolved = AppConfig.resolve_env_variables("${QDRANT_MODE:-local}")

    assert resolved == "local"


def test_resolve_env_variables_prefers_env_over_default(monkeypatch):
    monkeypatch.setenv("QDRANT_MODE", "server")

    resolved = AppConfig.resolve_env_variables("${QDRANT_MODE:-local}")

    assert resolved == "server"


def test_resolve_env_variables_supports_empty_default(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)

    resolved = AppConfig.resolve_env_variables("${QDRANT_URL:-}")

    assert resolved == ""


def test_resolve_env_variables_keeps_legacy_dollar_syntax(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    resolved = AppConfig.resolve_env_variables("$OPENAI_API_KEY")

    assert resolved == "test-key"


def test_from_file_skips_models_with_missing_env_vars(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        app_config_module.ExtensionsConfig,
        "from_file",
        classmethod(lambda cls: ExtensionsConfig()),
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
models:
  - name: doubao
    display_name: Doubao
    use: langchain_deepseek:ChatDeepSeek
    model: doubao-seed-2.0-pro
    api_key: $VOLCENGINE_API_KEY
  - name: openrouter
    display_name: OpenRouter
    use: langchain_openai:ChatOpenAI
    model: qwen/qwen3.6-plus-preview:free
    api_key: $OPENAI_API_KEY
sandbox:
  use: src.sandbox.local:LocalSandboxProvider
""".strip()
    )

    with caplog.at_level(logging.WARNING):
        config = AppConfig.from_file(str(config_path))

    assert [model.name for model in config.models] == ["openrouter"]
    assert "Skipping model 'doubao'" in caplog.text
