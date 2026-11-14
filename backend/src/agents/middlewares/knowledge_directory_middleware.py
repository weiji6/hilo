"""Inject a knowledge-directory tree into the system prompt at runtime."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from threading import Lock

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage

from src.community.knowledge_base.book_metadata import normalize_folder_path
from src.community.knowledge_base.catalog import (
    filter_book_catalog_entries,
    list_book_catalog,
    render_book_catalog_directory_tree,
)
from src.community.knowledge_base.common import resolve_project_path
from src.community.knowledge_base.folder_registry import list_folder_paths
from src.config.knowledge_base_config import get_knowledge_base_config
from src.config.paths import get_paths

logger = logging.getLogger(__name__)
KNOWLEDGE_DIRECTORY_TAG = "<knowledge_directory_tree>"
KNOWLEDGE_DIRECTORY_CACHE_TTL_SECONDS = 15.0
_directory_block_cache: dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], tuple[float, str]] = {}
_directory_block_cache_lock = Lock()


def _coerce_runtime_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = [item.strip() for item in value.split(",") if item.strip()]
        return parsed or None
    if isinstance(value, (list, tuple, set)):
        parsed = [str(item).strip() for item in value if str(item).strip()]
        return parsed or None
    return None


def _message_preview(message: object, *, max_chars: int = 240) -> str:
    content = str(getattr(message, "content", "") or "").replace("\n", "\\n")
    return content[:max_chars]


def _contains_injected_directory_block(message: object) -> bool:
    content = str(getattr(message, "content", "") or "").strip()
    return content.startswith(KNOWLEDGE_DIRECTORY_TAG) and "</knowledge_directory_tree>" in content


def _directory_cache_key(request: ModelRequest) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    runtime_context = request.runtime.context
    return (
        str(runtime_context.get("thread_id") or ""),
        str(runtime_context.get("user_id") or ""),
        tuple(_coerce_runtime_string_list(runtime_context.get("selected_doc_ids")) or ()),
        tuple(_coerce_runtime_string_list(runtime_context.get("selected_sources_scope")) or ()),
    )


def _get_cached_directory_block(
    key: tuple[str, str, tuple[str, ...], tuple[str, ...]],
) -> str | None:
    now = time.perf_counter()
    with _directory_block_cache_lock:
        cached = _directory_block_cache.get(key)
        if cached is None:
            return None
        expires_at, content = cached
        if expires_at <= now:
            _directory_block_cache.pop(key, None)
            return None
        return content


def _store_cached_directory_block(
    key: tuple[str, str, tuple[str, ...], tuple[str, ...]],
    content: str,
) -> None:
    with _directory_block_cache_lock:
        _directory_block_cache[key] = (
            time.perf_counter() + KNOWLEDGE_DIRECTORY_CACHE_TTL_SECONDS,
            content,
        )


class KnowledgeDirectoryMiddleware(AgentMiddleware[AgentState]):
    """Add a runtime knowledge tree to the system context for source navigation."""

    def _visible_entries(self, request: ModelRequest) -> list:
        started_at = time.perf_counter()
        runtime_context = request.runtime.context
        entries = list_book_catalog(
            thread_id=runtime_context.get("thread_id"),
            user_id=runtime_context.get("user_id"),
            include_search_content=False,
            caller="KnowledgeDirectoryMiddleware._visible_entries",
        )
        filtered = filter_book_catalog_entries(
            entries,
            doc_ids=_coerce_runtime_string_list(runtime_context.get("selected_doc_ids")),
            scopes=_coerce_runtime_string_list(runtime_context.get("selected_sources_scope")),
        )
        logger.info(
            "KnowledgeDirectory visible entries built: total=%s filtered=%s thread_id=%s has_user=%s elapsed_ms=%.1f",
            len(entries),
            len(filtered),
            runtime_context.get("thread_id"),
            bool(runtime_context.get("user_id")),
            (time.perf_counter() - started_at) * 1000,
        )
        return filtered

    def _occupied_folder_paths_by_scope(self, entries: list) -> dict[str, set[str]]:
        occupied: dict[str, set[str]] = {"user": set(), "global": set()}
        for entry in entries:
            scope = str(getattr(entry, "scope", "") or "")
            if scope not in occupied:
                continue
            normalized = normalize_folder_path(getattr(entry, "folder_path", None))
            if not normalized:
                continue
            parts = normalized.split("/")
            for index in range(1, len(parts) + 1):
                occupied[scope].add("/".join(parts[:index]))
        return occupied

    def _build_empty_folder_section(self, request: ModelRequest, entries: list) -> str | None:
        started_at = time.perf_counter()
        runtime_context = request.runtime.context
        if _coerce_runtime_string_list(runtime_context.get("selected_doc_ids")):
            return None

        selected_scopes = set(_coerce_runtime_string_list(runtime_context.get("selected_sources_scope")) or ["user", "thread", "global"])
        occupied = self._occupied_folder_paths_by_scope(entries)
        sections: list[tuple[str, list[str]]] = []

        if "user" in selected_scopes and runtime_context.get("user_id"):
            user_id = str(runtime_context["user_id"])
            registry_path = get_paths().user_knowledge_docs_dir(user_id).parent / ".folders.json"
            user_folders = [
                folder
                for folder in list_folder_paths(registry_path)
                if folder not in occupied["user"]
            ]
            if user_folders:
                sections.append(("用户空文件夹", user_folders))

        if "global" in selected_scopes:
            docs_root = resolve_project_path(get_knowledge_base_config().docs_path)
            registry_path = docs_root / ".folders.json"
            global_folders = [
                folder
                for folder in list_folder_paths(registry_path)
                if folder not in occupied["global"]
            ]
            if global_folders:
                sections.append(("系统知识库空文件夹", global_folders))

        if not sections:
            logger.info(
                "KnowledgeDirectory empty folder section skipped: entries=%s elapsed_ms=%.1f",
                len(entries),
                (time.perf_counter() - started_at) * 1000,
            )
            return None

        lines = [
            "<empty_knowledge_folders>",
            "下面这些空文件夹当前还没有文档，但可以作为归档或后续检索的候选目录：",
            "",
        ]
        for title, folders in sections:
            lines.append(f"{title}:")
            for folder in folders:
                lines.append(f"- {folder}")
            lines.append("")
        lines.append("</empty_knowledge_folders>")
        logger.info(
            "KnowledgeDirectory empty folder section built: section_count=%s elapsed_ms=%.1f",
            len(sections),
            (time.perf_counter() - started_at) * 1000,
        )
        return "\n".join(lines)

    def _has_directory_tree(self, request: ModelRequest) -> bool:
        if request.system_message and _contains_injected_directory_block(request.system_message):
            return True
        return any(_contains_injected_directory_block(message) for message in request.messages)

    def _build_directory_block(self, entries: list) -> HumanMessage | None:
        started_at = time.perf_counter()
        try:
            directory_tree = render_book_catalog_directory_tree(entries, include_scope_roots=True)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to build knowledge directory tree: %s", exc)
            return None

        if not directory_tree:
            logger.info(
                "KnowledgeDirectory directory block empty: entries=%s elapsed_ms=%.1f",
                len(entries),
                (time.perf_counter() - started_at) * 1000,
            )
            return None

        logger.info(
            "KnowledgeDirectory directory block built: entries=%s tree_lines=%s elapsed_ms=%.1f",
            len(entries),
            len(directory_tree.splitlines()),
            (time.perf_counter() - started_at) * 1000,
        )
        return HumanMessage(
            content=(
                f"{KNOWLEDGE_DIRECTORY_TAG}\n"
                "下面是当前可见知识资料的目录树。它是导航线索，不是证据。"
                "目录树**只列文件夹**、不列书名 —— 文件夹后括号里的「X页」是该文件夹及其全部子目录所含书籍的页数合计，"
                "粗略反映该话题在库中的厚度；具体书名/`doc_id` 不在这里展示，需要时由子任务用 `book_search` 取。"
                "目录被分成 `【当前线程书籍】` / `【用户书籍】` / `【系统知识库】` 三段："
                "**优先尊重「当前线程书籍」和「用户书籍」分支下的资料**，"
                "因为那是用户主动上传/整理的；「系统知识库」是共享语料，用于补充而不是替代。"
                "`【…】` 只是分段标题、不是路径段；填 `knowledge_folders` 时只能填 `【…】` 下面那棵子树里的目录名（如 `财政史/清代`），"
                "不要把 `用户书籍`、`系统知识库` 这类段名当成路径前缀拼上去。"
                "在启用子任务时，主任务不要自行调用 `book_search` 选书；主任务只判断已有历史结果是否足够，"
                "若不足则按任务目标、证据缺口、阶段、人物、机构或机制派发子任务。"
                "`knowledge_search` 现在只检索历史主任务/子任务结果，不检索书籍正文；不要把书籍 `doc_ids` 传给 `knowledge_search`。"
                "子任务会用 `book_search` 选择相关资料、检查 metadata（尤其 `语言` / `language_hint`、目录、摘要），"
                "再用 `knowledge_locate` 读目录、章节页、命中页或连续页正文。"
                "如果涉及多本书，不要在主任务里继续串行深挖，也不要把任务预先硬绑到某本书。"
                "不要填写「核心通用书」「专题支撑书」「补充材料」「参考工具书」这类目录树里未出现的层级标签 —— 它们是内部桶概念，不是可检索目录。"
                "`knowledge_folders` 是知识库逻辑目录，不是 sandbox / 容器 / 本地文件系统路径；不要用 `ls`、`read_file`、`bash` 等其他工具去推断。\n\n"
                f"{directory_tree}\n"
                "</knowledge_directory_tree>"
            )
        )

    def _inject_directory_block(self, request: ModelRequest) -> ModelRequest:
        started_at = time.perf_counter()
        if self._has_directory_tree(request):
            logger.info("Knowledge directory tree already present in model request; skipping reinjection")
            return request

        cache_key = _directory_cache_key(request)
        cached_content = _get_cached_directory_block(cache_key)
        if cached_content is not None:
            injected_message = HumanMessage(content=cached_content)
            patched_request = request.override(messages=[injected_message, *request.messages])
            logger.info(
                "KnowledgeDirectory cache hit: messages_before=%s messages_after=%s cache_ttl_seconds=%s elapsed_ms=%.1f",
                len(request.messages),
                len(patched_request.messages),
                KNOWLEDGE_DIRECTORY_CACHE_TTL_SECONDS,
                (time.perf_counter() - started_at) * 1000,
            )
            return patched_request
        logger.info(
            "KnowledgeDirectory cache miss: thread_id=%s has_user=%s selected_doc_ids=%s selected_scopes=%s",
            request.runtime.context.get("thread_id"),
            bool(request.runtime.context.get("user_id")),
            len(_coerce_runtime_string_list(request.runtime.context.get("selected_doc_ids")) or []),
            ",".join(_coerce_runtime_string_list(request.runtime.context.get("selected_sources_scope")) or []),
        )

        visible_entries = self._visible_entries(request)
        directory_message = self._build_directory_block(visible_entries)
        try:
            empty_folder_section = self._build_empty_folder_section(
                request,
                visible_entries,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Failed to build empty-folder section: %s", exc)
            empty_folder_section = None

        if directory_message is None and empty_folder_section is None:
            logger.info("No visible knowledge directory tree or empty-folder section available for injection")
            return request

        content_parts: list[str] = []
        if directory_message is not None:
            content_parts.append(str(directory_message.content))
        if empty_folder_section is not None:
            content_parts.append(empty_folder_section)
        injected_content = "\n\n".join(content_parts)
        _store_cached_directory_block(cache_key, injected_content)
        injected_message = HumanMessage(content=injected_content)
        patched_request = request.override(messages=[injected_message, *request.messages])
        logger.info(
            "Injected knowledge directory block into model request: messages_before=%s messages_after=%s first_message=%s second_message=%s elapsed_ms=%.1f",
            len(request.messages),
            len(patched_request.messages),
            _message_preview(patched_request.messages[0]) if patched_request.messages else "",
            _message_preview(patched_request.messages[1]) if len(patched_request.messages) > 1 else "",
            (time.perf_counter() - started_at) * 1000,
        )
        return patched_request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._inject_directory_block(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._inject_directory_block(request))
