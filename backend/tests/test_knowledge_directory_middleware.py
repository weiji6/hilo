from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from src.community.knowledge_base.catalog import BookCatalogEntry

if "langchain.agents" not in sys.modules:
    langchain_agents = ModuleType("langchain.agents")

    class _DummyAgentState(dict):
        pass

    langchain_agents.AgentState = _DummyAgentState
    sys.modules["langchain.agents"] = langchain_agents

if "langchain.agents.middleware" not in sys.modules:
    langchain_agents_middleware = ModuleType("langchain.agents.middleware")

    class _DummyAgentMiddleware:
        def __class_getitem__(cls, _item):
            return cls

    langchain_agents_middleware.AgentMiddleware = _DummyAgentMiddleware
    sys.modules["langchain.agents.middleware"] = langchain_agents_middleware

if "langchain.agents.middleware.types" not in sys.modules:
    langchain_agents_middleware_types = ModuleType("langchain.agents.middleware.types")
    langchain_agents_middleware_types.ModelCallResult = object
    langchain_agents_middleware_types.ModelRequest = object
    langchain_agents_middleware_types.ModelResponse = object
    sys.modules["langchain.agents.middleware.types"] = langchain_agents_middleware_types

_MIDDLEWARE_SPEC = importlib.util.spec_from_file_location(
    "test_knowledge_directory_middleware_module",
    Path(__file__).parent.parent / "src/agents/middlewares/knowledge_directory_middleware.py",
)
knowledge_directory_middleware = importlib.util.module_from_spec(_MIDDLEWARE_SPEC)
assert _MIDDLEWARE_SPEC and _MIDDLEWARE_SPEC.loader
_MIDDLEWARE_SPEC.loader.exec_module(knowledge_directory_middleware)
KnowledgeDirectoryMiddleware = knowledge_directory_middleware.KnowledgeDirectoryMiddleware


@pytest.fixture(autouse=True)
def _clear_directory_cache():
    with knowledge_directory_middleware._directory_block_cache_lock:
        knowledge_directory_middleware._directory_block_cache.clear()


@dataclass(frozen=True)
class _DummyRequest:
    runtime: object
    system_message: SystemMessage | None
    messages: list[object]

    def override(self, **overrides):
        return replace(self, **overrides)


def test_knowledge_directory_middleware_injects_tree_into_hidden_user_message(monkeypatch) -> None:
    middleware = KnowledgeDirectoryMiddleware()
    entries = [
        BookCatalogEntry(
            doc_id="uk_1",
            title="晚清财政史料",
            filename="late-qing.pdf",
            scope="user",
            source_path="/tmp/late-qing.pdf",
            source_url="/api/secure-knowledge/users/me/knowledge/docs/late-qing.pdf",
            original_url=None,
            preview="",
            search_text="晚清财政史料 财政史 清代 晚清",
            search_tokens=["晚清财政史料", "财政史", "清代", "晚清"],
            type="user",
            folder_path="财政史/清代/晚清",
            page_count=420,
        )
    ]
    monkeypatch.setattr(
        knowledge_directory_middleware,
        "list_book_catalog",
        lambda thread_id=None, user_id=None, **kwargs: entries,
    )

    captured: dict[str, object] = {}

    def handler(request):
        captured["system_message"] = request.system_message
        captured["messages"] = request.messages
        return "ok"

    request = _DummyRequest(
        runtime=SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        system_message=SystemMessage(content="base-system"),
        messages=[],
    )

    result = middleware.wrap_model_call(request, handler)

    assert result == "ok"
    system_message = captured["system_message"]
    assert isinstance(system_message, SystemMessage)
    assert "base-system" in str(system_message.content)
    messages = captured["messages"]
    assert isinstance(messages[0], HumanMessage)
    content = str(messages[0].content)
    assert "<knowledge_directory_tree>" in content
    assert "`knowledge_folders`" in content
    assert "不是 sandbox / 容器 / 本地文件系统路径" in content
    # Scope sections are rendered as 【…】 headers, NOT as path segments. Book
    # titles / doc_id are no longer leaked into the tree — the agent must use
    # ``book_search`` to look those up.
    assert "【用户书籍】" in content
    assert "用户书籍/" not in content  # not a path segment
    assert "财政史/" in content
    assert "(420页)" in content  # rollup page count at the leaf folder
    assert "晚清财政史料" not in content
    assert "doc_id=uk_1" not in content


def test_knowledge_directory_middleware_does_not_mistake_prompt_reference_for_injected_tree(monkeypatch) -> None:
    middleware = KnowledgeDirectoryMiddleware()
    entries = [
        BookCatalogEntry(
            doc_id="g_1",
            title="盛宣怀档案",
            filename="sheng.pdf",
            scope="global",
            source_path="/tmp/sheng.pdf",
            source_url="/api/knowledge/docs/sheng.pdf",
            original_url=None,
            preview="",
            search_text="盛宣怀档案 晚清人物",
            search_tokens=["盛宣怀档案", "晚清人物"],
            folder_path="清史/晚清名人名臣集/盛宣怀档案",
        )
    ]
    monkeypatch.setattr(
        knowledge_directory_middleware,
        "list_book_catalog",
        lambda thread_id=None, user_id=None, **kwargs: entries,
    )

    captured: dict[str, object] = {}

    def handler(request):
        captured["messages"] = request.messages
        return "ok"

    request = _DummyRequest(
        runtime=SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        system_message=SystemMessage(
            content="rules mention <knowledge_directory_tree> as a concept, but it is not injected yet"
        ),
        messages=[],
    )

    result = middleware.wrap_model_call(request, handler)

    assert result == "ok"
    messages = captured["messages"]
    assert isinstance(messages[0], HumanMessage)
    content = str(messages[0].content)
    assert content.startswith("<knowledge_directory_tree>")
    # The fixture entry's folder lands under the 【系统知识库】 section.
    assert "【系统知识库】" in content
    assert "清史/" in content


def test_knowledge_directory_middleware_injects_empty_folder_candidates(monkeypatch, tmp_path) -> None:
    middleware = KnowledgeDirectoryMiddleware()
    monkeypatch.setattr(
        knowledge_directory_middleware,
        "list_book_catalog",
        lambda thread_id=None, user_id=None, **kwargs: [],
    )
    monkeypatch.setattr(
        knowledge_directory_middleware,
        "get_knowledge_base_config",
        lambda: SimpleNamespace(docs_path=str(tmp_path / "docs")),
    )
    monkeypatch.setattr(
        knowledge_directory_middleware,
        "resolve_project_path",
        lambda path: tmp_path / "docs",
    )
    monkeypatch.setattr(
        knowledge_directory_middleware,
        "get_paths",
        lambda: SimpleNamespace(
            user_knowledge_docs_dir=lambda user_id: tmp_path / "users" / user_id / "knowledge" / "docs"
        ),
    )

    def fake_list_folder_paths(path):
        path_text = str(path)
        if "users/user-1" in path_text:
            return ["用户资料/未整理"]
        return ["系统资料/待归档"]

    monkeypatch.setattr(
        knowledge_directory_middleware,
        "list_folder_paths",
        fake_list_folder_paths,
    )

    captured: dict[str, object] = {}

    def handler(request):
        captured["system_message"] = request.system_message
        captured["messages"] = request.messages
        return "ok"

    request = _DummyRequest(
        runtime=SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1"}),
        system_message=SystemMessage(content="base-system"),
        messages=[],
    )

    result = middleware.wrap_model_call(request, handler)

    assert result == "ok"
    system_message = captured["system_message"]
    assert isinstance(system_message, SystemMessage)
    assert "base-system" in str(system_message.content)
    messages = captured["messages"]
    assert isinstance(messages[0], HumanMessage)
    assert "<empty_knowledge_folders>" in str(messages[0].content)
    assert "用户空文件夹" in str(messages[0].content)
    assert "用户资料/未整理" in str(messages[0].content)
    assert "系统知识库空文件夹" in str(messages[0].content)
    assert "系统资料/待归档" in str(messages[0].content)
