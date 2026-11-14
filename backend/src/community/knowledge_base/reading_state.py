from __future__ import annotations

from collections.abc import Mapping
from typing import Any

READING_SET_DOC_IDS_KEY = "knowledge_reading_set_doc_ids"
READING_SET_TITLES_KEY = "knowledge_reading_set_titles"
COVERED_DOC_IDS_KEY = "knowledge_covered_doc_ids"
READING_SET_QUERY_KEY = "knowledge_reading_set_query"
READING_SET_HUMAN_INDEX_KEY = "knowledge_reading_set_human_index"
SUBTASK_FINAL_RESULT_KEY = "subtask_final_result"


def latest_human_index(messages: list[Any] | None) -> int:
    if not messages:
        return -1
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "type", None) == "human":
            return index
    return -1


def _normalize_doc_ids(doc_ids: object) -> list[str]:
    if not isinstance(doc_ids, list):
        return []
    return [str(item).strip() for item in doc_ids if str(item).strip()]


def _normalize_titles(titles: object) -> dict[str, str]:
    if not isinstance(titles, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in titles.items():
        doc_id = str(key).strip()
        title = str(value).strip()
        if doc_id and title:
            normalized[doc_id] = title
    return normalized


def get_active_reading_state(state: Mapping[str, Any] | None) -> tuple[list[str], dict[str, str], list[str], str | None]:
    if not state:
        return [], {}, [], None

    reading_human_index = state.get(READING_SET_HUMAN_INDEX_KEY)
    if reading_human_index != latest_human_index(state.get("messages")):
        return [], {}, [], None

    reading_set = _normalize_doc_ids(state.get(READING_SET_DOC_IDS_KEY))
    covered = _normalize_doc_ids(state.get(COVERED_DOC_IDS_KEY))
    titles = _normalize_titles(state.get(READING_SET_TITLES_KEY))
    query = str(state.get(READING_SET_QUERY_KEY) or "").strip() or None
    return reading_set, titles, covered, query


def get_uncovered_doc_ids(state: Mapping[str, Any] | None) -> list[str]:
    reading_set, _titles, covered, _query = get_active_reading_state(state)
    if not reading_set:
        return []
    covered_set = set(covered)
    return [doc_id for doc_id in reading_set if doc_id not in covered_set]
