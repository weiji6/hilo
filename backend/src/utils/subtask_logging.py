"""Dedicated rotating log for todo/subtask dispatch diagnostics."""

from __future__ import annotations

import json
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.config.paths import Paths

_CONFIG_LOCK = threading.Lock()
_CONFIGURED = False
_LOGGER_NAME = "deerflow.subtasks"


def get_subtask_log_path() -> Path:
    path = Paths().base_dir / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / "subtasks.log"


def configure_subtask_logging() -> logging.Logger:
    global _CONFIGURED

    logger = logging.getLogger(_LOGGER_NAME)
    if _CONFIGURED:
        return logger

    with _CONFIG_LOCK:
        if _CONFIGURED:
            return logger

        handler = RotatingFileHandler(
            get_subtask_log_path(),
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        _CONFIGURED = True

    return logger


def log_subtask_event(event: str, **payload: Any) -> None:
    logger = configure_subtask_logging()
    record = {
        "event": event,
        **payload,
    }
    logger.info(json.dumps(record, ensure_ascii=False, default=str, sort_keys=True))
