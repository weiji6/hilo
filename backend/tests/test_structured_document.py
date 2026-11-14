from src.community.knowledge_base.structured_document import build_structured_document


def test_build_structured_document_resets_paragraph_number_per_page() -> None:
    payload = build_structured_document(
        source_filename="demo.pdf",
        title="Demo",
        text="第一页第一段\n\n第一页第二段\f第二页第一段\n\n第二页第二段",
        parser_name="ocr_pdf_local",
        hints=None,
    )

    first_page, second_page = payload["pages"]
    assert first_page["paragraphs"][0]["paragraph_no"] == 1
    assert first_page["paragraphs"][1]["paragraph_no"] == 2
    assert second_page["paragraphs"][0]["paragraph_no"] == 1
    assert second_page["paragraphs"][1]["paragraph_no"] == 2
    assert second_page["paragraphs"][0]["paragraph_no_in_doc"] == 3
    assert second_page["paragraphs"][1]["paragraph_no_in_doc"] == 4


def test_build_structured_document_maps_book_page_numbers_from_hints() -> None:
    payload = build_structured_document(
        source_filename="demo.pdf",
        title="Demo",
        text="封面\f目录\f正文一\f正文二",
        parser_name="ocr_pdf_local",
        hints={
            "book_page_start_pdf_page": "3",
            "book_page_start_value": "1",
        },
    )

    assert payload["pages"][0]["pdf_page_no"] == 1
    assert payload["pages"][0]["book_page_no"] is None
    assert payload["pages"][0]["page_no"] == 1
    assert payload["pages"][0]["page_number_source"] == "pdf"

    assert payload["pages"][2]["pdf_page_no"] == 3
    assert payload["pages"][2]["book_page_no"] == 1
    assert payload["pages"][2]["page_no"] == 1
    assert payload["pages"][2]["page_number_source"] == "book"

    assert payload["pages"][3]["pdf_page_no"] == 4
    assert payload["pages"][3]["book_page_no"] == 2
    assert payload["pages"][3]["page_no"] == 2
