"""Helpers for explicit knowledge-folder registries.

This registry stores logical folder paths so the UI can render empty folders and
support folder-level CRUD independent of whether any files currently exist in a
given branch.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.community.knowledge_base.book_metadata import normalize_folder_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_registry_entries(payload: dict[str, Any] | None) -> list[dict[str, str]]:
    raw_entries = payload.get("folders") if isinstance(payload, dict) else []
    if not isinstance(raw_entries, list):
        raw_entries = []

    seen: set[str] = set()
    entries: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        normalized_path = normalize_folder_path(item.get("path"))
        if not normalized_path or normalized_path in seen:
            continue
        seen.add(normalized_path)
        created_at = str(item.get("created_at") or _utc_now())
        updated_at = str(item.get("updated_at") or created_at)
        entries.append(
            {
                "path": normalized_path,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    entries.sort(key=lambda item: str(item.get("path") or ""))
    return entries


def load_folder_registry(path: Path) -> list[dict[str, str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return _normalize_registry_entries(payload)


def save_folder_registry(path: Path, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_entries = _normalize_registry_entries({"folders": entries})
    payload = {"folders": normalized_entries}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def expand_folder_paths(paths: Iterable[str | None]) -> list[str]:
    expanded: set[str] = set()
    for raw_path in paths:
        normalized = normalize_folder_path(raw_path)
        if not normalized:
            continue
        parts = normalized.split("/")
        for index in range(1, len(parts) + 1):
            expanded.add("/".join(parts[:index]))
    return sorted(expanded)


def list_folder_paths(path: Path) -> list[str]:
    return expand_folder_paths(entry.get("path") for entry in load_folder_registry(path))


def render_folder_tree(
    *,
    folder_paths: Iterable[str | None] = (),
    file_entries: Iterable[tuple[str | None, str]] = (),
) -> str | None:
    """Render folders plus optional files as a simple logical tree."""
    tree: dict[str, Any] = {}

    def _node_children(node: dict[str, Any]) -> dict[str, Any]:
        return node.setdefault("children", {})

    def _node_files(node: dict[str, Any]) -> list[str]:
        return node.setdefault("files", [])

    normalized_folder_paths = expand_folder_paths(folder_paths)
    for folder_path in normalized_folder_paths:
        node = tree
        for segment in folder_path.split("/"):
            node = _node_children(node).setdefault(segment, {})

    seen_files: set[tuple[str | None, str]] = set()
    for raw_folder_path, raw_filename in file_entries:
        filename = str(raw_filename or "").strip()
        if not filename:
            continue
        normalized_folder_path = normalize_folder_path(raw_folder_path)
        dedupe_key = (normalized_folder_path, filename)
        if dedupe_key in seen_files:
            continue
        seen_files.add(dedupe_key)

        node = tree
        if normalized_folder_path:
            for segment in normalized_folder_path.split("/"):
                node = _node_children(node).setdefault(segment, {})
        files = _node_files(node)
        if filename not in files:
            files.append(filename)

    if not tree:
        return None

    lines = ["."]

    def _render(node: dict[str, Any], prefix: str = "") -> None:
        folders = sorted(_node_children(node).items(), key=lambda item: item[0])
        files = sorted(_node_files(node))
        entries: list[tuple[str, str, Any]] = [("folder", name, child) for name, child in folders]
        entries.extend(("file", name, None) for name in files)

        for index, (entry_type, name, child) in enumerate(entries):
            is_last = index == len(entries) - 1
            branch = "`-- " if is_last else "|-- "
            lines.append(f"{prefix}{branch}{name}{'/' if entry_type == 'folder' else ''}")
            if entry_type == "folder":
                _render(child, prefix + ("    " if is_last else "|   "))

    _render(tree)
    return "\n".join(lines)


def ensure_folder_path(path: Path, folder_path: str) -> list[str]:
    normalized = normalize_folder_path(folder_path)
    if not normalized:
        raise ValueError("folder_path is required")

    entries = load_folder_registry(path)
    existing_paths = {str(entry.get("path") or "") for entry in entries}
    now = _utc_now()
    created = False
    for candidate in expand_folder_paths([normalized]):
        if candidate in existing_paths:
            continue
        entries.append(
            {
                "path": candidate,
                "created_at": now,
                "updated_at": now,
            }
        )
        existing_paths.add(candidate)
        created = True

    if created:
        save_folder_registry(path, entries)
    return list_folder_paths(path)


def ensure_folder_paths(path: Path, folder_paths: Iterable[str | None]) -> list[str]:
    normalized_paths = expand_folder_paths(folder_paths)
    if not normalized_paths:
        return list_folder_paths(path)

    entries = load_folder_registry(path)
    existing_paths = {str(entry.get("path") or "") for entry in entries}
    now = _utc_now()
    created = False
    for candidate in normalized_paths:
        if candidate in existing_paths:
            continue
        entries.append(
            {
                "path": candidate,
                "created_at": now,
                "updated_at": now,
            }
        )
        existing_paths.add(candidate)
        created = True

    if created:
        save_folder_registry(path, entries)
    return list_folder_paths(path)


def rename_folder_path(path: Path, old_path: str, new_path: str) -> list[str]:
    normalized_old = normalize_folder_path(old_path)
    normalized_new = normalize_folder_path(new_path)
    if not normalized_old or not normalized_new:
        raise ValueError("Both old_path and new_path are required")
    if normalized_old == normalized_new:
        return list_folder_paths(path)
    if normalized_new == normalized_old or normalized_new.startswith(f"{normalized_old}/"):
        raise ValueError("Cannot move a folder into itself")

    entries = load_folder_registry(path)
    now = _utc_now()
    next_entries: list[dict[str, str]] = []
    matched = False
    for entry in entries:
        current_path = str(entry.get("path") or "")
        if current_path == normalized_old or current_path.startswith(f"{normalized_old}/"):
            suffix = current_path[len(normalized_old) :]
            entry = {
                "path": f"{normalized_new}{suffix}",
                "created_at": str(entry.get("created_at") or now),
                "updated_at": now,
            }
            matched = True
        next_entries.append(entry)

    if not matched:
        raise ValueError("Folder not found")

    save_folder_registry(path, next_entries)
    return ensure_folder_path(path, normalized_new)


def delete_folder_path(path: Path, folder_path: str) -> list[str]:
    normalized = normalize_folder_path(folder_path)
    if not normalized:
        raise ValueError("folder_path is required")

    entries = load_folder_registry(path)
    next_entries = [
        entry
        for entry in entries
        if str(entry.get("path") or "") != normalized
        and not str(entry.get("path") or "").startswith(f"{normalized}/")
    ]
    save_folder_registry(path, next_entries)
    return list_folder_paths(path)
