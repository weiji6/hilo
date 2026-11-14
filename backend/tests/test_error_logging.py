import json

from src.utils import error_logging


def test_write_unhandled_error_appends_jsonl(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(error_logging, "_CONFIGURED", True)
    monkeypatch.setattr(error_logging, "get_unhandled_error_log_path", lambda: tmp_path / "backend-unhandled.log")

    error_logging.write_unhandled_error(
        location="gateway.request",
        error="boom",
        context={"method": "POST", "path": "/api/demo"},
    )

    lines = (tmp_path / "backend-unhandled.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["location"] == "gateway.request"
    assert payload["error"] == "boom"
    assert payload["context"] == {"method": "POST", "path": "/api/demo"}
