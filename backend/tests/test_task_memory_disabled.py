"""A disabled task-memory store must not contact embedding or vector services."""

from unittest.mock import Mock

import pytest

from src.community.knowledge_base import task_memory


def _upsert_memory():
    return task_memory.upsert_task_memory_record(
        title="一条鞭法",
        query="一条鞭法的主要内容是什么？",
        summary="一条鞭法将赋役项目合并征收，具体规定需结合地方史料核对。",
        task_level="subtask",
        thread_id="test-thread",
        user_id=None,
        task_id="test-task",
    )


@pytest.mark.parametrize("value", ["0", "false", "no", "off", " FALSE "])
def test_disabled_task_memory_skips_search_and_citation_injection(monkeypatch, value):
    monkeypatch.setenv("TASK_MEMORY_ENABLED", value)
    connect = Mock(side_effect=AssertionError("Disabled memory contacted external services"))
    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", connect)
    state = {"knowledge_citation_registry": [{"id": "1", "label": "Existing source"}]}

    assert task_memory.search_task_memory("一条鞭法") == []
    assert task_memory.search_and_prepare_task_memory(
        query="一条鞭法", title="明代赋役", target_state=state
    ) == []
    assert state == {"knowledge_citation_registry": [{"id": "1", "label": "Existing source"}]}
    connect.assert_not_called()


@pytest.mark.parametrize("value", ["0", "false", "no", "off", " FALSE "])
def test_disabled_task_memory_skips_persistence(monkeypatch, value):
    monkeypatch.setenv("TASK_MEMORY_ENABLED", value)
    connect = Mock(side_effect=AssertionError("Disabled memory contacted external services"))
    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", connect)

    assert _upsert_memory() is None
    connect.assert_not_called()


@pytest.mark.parametrize("value", [None, "true", "1", "yes"])
def test_enabled_task_memory_still_reaches_the_store(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TASK_MEMORY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TASK_MEMORY_ENABLED", value)
    connect = Mock(side_effect=RuntimeError("Test store unavailable"))
    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", connect)

    assert task_memory.search_task_memory("一条鞭法") == []
    assert _upsert_memory() is None
    assert connect.call_count == 2
