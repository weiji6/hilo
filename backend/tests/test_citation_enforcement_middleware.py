"""Tests for numbered citation enforcement middleware."""

from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.middlewares.citation_enforcement_middleware import (
    FINAL_FALLBACK_RESPONSE,
    UNGROUNDED_WARNING_MARKER,
    CitationEnforcementMiddleware,
)
from src.community.knowledge_base.citations import KNOWLEDGE_CITATION_REGISTRY_KEY


class _SuggestionModel:
    def __init__(self, suggestions: str | None = None) -> None:
        self.suggestions = suggestions or "问题一？\n问题二？\n问题三？"
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.suggestions)

    async def ainvoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.suggestions)


def _registry() -> list[dict[str, str]]:
    return [
        {
            "id": "1",
            "label": "史料 第7页第2段",
            "url": "/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2",
        }
    ]


def _build_request(model=None, tool_name: str = "knowledge_locate", question: str = "请根据知识库回答这个问题") -> ModelRequest:
    return ModelRequest(
        model=model or _SuggestionModel(),
        messages=[
            HumanMessage(content=question),
            ToolMessage(
                content="citation: [citation:1] (史料 第7页第2段)",
                tool_call_id="tool-call-1",
                name=tool_name,
            ),
        ],
        state={KNOWLEDGE_CITATION_REGISTRY_KEY: _registry()},
        system_message=SystemMessage(content="You are a helpful assistant."),
    )


def _bad_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="这是一个没有 citation 的回答。")])


def _good_numbered_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="根据现有资料，可以得出相关结论。[citation:1]")])


def _old_link_response() -> ModelResponse:
    return ModelResponse(
        result=[
            AIMessage(
                content=(
                    "根据现有资料，可以得出相关结论。"
                    "[citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)"
                )
            )
        ]
    )


def _refusal_response(content: str) -> ModelResponse:
    return ModelResponse(result=[AIMessage(content=content)])


class TestCitationEnforcementMiddleware:
    def test_numbered_citation_is_resolved_from_state_without_exposing_url_in_retry_hint(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("继续追问一？\n继续追问二？\n继续追问三？"))
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return _bad_response() if len(seen_requests) == 1 else _good_numbered_response()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)
        retry_system = str(seen_requests[1].system_message.content)

        assert "根据现有资料，可以得出相关结论。[citation:1]" in content
        assert "1. [citation:1]" in content
        assert "citation: [citation:1] (史料 第7页第2段)" in retry_system
        assert "/api/knowledge/docs/book.pdf" not in retry_system
        assert "[citation:史料 第7页第2段](</api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2>)" not in content

    def test_old_linked_citation_is_not_accepted_or_repaired(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("缩小范围？\n指定书名？\n补充线索？"))
        seen_requests: list[ModelRequest] = []

        def handler(current_request: ModelRequest) -> ModelResponse:
            seen_requests.append(current_request)
            return _old_link_response()

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert len(seen_requests) == 3
        assert content.startswith(FINAL_FALLBACK_RESPONSE)
        assert "/api/knowledge/docs/book.pdf" not in content
        assert "参考文献" not in content

    def test_stage_two_rebuilds_reference_section_and_stage_three_rebuilds_suggestions(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("新问题一？\n新问题二？\n新问题三？"), question="请详细考证这个历史问题")

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "根据现有资料，可以得出相关结论。[citation:1]\n\n"
                            "参考文献\n"
                            "1. [citation:旧引用](/old)\n\n"
                            "建议问题\n"
                            "1. 旧问题？"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "[citation:旧引用](/old)" not in content
        assert "旧问题？" not in content
        assert "参考文献" in content
        assert "1. [citation:1]" in content
        assert "建议问题" in content
        assert "1. 新问题一？" in content
        assert "/api/knowledge/docs/book.pdf" not in content

    def test_stage_three_feeds_current_findings_context_to_suggestion_model(self):
        middleware = CitationEnforcementMiddleware()
        suggestion_model = _SuggestionModel(
            "盛宣怀在轮船招商局的官督商办机制如何影响晚清财政与商股关系？\n"
            "电报、铁路与银行事业之间的筹资网络是否构成盛宣怀贡献的制度核心？\n"
            "甲午后铁路国有化争议如何改变对盛宣怀实业贡献的历史评价？"
        )
        request = ModelRequest(
            model=suggestion_model,
            messages=[
                HumanMessage(content="请详细考证盛宣怀是谁，有什么突出贡献"),
                ToolMessage(
                    content=(
                        "### Todo: 查盛宣怀的晚清实业财政活动\n"
                        "任务结果:\n"
                        "盛宣怀的突出贡献集中在轮船招商局、电报、铁路、银行等官督商办事业，"
                        "但仍需补查这些事业如何连接财政筹款、商股募集与国家利权。"
                    ),
                    tool_call_id="todo-call-1",
                    name="write_todos",
                ),
                ToolMessage(
                    content="citation: [citation:1] (史料 第7页第2段)",
                    tool_call_id="tool-call-1",
                    name="knowledge_locate",
                ),
            ],
            state={KNOWLEDGE_CITATION_REGISTRY_KEY: _registry()},
            system_message=SystemMessage(content="You are a helpful assistant."),
        )

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "盛宣怀是晚清官僚型实业人物，其贡献主要体现为推动轮船招商局、电报、铁路、银行等新式事业。"
                            "[citation:1]"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        prompt = str(suggestion_model.messages[1].content)
        content = str(final_response.result[-1].content)

        assert "当前主任务/子任务已有发现摘要" in prompt
        assert "轮船招商局" in prompt
        assert "官督商办" in prompt
        assert "商股募集" in prompt
        assert "盛宣怀在轮船招商局的官督商办机制" in content

    def test_allows_refusal_without_reference_section(self):
        middleware = CitationEnforcementMiddleware()
        request = _build_request(model=_SuggestionModel("缩小到更具体时期？\n指定书名或章节？\n优先核实哪条史料？"))
        refusal = _refusal_response("【无法回答】当前书目中暂无相关资料，无法根据现有资料回答这个问题。")

        def handler(_: ModelRequest) -> ModelResponse:
            return refusal

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert content.startswith("【无法回答】当前书目中暂无相关资料")
        assert "参考文献" not in content
        assert "建议问题" in content

    def test_historical_citation_without_current_tool_call_does_not_show_ungrounded_warning(self):
        middleware = CitationEnforcementMiddleware()
        request = ModelRequest(
            model=_SuggestionModel("继续核对哪些来源？\n还需比较哪一时期？\n是否要追问制度细节？"),
            messages=[HumanMessage(content="继续刚才的话题")],
            state={KNOWLEDGE_CITATION_REGISTRY_KEY: _registry()},
            system_message=SystemMessage(content="You are a helpful assistant."),
        )

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "延续前面的结论，这一变化应放在晚清财政制度调整和地方执行之间理解，"
                            "尤其要注意文本中对具体执行环节的描述。[citation:1]"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert "[citation:1]" in content
        assert UNGROUNDED_WARNING_MARKER not in content

    def test_substantive_answer_without_citation_shows_ungrounded_warning_even_without_tool_call(self):
        middleware = CitationEnforcementMiddleware()
        request = ModelRequest(
            model=_SuggestionModel("继续核对哪些来源？\n还需比较哪一时期？\n是否要追问制度细节？"),
            messages=[HumanMessage(content="介绍一下这个背景")],
            state={KNOWLEDGE_CITATION_REGISTRY_KEY: _registry()},
            system_message=SystemMessage(content="You are a helpful assistant."),
        )

        def handler(_: ModelRequest) -> ModelResponse:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "这个背景可以概括为晚清财政压力、地方治理需求与新式事业扩张之间的相互作用，"
                            "相关变化通常需要同时观察制度设计、执行主体和资金来源三个层面。"
                        )
                    )
                ]
            )

        final_response = middleware.wrap_model_call(request, handler)
        content = str(final_response.result[-1].content)

        assert UNGROUNDED_WARNING_MARKER in content
