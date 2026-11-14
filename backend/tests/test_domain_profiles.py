"""Domain isolation, configuration lifecycle, and source-query integration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.community.knowledge_base.query_expansion import alias_queries, build_query_variants, focused_queries, retry_queries
from src.config.app_config import AppConfig, reset_app_config
from src.config.domain_config import DomainProfile, get_domain_profile, render_domain_instructions, set_domain_profile

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_profile():
    set_domain_profile()
    yield
    reset_app_config()


def test_default_never_adds_fiscal_or_historical_terms():
    for question in ["How does API retry work?", "民国财政情况", "database failure"]:
        assert [v["query"] for v in build_query_variants(question)] == [question]
        assert retry_queries(question) == []
    assert render_domain_instructions() == ""


def test_profile_is_relative_to_config_and_inline_fields_override(tmp_path, monkeypatch):
    (tmp_path / "domain.yaml").write_text("name: custom\ninstructions: cite versioned APIs\nquery_aliases:\n  API: [接口]\n")
    config = tmp_path / "config.yaml"
    config.write_text("models: []\nsandbox:\n  use: src.sandbox.local:LocalSandboxProvider\ndomain:\n  profile: domain.yaml\n  name: local\n")
    monkeypatch.chdir(tmp_path.parent)
    app = AppConfig.from_file(str(config))
    assert app.domain.name == "local"
    assert alias_queries("API retries") == ["接口 retries"]
    assert "cite versioned APIs" in render_domain_instructions()
    reset_app_config()
    assert get_domain_profile().name == "general"
    assert alias_queries("API retries") == []


def test_history_profile_uses_longest_alias_without_duplicate_periods():
    set_domain_profile(DomainProfile.from_config({"profile": "examples/fiscal-history/domain.yaml"}, config_dir=ROOT))
    assert alias_queries("民国时期财政情况") == ["民国财政情况"]
    assert "晚清财政情况" in alias_queries("清代末期财政情况")
    assert "民国时期财政收入结构" in focused_queries("民国时期财政情况")
    assert all("时期时期" not in query for query in retry_queries("民国时期财政情况"))


def test_switching_profiles_removes_previous_domain_behavior():
    set_domain_profile(DomainProfile.from_config({"profile": "examples/fiscal-history/domain.yaml"}, config_dir=ROOT))
    assert len(build_query_variants("民国财政情况")) > 1
    set_domain_profile(DomainProfile.from_config({"profile": "examples/technical-docs/domain.yaml"}, config_dir=ROOT))
    assert alias_queries("民国财政情况") == []
    variants = build_query_variants("API retry policy", scoped=True, limit=3)
    assert len(variants) == 3
    assert variants[0]["query"] == "API retry policy"
    assert not any("财政" in v["query"] for v in variants)
    assert alias_queries("capitalization") == []


@pytest.mark.parametrize("data", [{"unknown_option": True}, {"query_aliases": {"": ["x"]}}, {"rewrite_rules": [{"pattern": "[", "replacements": ["x"]}]}])
def test_invalid_domain_settings_fail_at_startup(data):
    with pytest.raises(ValidationError):
        DomainProfile.model_validate(data)


def test_hilo_config_path_takes_precedence_and_legacy_path_still_works(tmp_path, monkeypatch):
    old = tmp_path / "old.yaml"
    new = tmp_path / "hilo.yaml"
    old.touch()
    new.touch()
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(old))
    monkeypatch.setenv("HILO_CONFIG_PATH", str(new))
    assert AppConfig.resolve_config_path() == new
    monkeypatch.delenv("HILO_CONFIG_PATH")
    assert AppConfig.resolve_config_path() == old
