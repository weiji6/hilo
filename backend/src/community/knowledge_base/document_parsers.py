"""Document parsing metadata helpers."""

from __future__ import annotations

from pathlib import Path

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
    if suffix in {".md", ".txt"} | PDF_EXTENSIONS | OFFICE_EXTENSIONS:
        return "ocr_pdf_mineru_grpc", True
    return "binary_only", False
