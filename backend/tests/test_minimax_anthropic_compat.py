from langchain_core.messages import AIMessage

from src.models.minimax_anthropic_compat import (
    normalize_minimax_anthropic_message,
)
from src.models.minimax_thinking import sanitize_minimax_anthropic_thinking_text


def test_sanitize_removes_leaked_thinking_dict_and_keeps_answer() -> None:
    leaked = (
        """{'thinking': 'The user simply said "hi".', 'type': 'thinking', """
        """'index': 0, 'signature': 'abc'}\n\nHello!"""
    )

    sanitized = sanitize_minimax_anthropic_thinking_text(leaked)

    assert sanitized.content == "Hello!"
    assert sanitized.reasoning == 'The user simply said "hi".'


def test_sanitize_preserves_non_thinking_dict_literals() -> None:
    content = "Here is data: {'type': 'text', 'thinking': 'visible'}"

    sanitized = sanitize_minimax_anthropic_thinking_text(content)

    assert sanitized.content == content
    assert sanitized.reasoning is None


def test_sanitize_combines_multiple_leaked_thinking_blocks() -> None:
    leaked = (
        "{'type': 'thinking', 'thinking': 'first'}"
        "Visible"
        "{'type': 'thinking', 'thinking': 'second'}"
    )

    sanitized = sanitize_minimax_anthropic_thinking_text(leaked)

    assert sanitized.content == "Visible"
    assert sanitized.reasoning == "first\nsecond"


def test_normalize_message_moves_reasoning_to_additional_kwargs() -> None:
    message = AIMessage(
        content=(
            "{'thinking': 'plan', 'type': 'thinking', 'index': 0, "
            "'signature': 'abc'}\nFinal answer"
        )
    )

    normalize_minimax_anthropic_message(message)

    assert message.content == "Final answer"
    assert message.additional_kwargs["reasoning_content"] == "plan"


def test_normalize_message_handles_text_blocks() -> None:
    message = AIMessage(
        content=[
            {
                "type": "text",
                "text": "{'type': 'thinking', 'thinking': 'hidden'}",
            },
            {"type": "text", "text": "Visible"},
        ]
    )

    normalize_minimax_anthropic_message(message)

    assert message.content == [{"type": "text", "text": "Visible"}]
    assert message.additional_kwargs["reasoning_content"] == "hidden"
