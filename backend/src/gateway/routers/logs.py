"""Log viewer endpoints for operational diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.utils.error_logging import get_error_log_path
from src.utils.subtask_logging import get_subtask_log_path

router = APIRouter(prefix="/api/logs", tags=["logs"])

_ALLOWED_LOGS = {
    "subtasks": get_subtask_log_path,
    "errors": get_error_log_path,
}


def _tail_file(path: Path, lines: int) -> list[str]:
    """Return the last `lines` lines of a file efficiently."""
    if not path.exists():
        return []
    with path.open("rb") as f:
        # Seek from the end and collect chunks until we have enough newlines
        chunk_size = 8192
        collected: list[bytes] = []
        newline_count = 0
        f.seek(0, 2)  # end of file
        remaining = f.tell()
        while remaining > 0 and newline_count <= lines:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            f.seek(remaining)
            chunk = f.read(read_size)
            collected.append(chunk)
            newline_count += chunk.count(b"\n")
        raw = b"".join(reversed(collected)).decode("utf-8", errors="replace")
        all_lines = raw.splitlines()
        return all_lines[-lines:] if len(all_lines) > lines else all_lines


@router.get("/{log_name}", response_class=PlainTextResponse)
async def get_log(
    log_name: str,
    n: int = Query(default=200, ge=1, le=5000, description="Number of tail lines to return"),
    fmt: str = Query(default="text", description="Output format: 'text' or 'json'"),
) -> PlainTextResponse:
    """Tail a named log file.

    Available logs:
    - **subtasks** — structured JSON lines from subagent task execution
    - **errors** — backend error log

    Pass `?fmt=json` to get a JSON array of parsed log entries (subtasks log only).
    Pass `?n=500` to get more lines (default 200, max 5000).
    """
    if log_name not in _ALLOWED_LOGS:
        raise HTTPException(status_code=404, detail=f"Unknown log '{log_name}'. Available: {list(_ALLOWED_LOGS)}")

    path = _ALLOWED_LOGS[log_name]()
    lines = _tail_file(path, n)

    if fmt == "json":
        parsed = []
        for line in lines:
            try:
                # subtask log format: "TIMESTAMP | LEVEL | LOGGER | {json}"
                json_part = line.split("| ")[-1].strip()
                parsed.append(json.loads(json_part))
            except Exception:
                parsed.append({"raw": line})
        return PlainTextResponse(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            media_type="application/json",
        )

    return PlainTextResponse("\n".join(lines), media_type="text/plain")


@router.get("/{log_name}/timing", response_class=PlainTextResponse)
async def get_timing_summary(
    log_name: str = "subtasks",
) -> PlainTextResponse:
    """Return a human-readable timing summary from the subtasks log.

    Shows per-subagent LLM vs tool time breakdown from `subtask_timing_summary` events.
    """
    if log_name != "subtasks":
        raise HTTPException(status_code=400, detail="Timing summary only available for 'subtasks' log")

    path = _ALLOWED_LOGS["subtasks"]()
    lines = _tail_file(path, 5000)

    records: list[dict] = []
    for line in lines:
        try:
            json_part = line.split("| ")[-1].strip()
            data = json.loads(json_part)
            if data.get("event") == "subtask_timing_summary":
                records.append(data)
        except Exception:
            pass

    if not records:
        return PlainTextResponse("No timing summary records found yet.", media_type="text/plain")

    rows = ["task_id                  | subagent            | llm_calls | llm_total_s | tool_calls | tool_total_s | total_s"]
    rows.append("-" * 110)
    for r in records[-50:]:  # most recent 50
        rows.append(
            f"{r.get('task_id', ''):<24} | {r.get('subagent_name', ''):<19} | "
            f"{r.get('llm_calls', 0):>9} | {r.get('llm_total_s', 0):>11.1f} | "
            f"{r.get('tool_calls', 0):>10} | {r.get('tool_total_s', 0):>12.1f} | "
            f"{r.get('total_s', 0):>7.1f}"
        )

    return PlainTextResponse("\n".join(rows), media_type="text/plain")
