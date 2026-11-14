import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage

from src.community.knowledge_base.book_metadata import load_book_metadata_for_source, save_book_metadata
from src.community.knowledge_base.folder_registry import ensure_folder_path
from src.community.knowledge_base.book_metadata_runtime import (
    _extract_response_text,
    build_existing_folder_tree,
    generate_book_metadata_record,
    maybe_generate_book_metadata,
)
from src.config.knowledge_base_config import BookMetadataConfig


class _FakeModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def invoke(self, messages):
        return SimpleNamespace(content=self._response_text)


class _FlakyModel:
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response)


def _structured_payload() -> dict[str, object]:
    pages = []
    for page_no in range(1, 13):
        text = f"第 {page_no} 页内容"
        if page_no == 3:
            text = "目录\n第一章 绪论 .......... 1\n第二章 财政 .......... 12"
        pages.append(
            {
                "page_no": page_no,
                "pdf_page_no": page_no,
                "book_page_no": page_no,
                "text": text,
                "paragraphs": [{"text": text}],
            }
        )
    return {
        "source_filename": "demo.pdf",
        "title": "Demo Book",
        "pages": pages,
    }


def test_generate_book_metadata_record_persists_model_output(monkeypatch, tmp_path) -> None:
    response_text = """
```json
{
  "title": "Demo Book",
  "type": {"value": "core", "confidence": 0.9, "evidence": "目录和前言"},
  "folder": {"value": "财政史", "confidence": 0.8, "evidence": "目录"},
  "categories": [{"value": "财政史", "confidence": 0.8, "evidence": "目录"}],
  "summary": {"value": "财政通史著作", "confidence": 0.7, "evidence": "样本文本"}
}
```
""".strip()
    fake_models = ModuleType("src.models")
    fake_models.create_chat_model = lambda name=None, thinking_enabled=False, **kwargs: _FakeModel(response_text)
    monkeypatch.setitem(sys.modules, "src.models", fake_models)

    record, saved_path = generate_book_metadata_record(
        structured_payload=_structured_payload(),
        source_filename="demo.pdf",
        title="Demo Book",
        output_dir=tmp_path,
        config=BookMetadataConfig(enabled=True, model_name="demo-model"),
    )

    assert saved_path.exists()
    assert record.suggestion is not None
    assert record.suggestion.type is not None
    assert record.suggestion.type.value == "core"
    loaded = load_book_metadata_for_source(tmp_path, "demo.pdf")
    assert loaded is not None
    assert loaded.model_name == "demo-model"
    assert loaded.suggestion is not None
    assert loaded.suggestion.folder is not None
    assert loaded.suggestion.folder.value == "财政史"


def test_generate_book_metadata_record_explicitly_disables_provider_thinking(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_create_chat_model(name=None, thinking_enabled=False, **kwargs):
        captured["name"] = name
        captured["thinking_enabled"] = thinking_enabled
        captured["kwargs"] = kwargs
        return _FakeModel('{"title":"Demo Book","categories":[],"eras":[],"regions":[],"keywords":[],"notes":null}')

    fake_models = ModuleType("src.models")
    fake_models.create_chat_model = _fake_create_chat_model
    monkeypatch.setitem(sys.modules, "src.models", fake_models)

    generate_book_metadata_record(
        structured_payload=_structured_payload(),
        source_filename="demo.pdf",
        title="Demo Book",
        output_dir=tmp_path,
        config=BookMetadataConfig(enabled=True, model_name="demo-model"),
    )

    assert captured["name"] == "demo-model"
    assert captured["thinking_enabled"] is False
    # No extra kwargs — thinking is suppressed via the model's when_thinking_disabled config
    assert captured["kwargs"] == {}


def test_maybe_generate_book_metadata_returns_none_when_disabled(tmp_path) -> None:
    result = maybe_generate_book_metadata(
        structured_payload=_structured_payload(),
        source_filename="demo.pdf",
        title="Demo Book",
        output_dir=tmp_path,
        config=BookMetadataConfig(enabled=False),
    )
    assert result is None


def test_generate_book_metadata_record_retries_transient_invoke_failure(monkeypatch, tmp_path) -> None:
    response_text = """
```json
{
  "title": "Demo Book",
  "type": {"value": "core", "confidence": 0.9, "evidence": "目录和前言"}
}
```
""".strip()
    flaky_model = _FlakyModel(
        [
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            response_text,
        ]
    )
    fake_models = ModuleType("src.models")
    fake_models.create_chat_model = lambda name=None, thinking_enabled=False, **kwargs: flaky_model
    monkeypatch.setitem(sys.modules, "src.models", fake_models)
    monkeypatch.setattr(
        "src.community.knowledge_base.book_metadata_runtime.sleep",
        lambda seconds: None,
    )

    record, saved_path = generate_book_metadata_record(
        structured_payload=_structured_payload(),
        source_filename="demo.pdf",
        title="Demo Book",
        output_dir=tmp_path,
        config=BookMetadataConfig(enabled=True, model_name="demo-model"),
    )

    assert flaky_model.calls == 2
    assert saved_path.exists()
    assert record.suggestion is not None
    assert record.suggestion.type is not None
    assert record.suggestion.type.value == "core"


def test_build_existing_folder_tree_renders_nested_paths(tmp_path) -> None:
    save_book_metadata(
        tmp_path,
        "a.pdf",
        {
            "source_filename": "a.pdf",
            "source_title": "A",
            "page_count": 1,
            "prompt_input": {
                "source_filename": "a.pdf",
                "title": "A",
                "page_count": 1,
                "selected_pages": [],
                "selection_notes": [],
            },
            "suggestion": {
                "folder": {"value": "财政史/清代", "confidence": 1.0, "evidence": "manual"},
            },
        },
    )
    save_book_metadata(
        tmp_path,
        "b.pdf",
        {
            "source_filename": "b.pdf",
            "source_title": "B",
            "page_count": 1,
            "prompt_input": {
                "source_filename": "b.pdf",
                "title": "B",
                "page_count": 1,
                "selected_pages": [],
                "selection_notes": [],
            },
            "suggestion": {
                "categories": [{"value": "制度史", "confidence": 1.0, "evidence": "manual"}],
            },
        },
    )

    tree = build_existing_folder_tree(tmp_path)

    assert tree is not None
    assert "财政史/" in tree
    assert "清代/" in tree
    assert "a.pdf" in tree
    assert "制度史/" in tree
    assert "b.pdf" in tree


def test_build_existing_folder_tree_includes_empty_registry_folders(tmp_path) -> None:
    ensure_folder_path(tmp_path / ".folders.json", "财政史/明代")

    tree = build_existing_folder_tree(
        tmp_path,
        folder_registry_path=tmp_path / ".folders.json",
    )

    assert tree is not None
    assert "财政史/" in tree
    assert "明代/" in tree


def test_extract_response_text_accepts_prefixed_json_in_content() -> None:
    response = SimpleNamespace(content='下面是结果：\n{"title":"Demo Book","categories":[],"eras":[],"regions":[],"keywords":[],"notes":null}')

    text = _extract_response_text(response)

    assert text.startswith('{"title":"Demo Book"')


def test_extract_response_text_uses_json_in_reasoning_when_content_empty() -> None:
    response = AIMessage(
        content="",
        additional_kwargs={
            "reasoning": '先分析一下。\n{"title":"Demo Book","categories":[],"eras":[],"regions":[],"keywords":[],"notes":null}'
        },
    )

    text = _extract_response_text(response)

    assert text.startswith('{"title":"Demo Book"')


def test_extract_response_text_raises_for_reasoning_only_analysis() -> None:
    response = AIMessage(
        content="",
        additional_kwargs={
            "reasoning": "The user wants me to classify a book based on provided excerpts."
        },
    )

    with pytest.raises(ValueError, match="reasoning-only analysis"):
        _extract_response_text(response)
