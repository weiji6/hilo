from __future__ import annotations

from types import SimpleNamespace

import src.tools as tools_module
from src.agents.middlewares import parallel_todo_list_middleware as todo_module
from src.subagents.config import SubagentConfig


def test_write_todos_marks_cancelled_subtask_as_failed(monkeypatch):
    events: list[dict] = []

    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: events.append(event))
    monkeypatch.setattr(todo_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        todo_module,
        "get_subagent_config",
        lambda name: SubagentConfig(
            name=name,
            description="test",
            system_prompt="test",
            timeout_seconds=5,
        ),
    )

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def execute_async(self, prompt: str, task_id: str, **kwargs):
            return task_id

    class FakeStatus:
        COMPLETED = "completed"
        FAILED = "failed"
        TIMED_OUT = "timed_out"
        CANCELLED = "cancelled"

    monkeypatch.setattr(todo_module, "SubagentExecutor", FakeExecutor)
    monkeypatch.setattr(todo_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(
        todo_module,
        "get_background_task_result",
        lambda task_id: SimpleNamespace(
            status=FakeStatus.CANCELLED,
            result=None,
            error="Subtask cancelled because the parent session was interrupted.",
            ai_messages=[],
            structured_result=None,
        ),
    )

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )
    runtime = SimpleNamespace(
        state={"todos": [], "sandbox": None, "thread_data": None},
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[{"content": "执行中的子任务", "status": "in_progress"}],
        tool_call_id="call-cancel",
    )

    todos = command.update["todos"]
    assert todos[0]["status"] == "failed"
    assert "cancelled" in todos[0]["error"].lower()
    assert any(event["type"] == "task_failed" for event in events)
