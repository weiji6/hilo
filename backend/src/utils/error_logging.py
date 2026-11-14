"""Helpers for persistent error logging."""

from __future__ import annotations

import json
import logging
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.config.paths import Paths

_CONFIG_LOCK = threading.Lock()
_CONFIGURED = False
_ERROR_LOGGER_NAME = "deerflow.error_file"


def _logs_dir() -> Path:
    path = Paths().base_dir / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_error_log_path() -> Path:
    return _logs_dir() / "backend-errors.log"


def get_unhandled_error_log_path() -> Path:
    return _logs_dir() / "backend-unhandled.log"


def get_error_doc_path() -> Path:
    return _logs_dir() / "error-log.md"


def _build_rotating_handler(path: Path, *, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _install_global_exception_hooks() -> None:
    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        write_unhandled_error(
            location="sys.excepthook",
            error=str(exc_value),
            context={
                "exception_type": exc_type.__name__,
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
            },
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, KeyboardInterrupt):
            threading.__excepthook__(args)
            return
        write_unhandled_error(
            location="threading.excepthook",
            error=str(args.exc_value),
            context={
                "exception_type": args.exc_type.__name__,
                "thread_name": getattr(args.thread, "name", None),
                "traceback": "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            },
        )
        threading.__excepthook__(args)

    sys.excepthook = _handle_uncaught_exception
    threading.excepthook = _handle_thread_exception


def configure_persistent_error_logging() -> None:
    """Attach a rotating file handler for ERROR+ logs exactly once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    with _CONFIG_LOCK:
        if _CONFIGURED:
            return

        root_logger = logging.getLogger()
        root_logger.addHandler(_build_rotating_handler(get_error_log_path(), level=logging.ERROR))
        root_logger.setLevel(min(root_logger.level or logging.INFO, logging.INFO))

        # Keep a named logger for direct structured writes if needed later.
        error_logger = logging.getLogger(_ERROR_LOGGER_NAME)
        error_logger.setLevel(logging.ERROR)
        error_logger.propagate = True

        _install_global_exception_hooks()

        _CONFIGURED = True


def write_unhandled_error(
    *,
    location: str,
    error: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Persist a structured unhandled-error record for request/thread crash analysis."""
    configure_persistent_error_logging()

    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "location": location,
        "error": error,
        "context": context or {},
    }
    _append_jsonl(get_unhandled_error_log_path(), payload)


def append_error_doc(
    *,
    location: str,
    summary: str,
    error: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Append a human-readable error entry to the markdown error log."""
    configure_persistent_error_logging()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"## {timestamp} | {location}",
        "",
        f"- Summary: {summary}",
    ]
    if error:
        lines.append(f"- Error: `{error}`")
    if context:
        lines.extend(
            [
                "- Context:",
                "```json",
                json.dumps(context, ensure_ascii=False, indent=2, default=str),
                "```",
            ]
        )
    lines.append("")

    with get_error_doc_path().open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
