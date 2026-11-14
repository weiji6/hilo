"""Pure helpers for MiniMax's nonstandard leaked thinking text."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class SanitizedThinking:
    content: str
    reasoning: str | None


def _find_python_dict_literal_end(text: str, start: int) -> int | None:
    depth = 0
    quote: str | None = None
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1

    return None


def sanitize_minimax_anthropic_thinking_text(text: str) -> SanitizedThinking:
    """Remove leaked MiniMax thinking dict literals from visible text.

    Returns the cleaned visible content plus the extracted reasoning text. The
    parser is intentionally conservative: only dict literals with
    ``type == "thinking"`` and a string ``thinking`` field are removed.
    """

    output_parts: list[str] = []
    reasoning_parts: list[str] = []
    cursor = 0

    while True:
        start = text.find("{", cursor)
        if start == -1:
            output_parts.append(text[cursor:])
            break

        output_parts.append(text[cursor:start])
        end = _find_python_dict_literal_end(text, start)
        if end is None:
            output_parts.append(text[start:])
            break

        literal = text[start:end]
        try:
            value = ast.literal_eval(literal)
        except (SyntaxError, ValueError):
            output_parts.append(literal)
        else:
            if (
                isinstance(value, dict)
                and value.get("type") == "thinking"
                and isinstance(value.get("thinking"), str)
            ):
                reasoning_parts.append(value["thinking"])
            else:
                output_parts.append(literal)
        cursor = end

    content = "".join(output_parts).strip()
    reasoning = "\n".join(part for part in reasoning_parts if part).strip() or None
    return SanitizedThinking(content=content, reasoning=reasoning)
