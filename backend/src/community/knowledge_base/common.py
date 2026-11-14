"""Shared helpers for knowledge-base indexing and retrieval."""

import os
import re
from pathlib import Path


def sanitize_collection_suffix(value: str) -> str:
    """Sanitize arbitrary thread IDs for use in collection names."""
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return sanitized or "default"


def get_thread_collection_name(base_collection_name: str, thread_id: str) -> str:
    """Build the per-thread collection name for uploaded docs."""
    return f"{base_collection_name}__thread__{sanitize_collection_suffix(thread_id)}"


def get_user_collection_name(base_collection_name: str, user_id: str) -> str:
    """Build the per-user collection name for personal knowledge docs."""
    return f"{base_collection_name}__user__{sanitize_collection_suffix(user_id)}"


def resolve_project_path(path_value: str) -> Path:
    """Resolve a project-relative path from either repo root or backend cwd."""
    path = Path(path_value)
    if path.is_absolute():
        return path

    cwd = Path(os.getcwd())
    project_root = cwd.parent if cwd.name == "backend" else cwd
    if not (project_root / "backend").exists():
        project_root = Path(__file__).resolve().parents[4]
    return (project_root / path).resolve()


def derive_global_doc_id(docs_root: Path, source_path: Path) -> str:
    """Build a stable doc_id for repo knowledge docs."""
    try:
        return source_path.resolve().relative_to(docs_root.resolve()).as_posix()
    except Exception:
        return source_path.name


def derive_thread_doc_id(source_path: Path) -> str:
    """Build a stable doc_id for thread uploads."""
    return source_path.name


def derive_user_doc_id(record_id: str) -> str:
    """Build a stable doc_id for user knowledge records."""
    return record_id


def extract_title_from_text(text: str, fallback: str) -> str:
    """Extract a human-readable title from markdown/text content."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
        return stripped[:120]
    return fallback


def normalize_search_text(text: str) -> str:
    """Normalize text for simple lexical matching."""
    normalized = text.lower().replace("_", " ").replace("-", " ").replace("/", " ")
    normalized = re.sub(r"[()（）【】\[\]·:：,，.。]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def tokenize_search_text(text: str) -> list[str]:
    """Tokenize normalized text into lightweight search terms.

    For Chinese text, include overlapping bigrams/trigrams so lexical retrieval
    is not limited to whitespace-separated tokens.
    """
    normalized = normalize_search_text(text)
    if not normalized:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for segment in [token for token in normalized.split(" ") if token]:
        if segment not in seen:
            tokens.append(segment)
            seen.add(segment)

        if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            for n in (2, 3):
                if len(segment) < n:
                    continue
                for index in range(len(segment) - n + 1):
                    gram = segment[index : index + n]
                    if gram not in seen:
                        tokens.append(gram)
                        seen.add(gram)
    return tokens
