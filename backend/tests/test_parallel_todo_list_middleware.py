from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

import src.tools as tools_module
from src.agents.middlewares import parallel_todo_list_middleware as todo_module
from src.subagents.config import SubagentConfig


def test_write_todos_dispatches_parallel_batch_and_updates_todos(monkeypatch):
    events: list[dict] = []
    launched_prompts: dict[str, str] = {}

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
            launched_prompts[task_id] = prompt
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
            status=FakeStatus.COMPLETED,
            started_at=None,
            completed_at=None,
            result=f"result for {task_id}",
            error=None,
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
        todos=[
            {"content": "读《甲书》：查税制", "status": "in_progress"},
            {"content": "读《乙书》：查债务", "status": "in_progress"},
            {"content": "读《丙书》：查币制", "status": "in_progress"},
        ],
        tool_call_id="call-1",
    )

    todos = command.update["todos"]
    assert len(launched_prompts) == 3
    assert len(todos) == 3
    assert todos[0]["status"] == "completed"
    assert todos[1]["status"] == "completed"
    assert todos[2]["status"] == "completed"
    assert command.update["todo_orchestration"] is None
    assert todos[0]["task_id"] == "call-1:" + todos[0]["id"]
    assert todos[2]["task_id"] == "call-1:" + todos[2]["id"]
    assert "result_summary" in todos[0]
    assert any(event["type"] == "task_started" for event in events)
    assert any(event["type"] == "task_completed" for event in events)
    assert "Parallel dispatch summary:" in command.update["messages"][0].content
    assert "最多 2 个并发子任务自动分批执行" in command.update["messages"][0].content


def test_write_todos_merges_subtask_citation_registry_and_rewrites_markers(monkeypatch):
    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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
            status=FakeStatus.COMPLETED,
            started_at=None,
            completed_at=None,
            result="## 任务结果\n甲书证明了税制变化。[citation:1]",
            error=None,
            ai_messages=[],
            structured_result={
                "summary": "甲书证明了税制变化。[citation:1]",
                "findings": ["税制变化有页码证据。[citation:1]"],
                "citations": ["[citation:1]"],
                "open_questions": [],
            },
            citation_registry=[
                {
                    "id": "1",
                    "label": "甲书 原书第12页第3段",
                    "url": "/api/knowledge/docs/a.pdf?page_no=12&paragraph_no=3",
                }
            ],
        ),
    )

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=1,
    )
    runtime = SimpleNamespace(
        state={
            "todos": [],
            "sandbox": None,
            "thread_data": None,
            "knowledge_citation_registry": [
                {
                    "id": "1",
                    "label": "既有书 原书第1页第1段",
                    "url": "/api/knowledge/docs/existing.pdf?page_no=1&paragraph_no=1",
                }
            ],
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[{"content": "读《甲书》：查税制", "status": "in_progress"}],
        tool_call_id="call-cite",
    )

    todos = command.update["todos"]
    tool_content = command.update["messages"][0].content

    assert runtime.state["knowledge_citation_registry"][1]["label"] == "甲书 原书第12页第3段"
    assert todos[0]["structured_summary"] == "甲书证明了税制变化。[citation:2]"
    assert todos[0]["structured_findings"] == ["税制变化有页码证据。[citation:2]"]
    assert todos[0]["structured_citations"] == ["[citation:2]"]
    assert "[citation:2]" in tool_content
    assert "甲书证明了税制变化。[citation:1]" not in tool_content


def test_write_todos_wraps_custom_task_prompt_with_knowledge_locate_guardrails(monkeypatch):
    launched_prompts: dict[str, str] = {}

    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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
            launched_prompts[task_id] = prompt
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
            status=FakeStatus.COMPLETED,
            started_at=None,
            completed_at=None,
            result=f"done: {task_id}",
            error=None,
            ai_messages=[],
            structured_result=None,
        ),
    )

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=1,
    )
    runtime = SimpleNamespace(
        state={"todos": [], "sandbox": None, "thread_data": None},
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    middleware.tools[0].func(
        runtime=runtime,
        todos=[
            {
                "content": "读《李鸿章全集》",
                "status": "in_progress",
                "task_prompt": "检索海防相关奏折。",
            }
        ],
        tool_call_id="call-custom",
    )

    launched_prompt = next(iter(launched_prompts.values()))
    assert "检索海防相关奏折。" in launched_prompt
    assert "强制检索规则" in launched_prompt
    assert "分配的原样 `doc_id` 重试一次" in launched_prompt
    assert "submit_task_result" in launched_prompt
    assert "missing-doc-id" in launched_prompt


def test_write_todos_auto_promotes_pending_queue_until_all_batches_finish(monkeypatch):
    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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

    launched_order: list[str] = []

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def execute_async(self, prompt: str, task_id: str, **kwargs):
            launched_order.append(task_id)
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
            status=FakeStatus.COMPLETED,
            started_at=None,
            completed_at=None,
            result=f"done: {task_id}",
            error=None,
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
        todos=[
            {"content": "先执行的任务", "status": "in_progress"},
            {"content": "排队任务一", "status": "pending"},
            {"content": "排队任务二", "status": "pending"},
        ],
        tool_call_id="call-2",
    )

    todos = command.update["todos"]
    assert launched_order == [
        "call-2:" + todos[0]["id"],
        "call-2:" + todos[1]["id"],
        "call-2:" + todos[2]["id"],
    ]
    assert [todo["status"] for todo in todos] == ["completed", "completed", "completed"]
    assert all(todo["task_id"].startswith("call-2:") for todo in todos)
    assert "No subagent batch was dispatched." not in command.update["messages"][0].content


def test_write_todos_rejects_mixed_tool_batch():
    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "write_todos", "args": {"todos": []}, "id": "write-1", "type": "tool_call"},
                    {"name": "bash", "args": {"command": "pwd"}, "id": "bash-1", "type": "tool_call"},
                ],
            )
        ]
    }

    result = middleware.after_model(state, SimpleNamespace())

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert messages[0].tool_call_id == "bash-1"
    assert messages[0].status == "error"
    assert "phase boundary" in messages[0].content


def test_coerce_todos_list_from_json_string() -> None:
    """_coerce_todos_list must parse a JSON-encoded string into a Python list."""
    coerce = todo_module._coerce_todos_list

    raw = '[{"content": "查关税制度", "id": "1", "status": "in_progress"}, {"content": "查鸦片战争", "id": "2", "status": "pending"}]'
    result = coerce(raw)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["content"] == "查关税制度"
    assert result[1]["status"] == "pending"


def test_coerce_todos_list_passthrough_for_real_list() -> None:
    """_coerce_todos_list must pass through a real list unchanged."""
    coerce = todo_module._coerce_todos_list

    items = [{"content": "task 1", "status": "pending"}]
    assert coerce(items) is items


def test_coerce_todos_list_passthrough_for_non_parseable_string() -> None:
    """_coerce_todos_list must return non-JSON strings as-is (Pydantic will then reject them)."""
    coerce = todo_module._coerce_todos_list

    bad = "not valid json"
    assert coerce(bad) == bad


def test_coerce_write_todos_args_patches_string_todos_in_ai_message() -> None:
    """_coerce_write_todos_args must replace a JSON-string todos arg with a real list.

    This is the after_model guard that intercepts the malformed tool call
    before Pydantic validation rejects it.
    """
    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=False,
    )

    json_string = '[{"content": "查关税制度", "id": "1", "status": "in_progress"}]'
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_todos",
                        "args": {"todos": json_string},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }

    result = middleware._coerce_write_todos_args(state)

    assert result is not None, "should return a patched message"
    patched_msg = result["messages"][0]
    patched_todos = patched_msg.tool_calls[0]["args"]["todos"]
    assert isinstance(patched_todos, list), "todos should now be a real list"
    assert patched_todos[0]["content"] == "查关税制度"


def test_coerce_write_todos_args_noop_when_todos_already_a_list() -> None:
    """_coerce_write_todos_args should return None (no patch needed) when todos is already a list."""
    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=False,
    )

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_todos",
                        "args": {"todos": [{"content": "task", "status": "pending"}]},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }

    result = middleware._coerce_write_todos_args(state)
    assert result is None, "no patch needed when todos is already a list"


def test_write_todos_can_redispatch_completed_todo_with_same_content(monkeypatch):
    launched_task_ids: list[str] = []

    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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
            launched_task_ids.append(task_id)
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
            status=FakeStatus.COMPLETED,
            started_at=None,
            completed_at=None,
            result=f"rerun: {task_id}",
            error=None,
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
        state={
            "todos": [
                {
                    "id": "todo-same",
                    "content": "读《甲书》：查税制",
                    "status": "completed",
                    "task_id": "call-old:todo-same",
                    "result_summary": "old result",
                }
            ],
            "sandbox": None,
            "thread_data": None,
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[
            {"content": "读《甲书》：查税制", "status": "in_progress"},
        ],
        tool_call_id="call-new",
    )

    todos = command.update["todos"]
    assert launched_task_ids == ["call-new:todo-same"]
    assert todos[0]["task_id"] == "call-new:todo-same"
    assert todos[0]["status"] == "completed"
    assert todos[0]["result"] == "rerun: call-new:todo-same"


def test_write_todos_marks_matching_reading_set_book_as_covered_on_completion(monkeypatch):
    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
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
            status=FakeStatus.COMPLETED,
            started_at=None,
            completed_at=None,
            result="## 任务结果\n已核对《甲书》的相关证据。\n\n## 关键发现\n- 《甲书》提供了这一问题的关键证据。",
            error=None,
            ai_messages=[],
            structured_result={
                "summary": "已核对《甲书》的相关证据。",
                "findings": ["《甲书》提供了这一问题的关键证据。"],
                "citations": [],
                "open_questions": [],
            },
        ),
    )

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
        max_concurrent_subagents=2,
    )
    runtime = SimpleNamespace(
        state={
            "todos": [],
            "sandbox": None,
            "thread_data": None,
            "messages": [SimpleNamespace(type="human")],
            "knowledge_reading_set_doc_ids": ["doc-a", "doc-b"],
            "knowledge_reading_set_titles": {"doc-a": "甲书", "doc-b": "乙书"},
            "knowledge_covered_doc_ids": [],
            "knowledge_reading_set_query": "请综合两本书回答",
            "knowledge_reading_set_human_index": 0,
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    middleware.tools[0].func(
        runtime=runtime,
        todos=[{"content": "读《甲书》：查税制", "status": "in_progress"}],
        tool_call_id="call-cover",
    )

    assert runtime.state["knowledge_covered_doc_ids"] == ["doc-a"]


def test_write_todos_rejects_nonexistent_doc_ids(monkeypatch):
    from src.community.knowledge_base.catalog import BookCatalogEntry

    valid_entry = BookCatalogEntry(
        doc_id="real-doc-id",
        title="真实的书",
        filename="real.txt",
        scope="global",
        source_path="/path/real.txt",
        source_url="/api/knowledge/docs/real.txt",
        original_url=None,
        preview="",
        search_text="",
        search_tokens=[],
    )

    monkeypatch.setattr(
        todo_module,
        "log_subtask_event",
        lambda *a, **kw: None,
    )

    import src.community.knowledge_base.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "list_book_catalog", lambda **kwargs: [valid_entry])

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=True,
    )
    runtime = SimpleNamespace(
        state={"todos": [], "sandbox": None, "thread_data": None},
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[
            {
                "content": "查曾国藩",
                "status": "in_progress",
                "assigned_books": [{"doc_id": "曾国藩全集12册.pdf", "title": "曾国藩全集"}],
            }
        ],
        tool_call_id="call-bad-doc",
    )

    msg = command.update["messages"][0]
    assert msg.status == "error"
    assert "曾国藩全集12册.pdf" in msg.content
    assert "book_search" in msg.content
    assert "todos" not in command.update


def test_write_todos_passes_when_doc_ids_are_valid(monkeypatch):
    from src.community.knowledge_base.catalog import BookCatalogEntry

    valid_entry = BookCatalogEntry(
        doc_id="real-doc-id",
        title="真实的书",
        filename="real.txt",
        scope="global",
        source_path="/path/real.txt",
        source_url="/api/knowledge/docs/real.txt",
        original_url=None,
        preview="",
        search_text="",
        search_tokens=[],
    )

    import src.community.knowledge_base.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "list_book_catalog", lambda **kwargs: [valid_entry])
    monkeypatch.setattr(todo_module, "get_stream_writer", lambda: lambda event: None)
    monkeypatch.setattr(todo_module, "get_skills_prompt_section", lambda: "")
    import src.tools as tools_module

    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(todo_module, "get_subagent_config", lambda name: None)

    middleware = todo_module.TodoListMiddleware(
        system_prompt="test",
        tool_description="test",
        subagent_enabled=False,
    )
    runtime = SimpleNamespace(
        state={"todos": [], "sandbox": None, "thread_data": None},
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model", "trace_id": "trace-1"}},
    )

    command = middleware.tools[0].func(
        runtime=runtime,
        todos=[
            {
                "content": "查真实书",
                "status": "in_progress",
                "assigned_books": [{"doc_id": "real-doc-id", "title": "真实的书"}],
            }
        ],
        tool_call_id="call-good-doc",
    )

    # No error — normal board update
    msg = command.update["messages"][0]
    assert getattr(msg, "status", None) != "error"
    assert "todos" in command.update
