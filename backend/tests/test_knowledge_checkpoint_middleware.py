from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.knowledge_checkpoint_middleware import (
    KnowledgeCheckpointMiddleware,
)


def _build_request(messages: list) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="ok")])


def _tool_call_response(name: str) -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"{name}-call-1",
                        "name": name,
                        "args": {
                            "title": "北洋政府财政",
                            "summary": "已整理本板块发现",
                            "citations": ["citation: ..."],
                        },
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )


def _empty_checkpoint_response() -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "knowledge_checkpoint-call-empty",
                        "name": "knowledge_checkpoint",
                        "args": {
                            "title": "北洋政府财政",
                            "summary": "已整理本板块发现",
                            "citations": None,
                        },
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )


def test_replaces_grounding_payloads_before_latest_checkpoint_only():
    middleware = KnowledgeCheckpointMiddleware()
    seen_messages: list = []
    request = _build_request(
        [
            HumanMessage(content="请继续总结"),
            ToolMessage(content="very long search result", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="very long locate result", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="checkpoint A", tool_call_id="cp-1", name="knowledge_checkpoint"),
            ToolMessage(content="new search result", tool_call_id="ks-2", name="knowledge_search"),
        ]
    )

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_messages.extend(current_request.messages)
        return _response()

    middleware.wrap_model_call(request, handler)

    assert str(seen_messages[1].content).startswith("【已调用knowledge_search工具】")
    assert str(seen_messages[2].content).startswith("【已调用knowledge_locate工具】")
    assert str(seen_messages[3].content) == "checkpoint A"
    assert str(seen_messages[4].content) == "new search result"


def test_leaves_messages_untouched_when_no_checkpoint_exists():
    middleware = KnowledgeCheckpointMiddleware()
    seen_messages: list = []
    request = _build_request(
        [
            HumanMessage(content="请继续总结"),
            ToolMessage(content="raw search result", tool_call_id="ks-1", name="knowledge_search"),
        ]
    )

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_messages.extend(current_request.messages)
        return _response()

    middleware.wrap_model_call(request, handler)

    assert str(seen_messages[1].content) == "raw search result"


def test_retries_until_model_calls_checkpoint_after_grounding_threshold():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request(
        [
            HumanMessage(content="请详细整理表格"),
            ToolMessage(content="substantive search result 1", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="substantive locate result 2", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="substantive search result 3", tool_call_id="ks-2", name="knowledge_search"),
            ToolMessage(content="substantive locate result 4", tool_call_id="kl-2", name="knowledge_locate"),
            ToolMessage(content="substantive search result 5", tool_call_id="ks-3", name="knowledge_search"),
        ]
    )
    seen_requests: list[ModelRequest] = []
    responses = [
        _tool_call_response("knowledge_search"),
        _tool_call_response("knowledge_checkpoint"),
    ]

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_requests.append(current_request)
        return responses[len(seen_requests) - 1]

    final_response = middleware.wrap_model_call(request, handler)

    assert len(seen_requests) == 2
    assert seen_requests[1].messages[-1].type == "human"
    assert "系统插入提示（不是用户的新问题）" in str(seen_requests[1].messages[-1].content)
    assert "必须且只能调用一次 `knowledge_checkpoint`" in str(seen_requests[1].messages[-1].content)
    final_ai = final_response.result[-1]
    assert isinstance(final_ai, AIMessage)
    assert final_ai.tool_calls[0]["name"] == "knowledge_checkpoint"


def test_retries_when_checkpoint_args_are_empty():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request(
        [
            HumanMessage(content="请详细整理表格"),
            ToolMessage(content="substantive search result 1", tool_call_id="ks-1", name="knowledge_search"),
            ToolMessage(content="substantive locate result 2", tool_call_id="kl-1", name="knowledge_locate"),
            ToolMessage(content="substantive search result 3", tool_call_id="ks-2", name="knowledge_search"),
            ToolMessage(content="substantive locate result 4", tool_call_id="kl-2", name="knowledge_locate"),
            ToolMessage(content="substantive search result 5", tool_call_id="ks-3", name="knowledge_search"),
        ]
    )
    seen_requests: list[ModelRequest] = []
    responses = [
        _empty_checkpoint_response(),
        _tool_call_response("knowledge_checkpoint"),
    ]

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_requests.append(current_request)
        return responses[len(seen_requests) - 1]

    final_response = middleware.wrap_model_call(request, handler)

    assert len(seen_requests) == 2
    final_ai = final_response.result[-1]
    assert isinstance(final_ai, AIMessage)
    assert final_ai.tool_calls[0]["args"]["citations"] == ["citation: ..."]


def test_does_not_enforce_checkpoint_for_non_substantive_grounding_results():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request(
        [
            HumanMessage(content="请详细整理表格"),
            ToolMessage(
                content="本轮没有命中到可直接使用的内部知识片段。",
                tool_call_id="ks-1",
                name="knowledge_search",
            ),
            ToolMessage(
                content="No matching page/paragraph/line context found.",
                tool_call_id="kl-1",
                name="knowledge_locate",
            ),
        ]
    )
    seen_requests: list[ModelRequest] = []

    def handler(current_request: ModelRequest) -> ModelResponse:
        seen_requests.append(current_request)
        return _response()

    middleware.wrap_model_call(request, handler)

    assert len(seen_requests) == 1


def test_terminal_submission_bypasses_checkpoint_even_after_many_reads():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request([HumanMessage(content='请详细研究')] + [ToolMessage(content='source text', tool_call_id=str(i), name='knowledge_locate') for i in range(8)])
    response = _tool_call_response('submit_task_result')
    calls = []
    def handler(req):
        calls.append(req)
        return response
    assert middleware.wrap_model_call(request, handler) is response
    assert len(calls) == 1


def test_async_terminal_submission_bypasses_checkpoint_retry():
    import asyncio
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request([HumanMessage(content='请详细研究')] + [ToolMessage(content='source text', tool_call_id=str(i), name='knowledge_locate') for i in range(8)])
    response = _tool_call_response('submit_task_result')
    calls = []
    async def handler(req):
        calls.append(req)
        return response
    assert asyncio.run(middleware.awrap_model_call(request, handler)) is response
    assert len(calls) == 1


def test_submission_on_checkpoint_retry_is_not_discarded():
    middleware = KnowledgeCheckpointMiddleware()
    request = _build_request([HumanMessage(content='research in depth')] + [ToolMessage(content='source text', tool_call_id=str(i), name='knowledge_locate') for i in range(5)])
    final = _tool_call_response('submit_task_result')
    calls = []
    def handler(req):
        calls.append(req)
        return _response() if len(calls) == 1 else final
    assert middleware.wrap_model_call(request, handler) is final
    assert len(calls) == 2
