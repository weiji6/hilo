from typing import Annotated, NotRequired, TypedDict

from langchain.agents import AgentState

from src.community.knowledge_base.citations import merge_citation_registries


class SandboxState(TypedDict):
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    base64: str
    mime_type: str


class TodoOrchestrationState(TypedDict):
    mode: str
    phase: str
    last_write_todos_tool_call_id: str
    dispatched_todo_ids: list[str]
    dispatched_task_ids: list[str]


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for artifacts list - merges and deduplicates artifacts."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Use dict.fromkeys to deduplicate while preserving order
    return list(dict.fromkeys(existing + new))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """Reducer for viewed_images dict - merges image dictionaries.

    Special case: If new is an empty dict {}, it clears the existing images.
    This allows middlewares to clear the viewed_images state after processing.
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    # Special case: empty dict means clear all viewed images
    if len(new) == 0:
        return {}
    # Merge dictionaries, new values override existing ones for same keys
    return {**existing, **new}


class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    current_task_title: NotRequired[str | None]
    current_task_human_index: NotRequired[int | None]
    task_memory_injected_human_index: NotRequired[int | None]
    task_memory_saved_human_index: NotRequired[int | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: NotRequired[list | None]
    todo_orchestration: NotRequired[TodoOrchestrationState | None]
    subtasks_cancel_requested_at: NotRequired[str | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
    knowledge_reading_set_doc_ids: NotRequired[list[str] | None]
    knowledge_reading_set_titles: NotRequired[dict[str, str] | None]
    knowledge_covered_doc_ids: NotRequired[list[str] | None]
    knowledge_reading_set_query: NotRequired[str | None]
    knowledge_reading_set_human_index: NotRequired[int | None]
    knowledge_citation_registry: Annotated[list[dict], merge_citation_registries]
    subtask_final_result: NotRequired[dict | None]
