from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares import task_memory_middleware  # noqa: E402
from src.community.knowledge_base import task_memory  # noqa: E402
from src.community.knowledge_base.citations import (  # noqa: E402
    KNOWLEDGE_CITATION_REGISTRY_KEY,
    build_citation_stable_key,
)


@pytest.fixture(autouse=True)
def _enable_task_memory(monkeypatch: Any) -> None:
    """Exercise enabled memory independently of local application settings."""
    monkeypatch.setenv("TASK_MEMORY_ENABLED", "true")


class _FakeVectorStore:
    added_documents: list[Any] = []
    added_ids: list[str] = []

    def __init__(self, **_kwargs: Any) -> None:
        pass

    def add_documents(self, documents: list[Any], ids: list[str]) -> None:
        self.added_documents.extend(documents)
        self.added_ids.extend(ids)


def _patch_vector_store(monkeypatch: Any) -> None:
    _FakeVectorStore.added_documents = []
    _FakeVectorStore.added_ids = []
    monkeypatch.setattr(
        task_memory,
        "_ensure_task_memory_collection",
        lambda: (object(), object(), "task_memory_test"),
    )
    monkeypatch.setattr(task_memory, "QdrantVectorStore", _FakeVectorStore)


def test_subtask_memory_embeds_result_not_delegated_prompt(monkeypatch: Any) -> None:
    _patch_vector_store(monkeypatch)

    delegated_prompt = (
        "你只负责执行下面这一项 todo，不要接管其他 todo。\n\n"
        "Todo: 梳理盛宣怀与轮船招商局的关系\n\n"
        "要求：先查历史结果，再查原始资料，输出结构化结果。"
    )

    record_id = task_memory.upsert_task_memory_record(
        title="梳理盛宣怀与轮船招商局的关系",
        query=delegated_prompt,
        summary="盛宣怀参与轮船招商局相关事务，并在制度和经营层面产生影响。",
        findings=["其作用需要结合招商局档案继续核对。"],
        citations=["[citation:1]"],
        open_questions=["缺少可核验页码。"],
        task_level="subtask",
        thread_id="thread-1",
        user_id="user-1",
        task_id="task-1",
        raw_result="完整子任务最终输出",
    )

    assert record_id is not None
    assert len(_FakeVectorStore.added_documents) == 1

    document = _FakeVectorStore.added_documents[0]
    assert "你只负责执行下面这一项 todo" not in document.page_content
    assert "要求：先查历史结果" not in document.page_content
    assert "查询:" not in document.page_content
    assert "摘要:" in document.page_content
    assert "盛宣怀参与轮船招商局相关事务" in document.page_content
    assert "关键发现:" in document.page_content
    assert "关键引文:" in document.page_content
    assert document.metadata["query"] == "梳理盛宣怀与轮船招商局的关系"


def test_main_task_memory_still_embeds_user_query(monkeypatch: Any) -> None:
    _patch_vector_store(monkeypatch)

    task_memory.upsert_task_memory_record(
        title="盛宣怀研究",
        query="盛宣怀如何参与近代企业建设？",
        summary="盛宣怀参与电报、轮船、铁路等事业。",
        findings=[],
        citations=[],
        open_questions=[],
        task_level="main",
        thread_id="thread-1",
        user_id="user-1",
        task_id="main:thread-1:0",
    )

    document = _FakeVectorStore.added_documents[0]
    assert "查询: 盛宣怀如何参与近代企业建设？" in document.page_content


def test_task_memory_upsert_skips_insufficient_evidence_result(monkeypatch: Any) -> None:
    _patch_vector_store(monkeypatch)

    record_id = task_memory.upsert_task_memory_record(
        title="张之洞铁路借款考证",
        query="张之洞铁路借款有哪些确证？",
        summary="【证据不足】目前没有找到可核验 citation，不能下结论。",
        findings=[],
        citations=[],
        open_questions=["缺少原始页码。"],
        task_level="subtask",
        thread_id="thread-1",
        user_id="user-1",
        task_id="task-1",
        raw_result="## 任务结果\n【证据不足】目前没有找到可核验 citation，不能下结论。",
    )

    assert record_id is None
    assert _FakeVectorStore.added_documents == []


def test_task_memory_upsert_persists_citation_registry_subset(monkeypatch: Any) -> None:
    _patch_vector_store(monkeypatch)

    first_label = "盛宣怀档案 第12页第2段"
    first_url = "/api/knowledge/docs/sheng.pdf?page_no=12&paragraph_no=2"
    second_label = "招商局档案 第8页第1段"
    second_url = "/api/knowledge/docs/merchants.pdf?page_no=8&paragraph_no=1"
    unused_label = "无关材料 第3页第1段"
    unused_url = "/api/knowledge/docs/unused.pdf?page_no=3&paragraph_no=1"

    record_id = task_memory.upsert_task_memory_record(
        title="盛宣怀与招商局关系",
        query="盛宣怀与招商局是什么关系？",
        summary="盛宣怀深度参与招商局经营调整。[citation:2]",
        findings=["档案显示其参与了具体制度安排。[citation:1]"],
        citations=["[citation:1]", "[citation:2]"],
        open_questions=["仍需核对更早时期的董事会记录。[citation:2]"],
        citation_registry=[
            {
                "id": "1",
                "label": first_label,
                "url": first_url,
                "stable_key": build_citation_stable_key(citation_label=first_label, citation_link=first_url),
            },
            {
                "id": "2",
                "label": second_label,
                "url": second_url,
                "stable_key": build_citation_stable_key(citation_label=second_label, citation_link=second_url),
            },
            {
                "id": "3",
                "label": unused_label,
                "url": unused_url,
                "stable_key": build_citation_stable_key(citation_label=unused_label, citation_link=unused_url),
            },
        ],
        task_level="subtask",
        thread_id="thread-1",
        user_id="user-1",
        task_id="task-1",
        raw_result="完整子任务最终输出",
    )

    assert record_id is not None
    assert len(_FakeVectorStore.added_documents) == 1
    document = _FakeVectorStore.added_documents[0]
    assert document.metadata["citation_registry"] == [
        {
            "id": "1",
            "label": first_label,
            "url": first_url,
            "stable_key": build_citation_stable_key(citation_label=first_label, citation_link=first_url),
        },
        {
            "id": "2",
            "label": second_label,
            "url": second_url,
            "stable_key": build_citation_stable_key(citation_label=second_label, citation_link=second_url),
        },
    ]


def test_prepare_task_memory_matches_for_injection_merges_registry_and_rewrites_markers() -> None:
    existing_label = "既有档案 第1页第1段"
    existing_url = "/api/knowledge/docs/existing.pdf?page_no=1&paragraph_no=1"
    new_label = "新增档案 第5页第2段"
    new_url = "/api/knowledge/docs/new.pdf?page_no=5&paragraph_no=2"
    target_state = {
        KNOWLEDGE_CITATION_REGISTRY_KEY: [
            {
                "id": "1",
                "label": existing_label,
                "url": existing_url,
                "stable_key": build_citation_stable_key(citation_label=existing_label, citation_link=existing_url),
            }
        ]
    }

    prepared = task_memory.prepare_task_memory_matches_for_injection(
        [
            {
                "metadata": {
                    "summary": "历史摘要[citation:1] 和既有事实[citation:2]",
                    "findings": ["发现[citation:1]", "旧证据[citation:2]"],
                    "citations": ["[citation:1]", "[citation:2]"],
                    "open_questions": ["待核对[citation:1]"],
                    "citation_registry": [
                        {
                            "id": "1",
                            "label": new_label,
                            "url": new_url,
                            "stable_key": build_citation_stable_key(citation_label=new_label, citation_link=new_url),
                        },
                        {
                            "id": "2",
                            "label": existing_label,
                            "url": existing_url,
                            "stable_key": build_citation_stable_key(citation_label=existing_label, citation_link=existing_url),
                        },
                    ],
                }
            }
        ],
        target_state=target_state,
    )

    metadata = prepared[0]["metadata"]
    assert metadata["summary"] == "历史摘要[citation:2] 和既有事实[citation:1]"
    assert metadata["findings"] == ["发现[citation:2]", "旧证据[citation:1]"]
    assert metadata["citations"] == ["[citation:2]", "[citation:1]"]
    assert metadata["open_questions"] == ["待核对[citation:2]"]
    assert target_state[KNOWLEDGE_CITATION_REGISTRY_KEY] == [
        {
            "id": "1",
            "label": existing_label,
            "url": existing_url,
            "stable_key": build_citation_stable_key(citation_label=existing_label, citation_link=existing_url),
        },
        {
            "id": "2",
            "label": new_label,
            "url": new_url,
            "stable_key": build_citation_stable_key(citation_label=new_label, citation_link=new_url),
        },
    ]


def test_search_and_prepare_task_memory_merges_citations_into_target_state(monkeypatch: Any) -> None:
    new_label = "新档案 第7页第3段"
    new_url = "/api/knowledge/docs/new.pdf?page_no=7&paragraph_no=3"
    target_state: dict[str, Any] = {}

    def _fake_search(query: str, *, title: str | None = None, top_k: int = 5, task_level: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "metadata": {
                    "summary": "历史摘要[citation:5]",
                    "findings": ["发现[citation:5]"],
                    "citations": ["[citation:5]"],
                    "open_questions": [],
                    "citation_registry": [
                        {
                            "id": "5",
                            "label": new_label,
                            "url": new_url,
                            "stable_key": build_citation_stable_key(citation_label=new_label, citation_link=new_url),
                        }
                    ],
                }
            }
        ]

    monkeypatch.setattr(task_memory, "search_task_memory", _fake_search)

    prepared = task_memory.search_and_prepare_task_memory(
        query="盛宣怀",
        title=None,
        target_state=target_state,
        top_k=3,
    )

    assert prepared[0]["metadata"]["summary"] == "历史摘要[citation:1]"
    assert target_state[KNOWLEDGE_CITATION_REGISTRY_KEY] == [
        {
            "id": "1",
            "label": new_label,
            "url": new_url,
            "stable_key": build_citation_stable_key(citation_label=new_label, citation_link=new_url),
        }
    ]


def test_knowledge_search_tool_merges_historical_citations_into_runtime_state(monkeypatch: Any) -> None:
    """`knowledge_search` (the tool) must register historical citations into state.

    Regression: before this fix the tool called ``search_task_memory`` + render
    directly and skipped ``prepare_task_memory_matches_for_injection``, so the
    LLM saw ``[citation:N]`` markers from past records that were not present in
    ``state["knowledge_citation_registry"]`` — the frontend then could not
    resolve them when the model copied them into its final answer. The tool
    must additionally return a ``Command`` whose update payload echoes the
    merged registry, otherwise the LangGraph channel does not fire.
    """

    from langgraph.types import Command

    from src.community.knowledge_base import tools as knowledge_tools

    historical_label = "历史档案 第3页第2段"
    historical_url = "/api/knowledge/docs/history.pdf?page_no=3&paragraph_no=2"

    def _fake_search(query: str, *, title: str | None = None, top_k: int = 5, task_level: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "metadata": {
                    "summary": "历史结论[citation:7]",
                    "findings": ["要点[citation:7]"],
                    "citations": ["[citation:7]"],
                    "open_questions": [],
                    "citation_registry": [
                        {
                            "id": "7",
                            "label": historical_label,
                            "url": historical_url,
                            "stable_key": build_citation_stable_key(citation_label=historical_label, citation_link=historical_url),
                        }
                    ],
                    "title": "历史任务",
                    "task_level": "main",
                    "query": "历史问题",
                }
            }
        ]

    monkeypatch.setattr(task_memory, "search_task_memory", _fake_search)

    runtime_state: dict[str, Any] = {"current_task_title": "当前任务"}
    fake_runtime = SimpleNamespace(state=runtime_state)

    result = knowledge_tools.knowledge_search_tool.func(
        runtime=fake_runtime,
        query="盛宣怀",
        tool_call_id="call-knowledge-search-1",
    )

    assert isinstance(result, Command)
    update = result.update
    tool_message = update["messages"][0]
    output = tool_message.content
    assert "## 检索结果" in output
    # Historical id 7 must be rewritten to id 1 in the merged registry.
    assert "[citation:1]" in output
    assert "[citation:7]" not in output
    expected_registry = [
        {
            "id": "1",
            "label": historical_label,
            "url": historical_url,
            "stable_key": build_citation_stable_key(citation_label=historical_label, citation_link=historical_url),
        }
    ]
    # The mutation has to be present both in the live state (for in-process readers)
    # and the returned update payload (so LangGraph fires the channel).
    assert runtime_state[KNOWLEDGE_CITATION_REGISTRY_KEY] == expected_registry
    assert update[KNOWLEDGE_CITATION_REGISTRY_KEY] == expected_registry


def test_prepare_task_memory_matches_for_injection_strips_orphan_citations_without_registry() -> None:
    prepared = task_memory.prepare_task_memory_matches_for_injection(
        [
            {
                "metadata": {
                    "summary": "历史摘要[citation:9]",
                    "findings": ["发现[citation:9]"],
                    "citations": ["[citation:9]"],
                    "open_questions": ["待核对[citation:9]"],
                }
            }
        ],
        target_state={},
    )

    metadata = prepared[0]["metadata"]
    assert metadata["summary"] == "历史摘要"
    assert metadata["findings"] == ["发现"]
    assert metadata["citations"] == []
    assert metadata["open_questions"] == ["待核对"]
    assert metadata["citation_registry"] == []


class _DecisionModel:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def invoke(self, _messages: list[Any]) -> SimpleNamespace:
        return SimpleNamespace(content=self.payload)


def test_task_memory_middleware_before_model_returns_merged_registry_in_updates(monkeypatch: Any) -> None:
    """`before_model` must echo the merged registry through its returned updates.

    Regression: the middleware was mutating ``state["knowledge_citation_registry"]``
    in place via ``search_and_prepare_task_memory`` but only returning
    ``messages`` / ``current_task_*`` keys. LangGraph only fires channel updates
    on values present in the returned dict, so the historical citations never
    reached the frontend even though the in-memory state dict looked correct.
    """

    historical_label = "档案 第9页第1段"
    historical_url = "/api/knowledge/docs/foo.pdf?page_no=9&paragraph_no=1"

    def _fake_search_and_prepare(*, query: str, title: str | None, target_state: dict[str, Any] | None, top_k: int, task_level: str | None = None) -> list[dict[str, Any]]:
        # Mimic the production helper's side effect: merge the saved registry
        # into ``target_state`` and return the prepared matches.
        if isinstance(target_state, dict):
            registry = target_state.setdefault(KNOWLEDGE_CITATION_REGISTRY_KEY, [])
            registry.append(
                {
                    "id": "1",
                    "label": historical_label,
                    "url": historical_url,
                    "stable_key": build_citation_stable_key(citation_label=historical_label, citation_link=historical_url),
                }
            )
        return [
            {
                "metadata": {
                    "summary": "历史摘要[citation:1]",
                    "findings": [],
                    "citations": ["[citation:1]"],
                    "open_questions": [],
                    "title": "历史任务",
                    "task_level": "main",
                    "query": "历史问题",
                }
            }
        ]

    monkeypatch.setattr(task_memory_middleware, "search_and_prepare_task_memory", _fake_search_and_prepare)
    monkeypatch.setattr(task_memory_middleware, "title_from_query", lambda query: "当前任务标题")

    middleware = task_memory_middleware.TaskMemoryMiddleware()
    state = {"messages": [HumanMessage(content="盛宣怀与招商局关系？")]}

    result = middleware.before_model(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result is not None
    assert result[KNOWLEDGE_CITATION_REGISTRY_KEY] == [
        {
            "id": "1",
            "label": historical_label,
            "url": historical_url,
            "stable_key": build_citation_stable_key(citation_label=historical_label, citation_link=historical_url),
        }
    ]


def test_task_memory_middleware_skips_qdrant_write_when_model_says_skip(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel('{"action":"skip","reason":"low value"}'),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="这个功能为啥会这样？"),
            AIMessage(content="这是因为当前建议问题生成阶段误读了系统注入文本。"),
        ],
        "current_task_title": "建议问题异常",
        "current_task_human_index": 0,
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert calls == []


def test_task_memory_middleware_skips_insufficient_evidence_without_decision_model(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("decision model should not be called")),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="张之洞某项借款有没有确证？"),
            AIMessage(content="## 任务结果\n【证据不足】目前没有找到可核验 citation，不能下结论。"),
        ],
        "current_task_title": "张之洞借款考证",
        "current_task_human_index": 0,
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert calls == []


def test_task_memory_middleware_updates_qdrant_when_model_says_update(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel(
            '{"action":"update","target_task_id":"main:old-thread:3","reason":"补充同一主题"}'
        ),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？"),
            AIMessage(
                content=(
                    "张之洞创办汉阳铁厂时面对资金筹措、技术采购、官商关系和市场需求错配等问题，"
                    "这些因素共同导致早期经营长期承压，并需要后续制度调整才能维持。"
                )
            ),
        ],
        "current_task_title": "张之洞洋务企业困境",
        "current_task_human_index": 0,
        "current_task_memory_matches": [
            {
                "record_id": "record-1",
                "title": "张之洞汉阳铁厂研究",
                "task_id": "main:old-thread:3",
            }
        ],
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert len(calls) == 1
    assert calls[0]["title"] == "张之洞汉阳铁厂研究"
    assert calls[0]["task_level"] == "main"



def test_task_memory_middleware_extracts_numbered_citations_from_answer(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel('{"action":"add","title":"张之洞铁路建设"}'),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    citation_label = "铁路档案 第21页第1段"
    citation_url = "/api/knowledge/docs/railway.pdf?page_no=21&paragraph_no=1"
    state = {
        "messages": [
            HumanMessage(content="张之洞在铁路建设上做了什么？"),
            AIMessage(
                content=(
                    "张之洞推动铁路建设，并把路权问题提升到跨省协作与保利权层面。[citation:21]\n\n"
                    "参考文献\n"
                    "1. [citation:21]\n\n"
                    "建议问题\n"
                    "1. 后续问题？"
                )
            ),
        ],
        "current_task_title": "张之洞铁路建设",
        "current_task_human_index": 0,
        KNOWLEDGE_CITATION_REGISTRY_KEY: [
            {
                "id": "21",
                "label": citation_label,
                "url": citation_url,
                "stable_key": build_citation_stable_key(citation_label=citation_label, citation_link=citation_url),
            }
        ],
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert len(calls) == 1
    assert calls[0]["citations"] == ["[citation:21]"]
    assert calls[0]["citation_registry"] == state[KNOWLEDGE_CITATION_REGISTRY_KEY]


def test_task_memory_middleware_skips_update_when_target_is_not_matched(monkeypatch: Any) -> None:
    middleware = task_memory_middleware.TaskMemoryMiddleware()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        task_memory_middleware,
        "create_chat_model",
        lambda **_kwargs: _DecisionModel(
            '{"action":"update","target_task_id":"main:missing:9","target_title":"不存在的主题"}'
        ),
    )
    monkeypatch.setattr(
        task_memory_middleware,
        "upsert_task_memory_record",
        lambda **kwargs: calls.append(kwargs) or "record-1",
    )

    state = {
        "messages": [
            HumanMessage(content="张之洞创办汉阳铁厂等洋务企业时具体面临过哪些困境与失败？"),
            AIMessage(
                content=(
                    "张之洞创办汉阳铁厂时面对资金筹措、技术采购、官商关系和市场需求错配等问题，"
                    "这些因素共同导致早期经营长期承压，并需要后续制度调整才能维持。"
                )
            ),
        ],
        "current_task_title": "张之洞洋务企业困境",
        "current_task_human_index": 0,
        "current_task_memory_matches": [
            {
                "record_id": "record-1",
                "title": "张之洞汉阳铁厂研究",
                "task_id": "main:old-thread:3",
            }
        ],
    }

    result = middleware.after_agent(state, SimpleNamespace(context={"thread_id": "t1", "user_id": "u1"}))

    assert result == {"task_memory_saved_human_index": 0}
    assert calls == []


def test_search_task_memory_retries_on_no_embedding_data(monkeypatch: Any) -> None:
    attempt_count = 0

    class _FlakyVectorStore:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def similarity_search_with_score(self, *_args: Any, **_kwargs: Any) -> list:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise RuntimeError("No embedding data received")
            return []

    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", lambda: (object(), object(), "col"))
    monkeypatch.setattr(task_memory, "QdrantVectorStore", _FlakyVectorStore)
    monkeypatch.setattr(task_memory, "sleep", lambda _: None)

    results = task_memory.search_task_memory("盛宣怀")
    assert results == []
    assert attempt_count == 3


def test_search_task_memory_raises_after_max_retries(monkeypatch: Any) -> None:
    attempt_count = 0

    class _AlwaysFailVectorStore:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def similarity_search_with_score(self, *_args: Any, **_kwargs: Any) -> list:
            nonlocal attempt_count
            attempt_count += 1
            raise RuntimeError("No embedding data received")

    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", lambda: (object(), object(), "col"))
    monkeypatch.setattr(task_memory, "QdrantVectorStore", _AlwaysFailVectorStore)
    monkeypatch.setattr(task_memory, "sleep", lambda _: None)

    try:
        task_memory.search_task_memory("盛宣怀")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "no embedding data received" in str(exc).lower()
    assert attempt_count == task_memory._EMBED_RETRY_ATTEMPTS


def test_search_task_memory_does_not_retry_non_transient_error(monkeypatch: Any) -> None:
    attempt_count = 0

    class _NonTransientFailVectorStore:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def similarity_search_with_score(self, *_args: Any, **_kwargs: Any) -> list:
            nonlocal attempt_count
            attempt_count += 1
            raise ValueError("collection not found")

    monkeypatch.setattr(task_memory, "_ensure_task_memory_collection", lambda: (object(), object(), "col"))
    monkeypatch.setattr(task_memory, "QdrantVectorStore", _NonTransientFailVectorStore)
    monkeypatch.setattr(task_memory, "sleep", lambda _: None)

    try:
        task_memory.search_task_memory("盛宣怀")
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert attempt_count == 1


# ---------------------------------------------------------------------------
# _count_distinct_books_in_citation_registry
# ---------------------------------------------------------------------------

def _make_citation_entry(source_title: str) -> dict:
    """Build a minimal citation registry entry with citation_source_title in URL."""
    from urllib.parse import urlencode
    query = urlencode({"citation_source_title": source_title, "other": "param"})
    return {"id": "1", "label": source_title, "url": f"http://example.com/doc?{query}"}


def _make_citation_entry_label_only(label: str) -> dict:
    """Registry entry with no parseable URL — falls back to label."""
    return {"id": "2", "label": label, "url": ""}


def test_count_distinct_books_empty_registry() -> None:
    from src.community.knowledge_base.task_memory import _count_distinct_books_in_citation_registry
    assert _count_distinct_books_in_citation_registry(None) == 0
    assert _count_distinct_books_in_citation_registry([]) == 0


def test_count_distinct_books_single_book() -> None:
    from src.community.knowledge_base.task_memory import _count_distinct_books_in_citation_registry
    registry = [_make_citation_entry("史书甲"), _make_citation_entry("史书甲")]
    assert _count_distinct_books_in_citation_registry(registry) == 1


def test_count_distinct_books_multiple_books() -> None:
    from src.community.knowledge_base.task_memory import _count_distinct_books_in_citation_registry
    registry = [
        _make_citation_entry("史书甲"),
        _make_citation_entry("史书乙"),
        _make_citation_entry("史书丙"),
        _make_citation_entry("史书甲"),  # duplicate
    ]
    assert _count_distinct_books_in_citation_registry(registry) == 3


def test_count_distinct_books_falls_back_to_label() -> None:
    from src.community.knowledge_base.task_memory import _count_distinct_books_in_citation_registry
    registry = [
        _make_citation_entry_label_only("史书甲"),
        _make_citation_entry_label_only("史书乙"),
        _make_citation_entry_label_only("史书甲"),
    ]
    assert _count_distinct_books_in_citation_registry(registry) == 2


# ---------------------------------------------------------------------------
# render_task_memory_matches — citation diversity warning
# ---------------------------------------------------------------------------

def _make_match_with_registry(registry: list[dict], citations: list[str] | None = None) -> dict:
    return {
        "metadata": {
            "title": "测试子任务",
            "task_level": "subtask",
            "query": "测试 query",
            "summary": "找到了一些结果",
            "findings": ["发现 A"],
            "citations": citations or ["[citation:1](http://example.com)"],
            "open_questions": [],
            "citation_registry": registry,
        },
        "score": 0.85,
        "weighted_score": 0.85,
    }


def test_render_shows_narrow_citation_warning_for_one_book() -> None:
    from src.community.knowledge_base.task_memory import render_task_memory_matches
    registry = [_make_citation_entry("唯一的书")]
    result = render_task_memory_matches([_make_match_with_registry(registry)])
    assert "引用书目较少" in result
    assert "1 本书" in result
    assert "需要补充" in result


def test_render_shows_narrow_citation_warning_for_two_books() -> None:
    from src.community.knowledge_base.task_memory import render_task_memory_matches
    registry = [_make_citation_entry("书甲"), _make_citation_entry("书乙")]
    result = render_task_memory_matches([_make_match_with_registry(registry)])
    assert "引用书目较少" in result
    assert "2 本书" in result


def test_render_no_warning_for_three_or_more_books() -> None:
    from src.community.knowledge_base.task_memory import render_task_memory_matches
    registry = [
        _make_citation_entry("书甲"),
        _make_citation_entry("书乙"),
        _make_citation_entry("书丙"),
    ]
    result = render_task_memory_matches([_make_match_with_registry(registry)])
    # The specific per-result warning text must NOT appear
    # (⚠️ can appear in trailing instructions, so we check the specific warning phrase)
    assert "引用书目较少" not in result
    assert "注册信息不完整" not in result


def test_render_unverifiable_breadth_warning_when_citations_but_no_registry() -> None:
    from src.community.knowledge_base.task_memory import render_task_memory_matches
    # _is_complete_citation only accepts bare [citation:N] numbered format
    match = _make_match_with_registry(registry=[], citations=["[citation:1]"])
    result = render_task_memory_matches([match])
    assert "注册信息不完整" in result


def test_render_no_warning_when_no_citations_and_no_registry() -> None:
    from src.community.knowledge_base.task_memory import render_task_memory_matches
    match = _make_match_with_registry(registry=[], citations=[])
    result = render_task_memory_matches([match])
    # no citations at all → no breadth warning (model can see empty citations list directly)
    assert "注册信息不完整" not in result
