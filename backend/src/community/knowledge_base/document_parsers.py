"""Document parsing metadata helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.community.knowledge_base.structured_document import build_structured_document

PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}


def infer_parse_method(filename: str) -> tuple[str, bool]:
    """Infer the parser used for a given source file."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        return "local_text", True
    if suffix in PDF_EXTENSIONS | OFFICE_EXTENSIONS:
        return "ocr_pdf_mineru_grpc", True
    return "binary_only", False


def parse_local_text(file_path: Path, *, title: str, hints: dict[str, str] | None = None) -> dict[str, Any]:
    """Parse UTF-8 Markdown/TXT locally, without an OCR or model service."""
    if file_path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Local text parsing supports Markdown and TXT only")
    return build_structured_document(
        source_filename=file_path.name,
        title=title,
        text=file_path.read_text(encoding="utf-8-sig"),
        parser_name="local_text",
        hints=hints,
    )
