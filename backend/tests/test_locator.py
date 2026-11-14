from pathlib import Path

from src.community.knowledge_base import locator as locator_module


def test_filename_match_score_prefers_whitespace_normalized_exact_match() -> None:
    exact_score = locator_module._filename_match_score("光绪朝 东华录.pdf", "光绪朝东华录.pdf")
    fuzzy_score = locator_module._filename_match_score("光续朝东华录.pdf", "光绪朝东华录.pdf")

    assert exact_score > fuzzy_score
    assert exact_score >= 9000


def test_locate_document_uses_best_fuzzy_filename_match_for_user_records(monkeypatch) -> None:
    payload_map = {
        "a.json": {"title": "光绪朝东华录", "pages": [{"page_no": 1, "pdf_page_no": 1, "paragraphs": []}]},
        "b.json": {"title": "光绪朝上谕档", "pages": [{"page_no": 1, "pdf_page_no": 1, "paragraphs": []}]},
    }

    monkeypatch.setattr(
        locator_module,
        "list_user_records",
        lambda user_id: [
            {
                "id": "doc-a",
                "source_filename": "光绪朝东华录.pdf",
                "structured_path": "a.json",
                "display_title": "光绪朝东华录",
            },
            {
                "id": "doc-b",
                "source_filename": "光绪朝上谕档.pdf",
                "structured_path": "b.json",
                "display_title": "光绪朝上谕档",
            },
        ],
    )
    monkeypatch.setattr(locator_module, "load_structured_document", lambda path: payload_map.get(Path(path).name))

    document = locator_module.locate_document(
        thread_id=None,
        user_id="user-1",
        filename="光续朝 东华录.pdf",
    )

    assert document is not None
    assert document.filename == "光绪朝东华录.pdf"
    assert document.title == "光绪朝东华录"
