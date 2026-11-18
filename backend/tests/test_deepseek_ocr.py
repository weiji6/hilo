from src.community.knowledge_base.deepseek_ocr import (
    build_structured_document_from_deepseek_response,
)
from src.community.knowledge_base.document_parsers import get_configured_ocr_parse_method
from src.config.knowledge_base_config import (
    DeepSeekOcrConfig,
    KnowledgeBaseConfig,
    load_knowledge_base_config_from_dict,
)


def test_deepseek_response_preserves_pages_and_cleans_layout_markers() -> None:
    response = {
        "id": "ocr-test",
        "purpose": "text_recognition",
        "page_count": 2,
        "pages": [
            {
                "index": 0,
                "text": "<｜ref｜>标题<｜/ref｜><｜box｜>[[10, 20, 900, 80]]<｜/box｜>\n\n第一页正文",
                "finish_reason": "stop",
            },
            {"index": 1, "text": "第二页正文", "finish_reason": "length"},
        ],
        "usage": {"total_tokens": 42},
    }

    payload = build_structured_document_from_deepseek_response(
        response,
        source_filename="demo.pdf",
        title="Demo",
        parser_name="ocr_deepseek",
    )

    assert payload["provider"] == "deepseek_ocr"
    assert payload["pages"][0]["text"] == "标题\n\n第一页正文"
    assert payload["pages"][0]["pdf_page_no"] == 1
    assert payload["pages"][1]["pdf_page_no"] == 2
    assert payload["pages"][1]["ocr_finish_reason"] == "length"
    assert payload["provider_result_meta"]["id"] == "ocr-test"


def test_deepseek_ocr_is_preferred_when_enabled() -> None:
    load_knowledge_base_config_from_dict(
        {
            "enabled": True,
            "deepseek_ocr": {"enabled": True},
            "mineru_api": {"enabled": True, "api_token": "legacy"},
        }
    )

    assert get_configured_ocr_parse_method() == "ocr_deepseek"
    assert get_configured_ocr_parse_method("document.pdf") == "ocr_deepseek"
    assert get_configured_ocr_parse_method("workbook.xlsx") == "ocr_pdf_mineru_api"
    load_knowledge_base_config_from_dict({})


def test_deepseek_ocr_config_defaults() -> None:
    config = DeepSeekOcrConfig()
    assert config.base_url == "https://api.deepseek.com"
    assert config.purpose == "text_recognition"
    assert KnowledgeBaseConfig().deepseek_ocr is None
