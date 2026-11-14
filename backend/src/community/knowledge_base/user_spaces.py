"""Lightweight folder-style knowledge spaces for per-user knowledge records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.config.paths import get_paths

DEFAULT_KNOWLEDGE_SPACE_ID = "ks_default"
PUBLIC_KNOWLEDGE_SPACE_ID = "ks_public"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spaces_file_path(user_id: str):
    return get_paths().user_knowledge_dir(user_id) / ".spaces.json"


def _default_personal_space() -> dict[str, Any]:
    now = _utc_now()
    return {
        "id": DEFAULT_KNOWLEDGE_SPACE_ID,
        "name": "默认个人知识库",
        "description": "默认资料文件夹",
        "type": "personal",
        "readonly": False,
        "is_default": True,
        "created_at": now,
        "updated_at": now,
    }


def _public_space() -> dict[str, Any]:
    now = _utc_now()
    return {
        "id": PUBLIC_KNOWLEDGE_SPACE_ID,
        "name": "公共知识库",
        "description": "只读公共资料区，可浏览和导入到个人知识库",
        "type": "public",
        "readonly": True,
        "is_default": False,
        "created_at": now,
        "updated_at": now,
    }


def _normalize_space_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    space_id = str(raw.get("id") or "").strip()
    if not space_id:
        return None

    space_type = str(raw.get("type") or "personal").strip().lower()
    if space_type not in {"personal", "public"}:
        space_type = "personal"

    name = str(raw.get("name") or "").strip() or "未命名知识库"
    description = str(raw.get("description") or "").strip()
    readonly = bool(raw.get("readonly", space_type == "public"))
    is_default = bool(raw.get("is_default", space_id == DEFAULT_KNOWLEDGE_SPACE_ID))
    created_at = str(raw.get("created_at") or _utc_now())
    updated_at = str(raw.get("updated_at") or created_at)
    return {
        "id": space_id,
        "name": name,
        "description": description,
        "type": space_type,
        "readonly": readonly,
        "is_default": is_default,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _load_personal_spaces(user_id: str) -> list[dict[str, Any]]:
    get_paths().ensure_user_knowledge_dirs(user_id)
    path = _spaces_file_path(user_id)
    default_space = _default_personal_space()

    if not path.exists():
        payload = {"spaces": [default_space]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return [default_space]

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {"spaces": []}

    raw_spaces = payload.get("spaces")
    if not isinstance(raw_spaces, list):
        raw_spaces = []

    spaces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_spaces:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_space_payload(item)
        if not normalized or normalized["type"] != "personal":
            continue
        if normalized["id"] in seen:
            continue
        seen.add(normalized["id"])
        spaces.append(normalized)

    if DEFAULT_KNOWLEDGE_SPACE_ID not in seen:
        spaces.insert(0, default_space)
        _save_personal_spaces(user_id, spaces)
        return spaces

    spaces.sort(key=lambda item: (not item.get("is_default", False), str(item.get("created_at") or "")))
    return spaces


def _save_personal_spaces(user_id: str, spaces: list[dict[str, Any]]) -> None:
    path = _spaces_file_path(user_id)
    payload = {"spaces": spaces}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_user_knowledge_spaces(user_id: str) -> list[dict[str, Any]]:
    spaces = _load_personal_spaces(user_id)
    return [*spaces, _public_space()]


def list_user_knowledge_spaces(user_id: str) -> list[dict[str, Any]]:
    return ensure_user_knowledge_spaces(user_id)


def get_default_knowledge_space(user_id: str) -> dict[str, Any]:
    for space in ensure_user_knowledge_spaces(user_id):
        if space.get("id") == DEFAULT_KNOWLEDGE_SPACE_ID:
            return space
    return _default_personal_space()


def get_user_knowledge_space_map(user_id: str) -> dict[str, dict[str, Any]]:
    return {
        str(space.get("id")): space
        for space in ensure_user_knowledge_spaces(user_id)
        if space.get("id")
    }


def create_user_knowledge_space(
    user_id: str,
    *,
    name: str,
    description: str = "",
) -> dict[str, Any]:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("name is required")

    spaces = _load_personal_spaces(user_id)
    now = _utc_now()
    new_space = {
        "id": f"ks_{uuid4().hex[:12]}",
        "name": normalized_name,
        "description": description.strip(),
        "type": "personal",
        "readonly": False,
        "is_default": False,
        "created_at": now,
        "updated_at": now,
    }
    spaces.append(new_space)
    _save_personal_spaces(user_id, spaces)
    return new_space


def delete_user_knowledge_space(user_id: str, space_id: str) -> dict[str, Any]:
    normalized_space_id = str(space_id or "").strip()
    if not normalized_space_id:
        raise ValueError("space_id is required")
    if normalized_space_id == DEFAULT_KNOWLEDGE_SPACE_ID:
        raise ValueError("Default knowledge space cannot be deleted")
    if normalized_space_id == PUBLIC_KNOWLEDGE_SPACE_ID:
        raise ValueError("Public knowledge space cannot be deleted")

    spaces = _load_personal_spaces(user_id)
    target = next((space for space in spaces if str(space.get("id")) == normalized_space_id), None)
    if target is None:
        raise ValueError("Knowledge space not found")

    remaining = [space for space in spaces if str(space.get("id")) != normalized_space_id]
    _save_personal_spaces(user_id, remaining)
    return target
