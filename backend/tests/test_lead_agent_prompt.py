"""Verify generic evidence rules and administrator-controlled domain instructions."""

import pytest

from src.agents.lead_agent import prompt as prompt_module
from src.config.domain_config import DomainProfile, set_domain_profile


@pytest.fixture(autouse=True)
def clean_prompt_context(monkeypatch):
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda: "")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda: "")
    set_domain_profile()
    yield
    set_domain_profile()


def test_default_prompt_preserves_source_and_citation_guidance():
    prompt = prompt_module.apply_prompt_template()
    assert "Hilo" in prompt
    assert "book_search" in prompt and "knowledge_locate" in prompt
    assert "<citations>" in prompt
    assert "numbered" in prompt or "[citation:" in prompt
    assert "财政史问题要写得像历史学者" not in prompt
    assert "北洋政府" not in prompt


def test_domain_instructions_are_present_in_both_research_and_qa_modes():
    set_domain_profile(DomainProfile(name="versioned-docs", instructions="Cite the applicable release version."))
    for enabled in (False, True):
        prompt = prompt_module.apply_prompt_template(subagent_enabled=enabled, qa_mode=True)
        assert "Cite the applicable release version." in prompt
        assert "knowledge_locate" in prompt


def test_explicit_research_preserves_source_scoped_dispatch():
    prompt = prompt_module.apply_prompt_template(subagent_enabled=True, orchestrator_only=True)
    assert "assigned doc_ids" in prompt
    assert "write_todos" in prompt
    assert "explicitly requested deep research" in prompt
