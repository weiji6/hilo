"""Middleware to inject uploaded files information into agent context."""

import json
import re
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.community.knowledge_base.ingestion import list_ingestion_records
from src.config.paths import Paths, get_paths

# Maximum number of characters of parsed document content to inject per file.
# ~50 k Chinese chars ≈ 75 k tokens — well within modern context windows.
_MAX_PARSED_CHARS = 50_000
# Never inject more than this many pages per file.
_MAX_PARSED_PAGES = 300


class UploadsMiddlewareState(AgentState):
    """State schema for uploads middleware."""

    uploaded_files: NotRequired[list[dict] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """Middleware to inject uploaded files information into the agent context.

    This middleware lists all files in the thread's uploads directory and
    adds a system message with the file list before the agent processes the request.
    """

    state_schema = UploadsMiddlewareState

    def __init__(self, base_dir: str | None = None):
        """Initialize the middleware.

        Args:
            base_dir: Base directory for thread data. Defaults to Paths resolution.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()

    def _get_uploads_dir(self, thread_id: str) -> Path:
        """Get the uploads directory for a thread.

        Args:
            thread_id: The thread ID.

        Returns:
            Path to the uploads directory.
        """
        return self._paths.sandbox_uploads_dir(thread_id)

    def _list_newly_uploaded_files(self, thread_id: str, last_message_files: set[str]) -> list[dict]:
        """List only newly uploaded files that weren't in the last message.

        Args:
            thread_id: The thread ID.
            last_message_files: Set of filenames that were already shown in previous messages.

        Returns:
            List of new file information dictionaries (including ingestion metadata
            so that parsed content can be injected downstream).
        """
        uploads_dir = self._get_uploads_dir(thread_id)

        if not uploads_dir.exists():
            return []

        # Build a quick lookup from source_filename → ingestion record so we can
        # surface parse_status and the structured JSON path in one pass.
        ingestion_by_filename: dict[str, dict] = {
            r["source_filename"]: r
            for r in list_ingestion_records(thread_id)
            if r.get("source_filename")
        }

        files = []
        for file_path in sorted(uploads_dir.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.name in last_message_files:
                continue
            stat = file_path.stat()
            record = ingestion_by_filename.get(file_path.name, {})
            files.append(
                {
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "path": f"/mnt/user-data/uploads/{file_path.name}",
                    "extension": file_path.suffix,
                    # Ingestion metadata (may be empty dict if record not found yet)
                    "parse_status": record.get("parse_status"),
                    "structured_path": record.get("structured_path"),
                }
            )

        return files

    def _load_parsed_content(self, file_info: dict) -> str | None:
        """Load the OCR-parsed text of a file from its structured JSON, if available.

        Returns a plain-text representation suitable for direct injection into the
        LLM context, or None if the file has not been parsed yet.
        """
        parse_status = file_info.get("parse_status")
        if parse_status not in ("parsed", "indexed"):
            return None

        structured_path = file_info.get("structured_path")
        if not structured_path:
            return None

        path = Path(str(structured_path))
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)

            # For markdown-based providers, inject full_text directly so that
            # blank lines and markdown formatting are preserved verbatim.
            if payload.get("provider") == "mineru_api":
                full_text: str = (payload.get("full_text") or "").strip()
                if not full_text:
                    return None
                if len(full_text) > _MAX_PARSED_CHARS:
                    full_text = full_text[:_MAX_PARSED_CHARS]
                    full_text += "\n\n[... 文档内容较长，已截断。如需完整内容请使用 knowledge_locate_tool ...]"
                return full_text

            pages: list[dict] = payload.get("pages", [])
            lines: list[str] = []
            char_count = 0

            for page in pages[:_MAX_PARSED_PAGES]:
                page_no = page.get("pdf_page_no") or page.get("page_no") or "?"
                page_paras: list[str] = []
                for para in page.get("paragraphs", []):
                    text = (para.get("text") or "").strip()
                    if text:
                        page_paras.append(text)
                        char_count += len(text)

                if page_paras:
                    lines.append(f"[第 {page_no} 页]")
                    lines.extend(page_paras)
                    lines.append("")

                if char_count >= _MAX_PARSED_CHARS:
                    lines.append(
                        "[... 文档内容较长，已截断。如需完整内容请使用 knowledge_locate_tool ...]"
                    )
                    break

            return "\n".join(lines).strip() or None

        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to load parsed content for %s", file_info.get("filename", "?")
            )
            return None

    def _create_files_message(self, files: list[dict]) -> str:
        """Create a formatted message listing uploaded files.

        If a file has been OCR-parsed, its full text is inlined so the LLM can
        reference it directly without additional tool calls.

        Args:
            files: List of file information dictionaries (from _list_newly_uploaded_files).

        Returns:
            Formatted string suitable for prepending to the last human message.
        """
        if not files:
            return "<uploaded_files>\nNo files have been uploaded yet.\n</uploaded_files>"

        lines = ["<uploaded_files>", "The following files have been uploaded and are available for use:", ""]
        any_unparsed = False

        for file in files:
            size_kb = file["size"] / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"

            # Header line — keep the "- filename (size)" format so that
            # _extract_files_from_message() can still de-duplicate correctly.
            lines.append(f"- {file['filename']} ({size_str})")
            lines.append(f"  Path: {file['path']}")

            parsed_content = self._load_parsed_content(file)
            if parsed_content:
                lines.append("  <parsed_content>")
                # Indent each line slightly so the block is visually nested
                for content_line in parsed_content.splitlines():
                    lines.append(f"  {content_line}" if content_line else "")
                lines.append("  </parsed_content>")
            else:
                any_unparsed = True

            lines.append("")

        if any_unparsed:
            lines.append(
                "You can read unparsed files using the `read_file` tool with the paths shown above."
            )
        lines.append("</uploaded_files>")

        return "\n".join(lines)

    def _extract_files_from_message(self, content: str) -> set[str]:
        """Extract filenames from uploaded_files tag in message content.

        Args:
            content: Message content that may contain <uploaded_files> tag.

        Returns:
            Set of filenames mentioned in the tag.
        """
        # Match <uploaded_files>...</uploaded_files> tag
        match = re.search(r"<uploaded_files>([\s\S]*?)</uploaded_files>", content)
        if not match:
            return set()

        files_content = match.group(1)

        # Extract filenames from lines like "- filename.ext (size)"
        # Need to capture everything before the opening parenthesis, including spaces
        filenames = set()
        for line in files_content.split("\n"):
            # Match pattern: - filename with spaces.ext (size)
            # Changed from [^\s(]+ to [^(]+ to allow spaces in filename
            file_match = re.match(r"^-\s+(.+?)\s*\(", line.strip())
            if file_match:
                filenames.add(file_match.group(1).strip())

        return filenames

    @override
    def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject uploaded files information before agent execution.

        Only injects files that weren't already shown in previous messages.
        Prepends file info to the last human message content.

        Args:
            state: Current agent state.
            runtime: Runtime context containing thread_id.

        Returns:
            State updates including uploaded files list.
        """
        import logging

        logger = logging.getLogger(__name__)

        thread_id = runtime.context.get("thread_id")
        if thread_id is None:
            return None

        messages = list(state.get("messages", []))
        if not messages:
            return None

        # Track all filenames that have been shown in previous messages (EXCEPT the last one)
        shown_files: set[str] = set()
        for msg in messages[:-1]:  # Scan all messages except the last one
            if isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else ""
                extracted = self._extract_files_from_message(content)
                shown_files.update(extracted)
                if extracted:
                    logger.info(f"Found previously shown files: {extracted}")

        logger.info(f"Total shown files from history: {shown_files}")

        # List only newly uploaded files
        files = self._list_newly_uploaded_files(thread_id, shown_files)
        logger.info(f"Newly uploaded files to inject: {[f['filename'] for f in files]}")

        if not files:
            return None

        # Find the last human message and prepend file info to it
        last_message_index = len(messages) - 1
        last_message = messages[last_message_index]

        if not isinstance(last_message, HumanMessage):
            return None

        # Create files message and prepend to the last human message content
        files_message = self._create_files_message(files)

        # Extract original content - handle both string and list formats
        original_content = ""
        if isinstance(last_message.content, str):
            original_content = last_message.content
        elif isinstance(last_message.content, list):
            # Content is a list of content blocks (e.g., [{"type": "text", "text": "..."}])
            text_parts = []
            for block in last_message.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            original_content = "\n".join(text_parts)

        logger.info(f"Original message content: {original_content[:100] if original_content else '(empty)'}")

        # Create new message with combined content
        updated_message = HumanMessage(
            content=f"{files_message}\n\n{original_content}",
            id=last_message.id,
            additional_kwargs=last_message.additional_kwargs,
        )

        # Replace the last message
        messages[last_message_index] = updated_message

        return {
            "uploaded_files": files,
            "messages": messages,
        }
