from __future__ import annotations

import json

from src.community.knowledge_base.book_metadata import (
    BookMetadataPromptInput,
    build_book_metadata_prompt_bundle,
    build_book_metadata_record,
    load_book_metadata_for_source,
    normalize_folder_path,
    parse_book_metadata_suggestion,
    resolve_book_folder,
    save_book_metadata,
)


def _build_structured_payload(page_count: int = 15) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    for page_no in range(1, page_count + 1):
        if page_no == 3:
            text = "\n".join(
                [
                    "目录",
                    "第一章 绪论 .......... 1",
                    "第二章 财政制度 .......... 8",
                    "第三章 财政改革 .......... 15",
                ]
            )
        elif page_no <= 10:
            text = f"前置页 {page_no}\n这是第 {page_no} 页的前部内容。"
        else:
            text = f"正文页 {page_no}\n这一页是正文样本 {page_no}。"

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
        "schema_version": 1,
        "source_filename": "demo.pdf",
        "title": "Demo Book",
        "pages": pages,
    }


def test_build_book_metadata_prompt_bundle_only_uses_front_pages() -> None:
    payload = _build_structured_payload()

    bundle = build_book_metadata_prompt_bundle(
        payload,
        source_filename="demo.pdf",
        title="Demo Book",
        front_page_limit=10,
        body_sample_count=3,
        max_excerpt_chars=200,
        existing_folder_tree=".\n`-- 财政史/\n    `-- existing.pdf",
    )

    prompt_input = bundle.prompt_input
    assert isinstance(prompt_input, BookMetadataPromptInput)
    assert len(prompt_input.selected_pages) == 10
    assert [page.page_no for page in prompt_input.selected_pages] == list(range(1, 11))
    assert all(page.reasons == ["front_page"] for page in prompt_input.selected_pages)
    assert bundle.user_prompt.startswith("Title: Demo Book")
    assert "Page 3" in bundle.user_prompt
    assert "目录" in bundle.user_prompt
    assert "Source filename:" not in bundle.user_prompt
    assert "Reasons:" not in bundle.user_prompt
    assert "Return JSON with these fields:" not in bundle.user_prompt
    assert "Return raw JSON only." in bundle.system_prompt
    assert '"folder": {"value": "string", "confidence": 0.0, "evidence": "string"} or null' in bundle.system_prompt
    assert '"ocr_quality": {"value": "high|medium|low"' in bundle.system_prompt
    assert "`categories` are subject/domain labels" in bundle.system_prompt
    assert "### Existing Folder Tree" in bundle.user_prompt
    assert "existing.pdf" in bundle.user_prompt


def test_parse_book_metadata_suggestion_coerces_dict_title() -> None:
    """AI occasionally wraps title in a MetadataField-like dict — must be coerced to str."""
    suggestion = parse_book_metadata_suggestion(
        {
            "title": {"value": "行政院工作报告", "confidence": 0.95, "evidence": "封面"},
        }
    )

    assert suggestion.title == "行政院工作报告"


def test_parse_book_metadata_suggestion_accepts_json_string() -> None:
    payload = json.dumps(
        {
            "title": "Demo Book",
            "type": {"value": "core", "confidence": 0.93, "evidence": "书名含通史"},
            "categories": [
                {"value": "财政史", "confidence": 0.96, "evidence": "内容讨论财政制度"},
            ],
            "summary": {"value": "A concise summary.", "confidence": 0.88, "evidence": "前言"},
        },
        ensure_ascii=False,
    )

    suggestion = parse_book_metadata_suggestion(payload)

    assert suggestion.title == "Demo Book"
    assert suggestion.type is not None
    assert suggestion.type.value == "core"
    assert suggestion.categories[0].value == "财政史"


def test_parse_book_metadata_suggestion_coerces_scalar_fields() -> None:
    suggestion = parse_book_metadata_suggestion(
        {
            "title": "民国财政史",
            "author": "杨荫溥",
            "publisher": "商务印书馆",
            "type": "specialized",
            "folder": "财政史/民国",
            "categories": ["中国财政史", "民国史"],
            "eras": ["1912-1949"],
            "regions": ["中国"],
            "keywords": ["民国财政", "税收制度"],
            "summary": "讨论民国时期财政制度与收支变化。",
            "ocr_quality": 0.8,
        }
    )

    assert suggestion.author is not None
    assert suggestion.author.value == "杨荫溥"
    assert suggestion.publisher is not None
    assert suggestion.publisher.value == "商务印书馆"
    assert suggestion.type is not None
    assert suggestion.type.value == "specialized"
    assert suggestion.folder is not None
    assert suggestion.folder.value == "财政史/民国"
    assert [field.value for field in suggestion.categories] == ["中国财政史", "民国史"]
    assert [field.value for field in suggestion.keywords] == ["民国财政", "税收制度"]
    assert suggestion.summary is not None
    assert suggestion.summary.value == "讨论民国时期财政制度与收支变化。"
    assert suggestion.ocr_quality is not None
    assert suggestion.ocr_quality.value == "0.8"


def test_parse_book_metadata_suggestion_ignores_mapping_with_null_value() -> None:
    suggestion = parse_book_metadata_suggestion(
        {
            "title": "户部奏稿第9册",
            "author": {"value": None, "confidence": 0.2, "evidence": "unknown"},
            "publisher": {"value": "", "confidence": 0.1, "evidence": "unknown"},
            "summary": {"value": "", "confidence": 0.2, "evidence": "unknown"},
            "type": {"value": "specialized", "confidence": 0.8, "evidence": "奏稿"},
        }
    )

    assert suggestion.author is None
    assert suggestion.publisher is None
    assert suggestion.summary is None
    assert suggestion.type is not None
    assert suggestion.type.value == "specialized"


def test_parse_book_metadata_suggestion_filters_null_items_from_arrays() -> None:
    suggestion = parse_book_metadata_suggestion(
        {
            "categories": [
                {"value": None, "confidence": 0.1, "evidence": "unknown"},
                {"value": "财政史", "confidence": 0.9, "evidence": "军饷"},
                {"value": "  ", "confidence": 0.1, "evidence": "unknown"},
            ],
        }
    )

    assert [field.value for field in suggestion.categories] == ["财政史"]


def test_book_metadata_persistence_uses_dedicated_subdirectory(tmp_path) -> None:
    payload = _build_structured_payload()
    prompt_input = build_book_metadata_prompt_bundle(payload).prompt_input
    record = build_book_metadata_record(
        source_filename="demo.pdf",
        source_title="Demo Book",
        page_count=15,
        prompt_input=prompt_input,
        suggestion={
            "title": "Demo Book",
            "type": {"value": "specialized", "confidence": 0.8, "evidence": "示例"},
            "folder": {"value": "财政史", "confidence": 0.9, "evidence": "示例"},
        },
        model_name="test-model",
        generated_at="2026-03-22T00:00:00Z",
    )

    saved_path = save_book_metadata(tmp_path, "demo.pdf", record)

    assert saved_path.parent.name == ".book-metadata"
    assert list(tmp_path.glob("*.json")) == []
    loaded = load_book_metadata_for_source(tmp_path, "demo.pdf")
    assert loaded is not None
    assert loaded.source_filename == "demo.pdf"
    assert loaded.suggestion is not None
    assert loaded.suggestion.type is not None
    assert loaded.suggestion.type.value == "specialized"
    assert loaded.suggestion.folder is not None
    assert loaded.suggestion.folder.value == "财政史"


def test_resolve_book_folder_prefers_explicit_folder_then_first_tag() -> None:
    explicit = parse_book_metadata_suggestion(
        {
            "folder": "财政史/清代",
            "categories": ["制度史"],
        }
    )
    fallback = parse_book_metadata_suggestion(
        {
            "categories": ["制度史", "财政史"],
            "keywords": ["盐政"],
        }
    )

    assert resolve_book_folder(explicit) == "财政史/清代"
    assert resolve_book_folder(fallback) == "制度史"
    assert normalize_folder_path("  财政史 \\ 清代  ") == "财政史/清代"
