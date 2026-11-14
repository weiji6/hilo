"""Helpers for book-level metadata generation, prompting, and persistence.

This module is intentionally router-agnostic. It prepares structured OCR output
for an AI metadata pass, normalizes the expected response shape, and persists the
result to disk for later catalog integration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

BOOK_METADATA_SCHEMA_VERSION = 1
DEFAULT_FRONT_PAGE_LIMIT = 20
DEFAULT_BODY_SAMPLE_COUNT = 5
DEFAULT_MAX_EXCERPT_CHARS = 1200
BOOK_METADATA_FILENAME_SUFFIX = ".book-metadata.json"
BOOK_METADATA_SUBDIR = ".book-metadata"
BOOK_TYPES = {"core", "specialized", "reference", "unknown"}


class MetadataField(BaseModel):
    """Single metadata value with confidence and evidence."""

    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None

    model_config = ConfigDict(extra="ignore")


class BookMetadataSamplePage(BaseModel):
    """One sampled page excerpt selected for metadata generation."""

    page_no: int
    pdf_page_no: int | None = None
    book_page_no: int | None = None
    reasons: list[str] = Field(default_factory=list)
    text: str

    model_config = ConfigDict(extra="ignore")


class BookMetadataPromptInput(BaseModel):
    """Structured input passed to the metadata-generation AI."""

    source_filename: str
    title: str
    page_count: int
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS
    selected_pages: list[BookMetadataSamplePage] = Field(default_factory=list)
    selection_notes: list[str] = Field(default_factory=list)
    existing_folder_tree: str | None = None

    model_config = ConfigDict(extra="ignore")


class BookMetadataSuggestion(BaseModel):
    """Expected AI output for routing and retrieval metadata."""

    title: str | None = None
    author: MetadataField | None = None
    publisher: MetadataField | None = None
    type: MetadataField | None = None
    folder: MetadataField | None = None
    categories: list[MetadataField] = Field(default_factory=list)
    eras: list[MetadataField] = Field(default_factory=list)
    regions: list[MetadataField] = Field(default_factory=list)
    keywords: list[MetadataField] = Field(default_factory=list)
    summary: MetadataField | None = None
    ocr_quality: MetadataField | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="ignore")


class BookMetadataRecord(BaseModel):
    """Persisted analysis record containing prompt input and AI output."""

    schema_version: int = BOOK_METADATA_SCHEMA_VERSION
    source_filename: str
    source_title: str
    page_count: int
    prompt_input: BookMetadataPromptInput
    suggestion: BookMetadataSuggestion | None = None
    model_name: str | None = None
    generated_at: str | None = None

    model_config = ConfigDict(extra="ignore", protected_namespaces=())


class BookMetadataPromptBundle(BaseModel):
    """Prompt text and structured input for downstream AI execution."""

    system_prompt: str
    user_prompt: str
    prompt_input: BookMetadataPromptInput

    model_config = ConfigDict(extra="ignore")


def _coerce_metadata_field(value: Any) -> MetadataField | None:
    if value is None:
        return None
    if isinstance(value, MetadataField):
        return value
    if isinstance(value, Mapping):
        raw_value = value.get("value")
        normalized_value = str(raw_value).strip() if raw_value is not None else ""
        if not normalized_value:
            return None
        payload = dict(value)
        payload["value"] = normalized_value
        payload.setdefault("confidence", 0.0)
        return MetadataField.model_validate(payload)

    normalized = str(value).strip()
    if not normalized:
        return None
    return MetadataField(
        value=normalized,
        confidence=0.5,
        evidence="coerced_from_scalar",
    )


def _coerce_book_type(value: Any) -> MetadataField | None:
    field = _coerce_metadata_field(value)
    if field is None:
        return None
    normalized = field.value.strip().lower()
    if normalized not in BOOK_TYPES:
        normalized = "unknown"
    field.value = normalized
    return field


def normalize_folder_path(value: Any) -> str | None:
    """Normalize a logical knowledge-folder path into slash-separated segments."""
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return None

    segments: list[str] = []
    for segment in raw.split("/"):
        normalized = " ".join(segment.split()).strip()
        if not normalized or normalized in {".", ".."}:
            continue
        segments.append(normalized)

    return "/".join(segments) or None


def _coerce_folder_field(value: Any) -> MetadataField | None:
    field = _coerce_metadata_field(value)
    if field is None:
        return None
    normalized = normalize_folder_path(field.value)
    if not normalized:
        return None
    field.value = normalized
    return field


def _coerce_metadata_fields(values: Any) -> list[MetadataField]:
    if values is None:
        return []
    if isinstance(values, list):
        coerced = [_coerce_metadata_field(item) for item in values]
        return [item for item in coerced if item is not None]

    item = _coerce_metadata_field(values)
    return [item] if item is not None else []


def _normalize_book_metadata_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    # title must be a plain string; coerce dict/non-string values gracefully.
    raw_title = payload.get("title")
    if isinstance(raw_title, Mapping):
        raw_title = raw_title.get("value") or raw_title.get("text") or raw_title.get("content") or ""
    normalized["title"] = str(raw_title).strip() if raw_title else None
    normalized["author"] = _coerce_metadata_field(payload.get("author"))
    normalized["publisher"] = _coerce_metadata_field(payload.get("publisher"))
    normalized["type"] = _coerce_book_type(payload.get("type"))
    normalized["folder"] = _coerce_folder_field(payload.get("folder"))
    normalized["categories"] = _coerce_metadata_fields(payload.get("categories"))
    normalized["eras"] = _coerce_metadata_fields(payload.get("eras"))
    normalized["regions"] = _coerce_metadata_fields(payload.get("regions"))
    normalized["keywords"] = _coerce_metadata_fields(payload.get("keywords"))
    normalized["summary"] = _coerce_metadata_field(payload.get("summary"))
    normalized["ocr_quality"] = _coerce_metadata_field(payload.get("ocr_quality"))
    return normalized


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 3)].rstrip() + "..."


def resolve_book_folder(suggestion: BookMetadataSuggestion | None) -> str | None:
    """Resolve a logical folder path for a book suggestion.

    Preference order:
    1. Explicit `folder`
    2. First category / era / region / keyword
    """
    if suggestion is None:
        return None

    explicit_folder = _coerce_folder_field(suggestion.folder)
    if explicit_folder is not None:
        return explicit_folder.value

    for fields in (suggestion.categories, suggestion.eras, suggestion.regions, suggestion.keywords):
        for field in fields:
            normalized = normalize_folder_path(_coerce_metadata_field(field).value if field else None)
            if normalized:
                return normalized
    return None


def _page_no(page: Mapping[str, Any], fallback: int) -> int:
    for key in ("page_no", "pdf_page_no", "book_page_no"):
        value = page.get(key)
        try:
            if value is not None:
                parsed = int(value)
                if parsed > 0:
                    return parsed
        except (TypeError, ValueError):
            continue
    return fallback


def _page_text(page: Mapping[str, Any]) -> str:
    return _normalize_text(str(page.get("text") or ""))


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _looks_like_toc(page_text: str) -> bool:
    if not page_text:
        return False

    normalized = _normalize_text(page_text).lower()
    if any(keyword in normalized for keyword in ("目录", "contents", "table of contents")):
        return True

    lines = _split_lines(page_text)
    if len(lines) < 3:
        return False

    dotted_lines = 0
    numbered_lines = 0
    for line in lines:
        if "....." in line or "……" in line:
            dotted_lines += 1
        if line and line[-1].isdigit():
            numbered_lines += 1

    if dotted_lines >= 2:
        return True
    return numbered_lines >= 3


def _evenly_spaced_indices(total: int, count: int) -> list[int]:
    if total <= 0 or count <= 0:
        return []
    if count >= total:
        return list(range(total))

    step = total / (count + 1)
    indices: list[int] = []
    for index in range(1, count + 1):
        candidate = int(round(step * index)) - 1
        candidate = max(0, min(total - 1, candidate))
        if candidate not in indices:
            indices.append(candidate)
    return indices


def _dedupe_reasons(existing: list[str], new_reasons: list[str]) -> list[str]:
    seen = set(existing)
    merged = list(existing)
    for reason in new_reasons:
        if reason in seen:
            continue
        seen.add(reason)
        merged.append(reason)
    return merged


def extract_book_metadata_pages(
    structured_payload: Mapping[str, Any],
    *,
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT,
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
) -> list[BookMetadataSamplePage]:
    """Select only the first N pages for metadata generation."""
    pages = list(structured_payload.get("pages") or [])
    if not pages:
        return []

    front_count = min(front_page_limit, len(pages))
    selected_pages: list[BookMetadataSamplePage] = []

    for index, page in enumerate(pages[:front_count], start=1):
        page_no = _page_no(page, index)
        text = _truncate_text(_page_text(page), max_excerpt_chars)
        selected_pages.append(
            BookMetadataSamplePage(
                page_no=page_no,
                pdf_page_no=page.get("pdf_page_no"),
                book_page_no=page.get("book_page_no"),
                reasons=["front_page"],
                text=text,
            )
        )

    return selected_pages


def build_book_metadata_prompt_input(
    structured_payload: Mapping[str, Any],
    *,
    source_filename: str | None = None,
    title: str | None = None,
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT,
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
    existing_folder_tree: str | None = None,
) -> BookMetadataPromptInput:
    """Convert structured OCR output into a compact AI prompt input."""
    selected_pages = extract_book_metadata_pages(
        structured_payload,
        front_page_limit=front_page_limit,
        body_sample_count=body_sample_count,
        max_excerpt_chars=max_excerpt_chars,
    )

    inferred_source_filename = source_filename or str(structured_payload.get("source_filename") or "unknown")
    inferred_title = title or str(structured_payload.get("title") or inferred_source_filename)
    page_count = len(list(structured_payload.get("pages") or []))
    notes = [
        f"Selected the first {front_page_limit} pages as the front-page window.",
        "No TOC detection or body-page sampling is applied.",
    ]

    return BookMetadataPromptInput(
        source_filename=inferred_source_filename,
        title=inferred_title,
        page_count=page_count,
        front_page_limit=front_page_limit,
        body_sample_count=body_sample_count,
        max_excerpt_chars=max_excerpt_chars,
        selected_pages=selected_pages,
        selection_notes=notes,
        existing_folder_tree=existing_folder_tree.strip() if existing_folder_tree else None,
    )


def build_book_metadata_system_prompt() -> str:
    """Return the system prompt for a metadata classification run."""
    return (
        "You are classifying a book for retrieval routing.\n"
        "Use only the supplied excerpts and their page numbers.\n"
        "Do not invent facts, and do not use outside knowledge to fill gaps.\n"
        "The field `type` is only for retrieval routing and must be one of: core, specialized, reference, unknown.\n"
        "The field `folder` is the logical knowledge-folder path for this book, using `/` between levels.\n"
        "Prefer reusing an existing folder from the supplied folder tree when one clearly fits.\n"
        "If no existing folder fits, create a short new folder path based on the book's primary subject.\n"
        "For older books, the folder should usually align with the first/highest-priority tag rather than the retrieval `type`.\n"
        "`core` means a general/synthetic history work such as 通史, 全史, 概论, 总论, or a broad dynastic overview.\n"
        "A domain-wide history such as《中国财政通史》is still `core`; do not mark it `specialized` merely because it focuses on one domain.\n"
        "`specialized` is for topic-focused or case-focused studies such as 专题研究, 制度史, 个案研究, 区域研究, 档案/史料研究.\n"
        "`reference` is for reference works such as 年表, 辞典, 索引, 汇编, 手册, 工具书.\n"
        "`categories` are subject/domain labels such as 财政史, 制度史, 经济史, 清史, not retrieval types.\n"
        "`eras` are time ranges or dynastic periods only. `regions` are places only. `keywords` are concrete research topics only.\n"
        "Prefer precision over recall: if uncertain, leave arrays empty instead of guessing.\n"
        "Keep lists short: categories/eras/regions <= 5 items each, keywords <= 8 items.\n"
        "Prefer the supplied title unless the excerpts clearly show a better normalized title.\n"
        "Each populated field should include short evidence copied or paraphrased from the excerpts.\n"
        "Do not use author-role words like 著, 编, 译 as `type`.\n"
        "The field `author` is the primary author(s) of the book as they appear on the cover or front matter.\n"
        "The field `publisher` is the publishing house (出版社) of the book as it appears on the cover or copyright page.\n"
        "Return valid JSON that matches the expected book-metadata schema.\n"
        "Return raw JSON only. Do not wrap it in markdown fences. Do not add any explanation before or after the JSON.\n"
        "If a field is unknown, use null, an empty array, or 'unknown' as appropriate.\n"
        "Keep confidence scores between 0 and 1.\n"
        "Use exactly this top-level shape:\n"
        "{\n"
        '  "title": "string or null",\n'
        '  "author": {"value": "string", "confidence": 0.0, "evidence": "string"} or null,\n'
        '  "publisher": {"value": "string", "confidence": 0.0, "evidence": "string"} or null,\n'
        '  "type": {"value": "core|specialized|reference|unknown", "confidence": 0.0, "evidence": "string"} or null,\n'
        '  "folder": {"value": "string", "confidence": 0.0, "evidence": "string"} or null,\n'
        '  "categories": [{"value": "string", "confidence": 0.0, "evidence": "string"}],\n'
        '  "eras": [{"value": "string", "confidence": 0.0, "evidence": "string"}],\n'
        '  "regions": [{"value": "string", "confidence": 0.0, "evidence": "string"}],\n'
        '  "keywords": [{"value": "string", "confidence": 0.0, "evidence": "string"}],\n'
        '  "summary": {"value": "string", "confidence": 0.0, "evidence": "string"} or null,\n'
        '  "ocr_quality": {"value": "high|medium|low", "confidence": 0.0, "evidence": "string"} or null,\n'
        '  "notes": "string or null"\n'
        "}\n"
    )


def render_book_metadata_user_prompt(prompt_input: BookMetadataPromptInput) -> str:
    """Render a human-readable prompt for an external model."""
    lines = [
        f"Title: {prompt_input.title}",
    ]
    for page in prompt_input.selected_pages:
        lines.extend(
            [
                "",
                f"### Page {page.page_no}",
                page.text or "",
            ]
        )
    if prompt_input.existing_folder_tree:
        lines.extend(
            [
                "",
                "### Existing Folder Tree",
                prompt_input.existing_folder_tree,
            ]
        )
    return "\n".join(lines)


def build_book_metadata_prompt_bundle(
    structured_payload: Mapping[str, Any],
    *,
    source_filename: str | None = None,
    title: str | None = None,
    front_page_limit: int = DEFAULT_FRONT_PAGE_LIMIT,
    body_sample_count: int = DEFAULT_BODY_SAMPLE_COUNT,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
    existing_folder_tree: str | None = None,
) -> BookMetadataPromptBundle:
    """Build the system/user prompt pair and structured input for an AI pass."""
    prompt_input = build_book_metadata_prompt_input(
        structured_payload,
        source_filename=source_filename,
        title=title,
        front_page_limit=front_page_limit,
        body_sample_count=body_sample_count,
        max_excerpt_chars=max_excerpt_chars,
        existing_folder_tree=existing_folder_tree,
    )
    return BookMetadataPromptBundle(
        system_prompt=build_book_metadata_system_prompt(),
        user_prompt=render_book_metadata_user_prompt(prompt_input),
        prompt_input=prompt_input,
    )


def parse_book_metadata_suggestion(payload: Mapping[str, Any] | str) -> BookMetadataSuggestion:
    """Parse and normalize a metadata response from an AI model."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, Mapping):
        raise TypeError("Book metadata payload must be a mapping or JSON string")
    return BookMetadataSuggestion.model_validate(_normalize_book_metadata_payload(payload))


def build_book_metadata_record(
    *,
    source_filename: str,
    source_title: str,
    page_count: int,
    prompt_input: BookMetadataPromptInput,
    suggestion: BookMetadataSuggestion | Mapping[str, Any] | str | None = None,
    model_name: str | None = None,
    generated_at: str | None = None,
) -> BookMetadataRecord:
    """Build a persisted analysis record from a prompt input and AI output."""
    parsed_suggestion: BookMetadataSuggestion | None = None
    if suggestion is not None:
        parsed_suggestion = (
            suggestion
            if isinstance(suggestion, BookMetadataSuggestion)
            else parse_book_metadata_suggestion(suggestion)
        )

    return BookMetadataRecord(
        source_filename=source_filename,
        source_title=source_title,
        page_count=page_count,
        prompt_input=prompt_input,
        suggestion=parsed_suggestion,
        model_name=model_name,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )


def derive_book_metadata_filename(source_filename: str) -> str:
    """Derive a stable metadata filename from the source filename."""
    return f"{source_filename}{BOOK_METADATA_FILENAME_SUFFIX}"


def get_book_metadata_dir(directory: Path) -> Path:
    """Return the dedicated subdirectory used for book-metadata sidecars."""
    return directory / BOOK_METADATA_SUBDIR


def save_book_metadata(
    directory: Path,
    source_filename: str,
    record: BookMetadataRecord | Mapping[str, Any],
) -> Path:
    """Persist a metadata record as JSON."""
    metadata_dir = get_book_metadata_dir(directory)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    path = metadata_dir / derive_book_metadata_filename(source_filename)
    payload = (
        record.model_dump(mode="json")
        if isinstance(record, BookMetadataRecord)
        else BookMetadataRecord.model_validate(record).model_dump(mode="json")
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_book_metadata(path: Path) -> BookMetadataRecord | None:
    """Load a persisted metadata record from disk."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return BookMetadataRecord.model_validate(payload)
    except Exception:
        return None


def load_book_metadata_for_source(directory: Path, source_filename: str) -> BookMetadataRecord | None:
    """Load a persisted metadata record for a given source filename."""
    return load_book_metadata(get_book_metadata_dir(directory) / derive_book_metadata_filename(source_filename))
