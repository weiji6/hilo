"""Runtime helpers for AI-generated book metadata."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import sleep
from typing import Any, Mapping

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.community.knowledge_base.book_metadata import (
    BookMetadataRecord,
    build_book_metadata_prompt_bundle,
    build_book_metadata_record,
    get_book_metadata_dir,
    load_book_metadata,
    parse_book_metadata_suggestion,
    resolve_book_folder,
    save_book_metadata,
)
from src.community.knowledge_base.folder_registry import list_folder_paths, render_folder_tree
from src.config.knowledge_base_config import BookMetadataConfig

logger = logging.getLogger(__name__)
BOOK_METADATA_RETRY_ATTEMPTS = 3
BOOK_METADATA_RETRY_DELAY_SECONDS = 1.0


def _strip_markdown_fences(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith("```"):
        return normalized

    lines = normalized.splitlines()
    if len(lines) <= 2:
        return normalized.strip("`")
    if lines[-1].strip() == "```":
        lines = lines[1:-1]
    else:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first top-level JSON object from mixed model output."""
    normalized = _strip_markdown_fences(text)
    if not normalized:
        return None
    if normalized.startswith("{"):
        return normalized

    start = normalized.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(normalized)):
        char = normalized[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return normalized[start : index + 1]

    return None


def _extract_response_text(response: Any) -> str:
    """Extract the best candidate JSON text from an AI response object."""
    content = str(getattr(response, "content", "") or "").strip()
    content_candidate = _extract_first_json_object(content) or _strip_markdown_fences(content)
    if content_candidate:
        return content_candidate

    reasoning = ""
    if isinstance(response, AIMessage):
        reasoning = str(
            response.additional_kwargs.get("reasoning_content")
            or response.additional_kwargs.get("reasoning")
            or ""
        ).strip()

    reasoning_candidate = _extract_first_json_object(reasoning)
    if reasoning_candidate:
        logger.warning("Book metadata model returned JSON in reasoning instead of content")
        return reasoning_candidate

    if reasoning:
        excerpt = reasoning[:400].replace("\n", " ")
        raise ValueError(
            "Book metadata model returned empty content and reasoning-only analysis "
            f"(reasoning starts with: {excerpt!r})"
        )
    raise ValueError("Book metadata model returned empty content")


def _is_retryable_metadata_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.HTTPError, json.JSONDecodeError)):
        return True
    if isinstance(exc, ValueError) and "empty content" in str(exc).lower():
        return True
    return exc.__class__.__name__ in {"APIConnectionError", "APITimeoutError", "RateLimitError"}


def build_existing_folder_tree(
    output_dir: Path,
    *,
    exclude_source_filename: str | None = None,
    folder_registry_path: Path | None = None,
) -> str | None:
    """Render the current logical folder layout as a simple file tree."""
    metadata_dir = get_book_metadata_dir(output_dir)
    file_entries: list[tuple[str | None, str]] = []

    if metadata_dir.exists():
        for path in sorted(metadata_dir.glob("*.book-metadata.json")):
            record = load_book_metadata(path)
            if record is None or record.source_filename == exclude_source_filename:
                continue
            file_entries.append((resolve_book_folder(record.suggestion), record.source_filename))

    return render_folder_tree(
        folder_paths=list_folder_paths(folder_registry_path) if folder_registry_path else [],
        file_entries=file_entries,
    )


def generate_book_metadata_record(
    *,
    structured_payload: Mapping[str, Any],
    source_filename: str,
    title: str,
    output_dir: Path,
    config: BookMetadataConfig,
) -> tuple[BookMetadataRecord, Path]:
    """Run an AI metadata pass and persist the resulting record."""
    from src.models import create_chat_model

    registry_path = output_dir / ".folders.json"

    prompt_bundle = build_book_metadata_prompt_bundle(
        structured_payload,
        source_filename=source_filename,
        title=title,
        front_page_limit=config.front_page_limit,
        body_sample_count=config.body_sample_count,
        max_excerpt_chars=config.max_excerpt_chars,
        existing_folder_tree=build_existing_folder_tree(
            output_dir,
            exclude_source_filename=source_filename,
            folder_registry_path=registry_path,
        ),
    )

    model = create_chat_model(
        name=config.model_name,
        thinking_enabled=False,
    )
    messages = [
        SystemMessage(content=prompt_bundle.system_prompt),
        HumanMessage(content=prompt_bundle.user_prompt),
    ]
    suggestion = None
    last_error: Exception | None = None
    for attempt in range(1, BOOK_METADATA_RETRY_ATTEMPTS + 1):
        # ── Call model ────────────────────────────────────────────────────────
        try:
            response = model.invoke(messages)
            response_text = _extract_response_text(response)
            suggestion = parse_book_metadata_suggestion(response_text)
        except Exception as exc:
            last_error = exc
            if not _is_retryable_metadata_error(exc) or attempt >= BOOK_METADATA_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "Book metadata generation transient failure for %s on attempt %s/%s: %s",
                source_filename, attempt, BOOK_METADATA_RETRY_ATTEMPTS, exc,
            )
            sleep(BOOK_METADATA_RETRY_DELAY_SECONDS)
            continue

        # New folder paths are intentional — the caller registers them after sync.
        break

    if suggestion is None:
        raise ValueError(f"Book metadata generation failed for {source_filename}: {last_error}")

    record = build_book_metadata_record(
        source_filename=source_filename,
        source_title=title,
        page_count=prompt_bundle.prompt_input.page_count,
        prompt_input=prompt_bundle.prompt_input,
        suggestion=suggestion,
        model_name=config.model_name,
    )
    return record, save_book_metadata(output_dir, source_filename, record)


def maybe_generate_book_metadata(
    *,
    structured_payload: Mapping[str, Any],
    source_filename: str,
    title: str,
    output_dir: Path,
    config: BookMetadataConfig | None,
) -> Path | None:
    """Best-effort metadata generation that never raises to callers."""
    if config is None or not config.enabled:
        return None

    try:
        _, output_path = generate_book_metadata_record(
            structured_payload=structured_payload,
            source_filename=source_filename,
            title=title,
            output_dir=output_dir,
            config=config,
        )
        return output_path
    except json.JSONDecodeError as exc:
        logger.warning("Book metadata generation returned invalid JSON for %s: %s", source_filename, exc)
    except Exception as exc:
        logger.warning("Book metadata generation failed for %s: %s", source_filename, exc)
    return None
