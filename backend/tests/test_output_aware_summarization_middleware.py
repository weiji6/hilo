from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.middlewares.output_aware_summarization_middleware import OutputAwareSummarizationMiddleware


class _DummySummarizationModel:
    profile = {"max_input_tokens": 256000}

    def _get_ls_params(self):
        return {"ls_provider": "openai"}


def test_output_aware_summarization_skips_after_fresh_final_answer():
    middleware = OutputAwareSummarizationMiddleware(
        model=_DummySummarizationModel(),
        trigger=("messages", 2),
        keep=("messages", 1),
        token_counter=lambda messages: len(messages),
    )
    state = {
        "messages": [
            HumanMessage(content="上一问"),
            AIMessage(content="上一问的最终答案"),
            HumanMessage(content="下一问"),
        ]
    }

    assert middleware.before_model(state, runtime=None) is None


def test_output_aware_summarization_skips_when_latest_message_is_completed_ai_answer():
    middleware = OutputAwareSummarizationMiddleware(
        model=_DummySummarizationModel(),
        trigger=("messages", 2),
        keep=("messages", 1),
        token_counter=lambda messages: len(messages),
    )
    state = {
        "messages": [
            HumanMessage(content="上一问"),
            AIMessage(
                content=(
                    "这是完整回答。\n\n"
                    "参考文献\n"
                    "1. [citation:史料 第7页第2段](/api/knowledge/docs/book.pdf?page_no=7&paragraph_no=2)\n\n"
                    "建议问题\n"
                    "1. 继续问什么？"
                )
            ),
        ]
    }

    assert middleware.before_model(state, runtime=None) is None


def test_output_aware_summarization_does_not_skip_after_tool_call_round():
    middleware = OutputAwareSummarizationMiddleware(
        model=_DummySummarizationModel(),
        trigger=("messages", 2),
        keep=("messages", 1),
        token_counter=lambda messages: len(messages),
    )
    state = {
        "messages": [
            HumanMessage(content="上一问"),
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": "knowledge_search", "args": {}}]),
            ToolMessage(content="检索结果", tool_call_id="call-1", name="knowledge_search"),
            HumanMessage(content="下一问"),
        ]
    }

    update = middleware.before_model(state, runtime=None)

    assert update is not None
