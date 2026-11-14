from src.tools.builtins.knowledge_checkpoint_tool import _normalize_string_list, knowledge_checkpoint_tool


def test_normalize_string_list_accepts_json_array_string() -> None:
    raw = '["citation 1", "citation 2"]'

    assert _normalize_string_list(raw) == ["citation 1", "citation 2"]


def test_normalize_string_list_accepts_python_list_string() -> None:
    raw = "['question 1', 'question 2']"

    assert _normalize_string_list(raw) == ["question 1", "question 2"]


def test_normalize_string_list_accepts_bullet_lines() -> None:
    raw = "- one\n- two"

    assert _normalize_string_list(raw) == ["one", "two"]


def test_normalize_string_list_falls_back_to_single_string() -> None:
    raw = "single item"

    assert _normalize_string_list(raw) == ["single item"]


def test_checkpoint_schema_requires_non_nullable_citations() -> None:
    citations_field = knowledge_checkpoint_tool.args_schema.model_fields["citations"]
    assert citations_field.is_required()
    assert citations_field.annotation == list[str] | str
