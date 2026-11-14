import sys
from types import SimpleNamespace
from types import ModuleType

if "langchain_core.memory" not in sys.modules:
    langchain_core_memory = ModuleType("langchain_core.memory")

    class _DummyBaseMemory:  # pragma: no cover - test import shim
        pass

    langchain_core_memory.BaseMemory = _DummyBaseMemory
    sys.modules["langchain_core.memory"] = langchain_core_memory

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.book_coverage_middleware import BookCoverageMiddleware


def _request_with_unread_book() -> ModelRequest:
    return ModelRequest(
        model=SimpleNamespace(),
        messages=[
            HumanMessage(content="请综合两本书回答"),
            ToolMessage(content="检索完成", tool_call_id="cp-1", name="knowledge_checkpoint"),
        ],
        system_message=SystemMessage(content="You are a helpful assistant."),
        state={
            "messages": [
                HumanMessage(content="请综合两本书回答"),
                ToolMessage(content="检索完成", tool_call_id="cp-1", name="knowledge_checkpoint"),
            ],
            "knowledge_reading_set_doc_ids": ["read-doc", "unread-doc"],
            "knowledge_reading_set_titles": {"read-doc": "已读书", "unread-doc": "未读书"},
            "knowledge_covered_doc_ids": ["read-doc"],
            "knowledge_reading_set_query": "请综合两本书回答",
            "knowledge_reading_set_human_index": 0,
        },
    )


def test_book_coverage_middleware_retries_when_model_keeps_searching_only_read_book():
    middleware = BookCoverageMiddleware()
    request = _request_with_unread_book()
    seen_requests: list[ModelRequest] = []

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_requests.append(current_request)
        if len(seen_requests) == 1:
            return ModelResponse(
                result=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-1",
                                "name": "knowledge_search",
                                "args": {"query": "继续查", "doc_ids": ["read-doc"]},
                            }
                        ],
                    )
                ]
            )
        return ModelResponse(
            result=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-2",
                            "name": "knowledge_locate",
                            "args": {"doc_id": "unread-doc"},
                        }
                    ],
                )
            ]
        )

    final_response = middleware.wrap_model_call(request, handler)

    assert len(seen_requests) == 2
    assert "未读书 (`unread-doc`)" in str(seen_requests[1].messages[-2].content)
    assert final_response.result[-1].tool_calls[0]["name"] == "knowledge_locate"
    assert final_response.result[-1].tool_calls[0]["args"]["doc_id"] == "unread-doc"
