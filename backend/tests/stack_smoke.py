"""Prepare or verify a disposable Hilo stack with synthetic data (stdlib only).

Never point this runner at a real deployment: it registers a test account and
creates documents, a thread and a custom Skill. Run with a fresh Compose project.
"""

import argparse
import http.cookiejar
import io
import json
import secrets
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def prepare(base_url):
    # Explicit test preparation, after init_config.py in a disposable checkout.
    (ROOT / "backend/.env").write_text("OPENAI_API_KEY=hilo-test-fixture\nOPENAI_MODEL=fixture\nOPENAI_BASE_URL=http://fixture:8080/v1\nEMBEDDING_MODEL=fixture\nEMBEDDING_BASE_URL=http://fixture:8080/v1\nTASK_MEMORY_ENABLED=false\n")
    path = ROOT / "frontend/.env"
    content = path.read_text()
    content = "\n".join(f"BETTER_AUTH_BASE_URL={base_url}" if line.startswith("BETTER_AUTH_BASE_URL=") else line for line in content.splitlines())
    path.write_text(content + "\n")
    path = ROOT / "config.yaml"
    content = path.read_text().replace("title:\n  enabled: true", "title:\n  enabled: false").replace("summarization:\n  enabled: true", "summarization:\n  enabled: false")
    path.write_text(content)
    print("Disposable stack configured with local HTTP model fixtures.", flush=True)


class Client:
    def __init__(self, base_url):
        self.base_url = base_url
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, payload=None, *, method=None, content_type="application/json"):
        data = json.dumps(payload).encode() if payload is not None and not isinstance(payload, bytes) else payload
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers={"Content-Type": content_type, "Origin": self.base_url})
        return self.opener.open(request, timeout=180)

    def json(self, path, payload=None, *, method=None):
        with self.request(path, payload, method=method) as response:
            return json.load(response)

    def upload(self, path, filename, data):
        boundary = "hilo-" + uuid.uuid4().hex
        body = f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + f"\r\n--{boundary}--\r\n".encode()
        with self.request(path, body, content_type=f"multipart/form-data; boundary={boundary}") as response:
            return json.load(response)


def wait_for(check, description, timeout=240):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                print(f"PASS {description}", flush=True)
                return result
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        time.sleep(2)
    raise AssertionError(f"Timed out: {description}; last error: {last_error}")


def verify(base_url):
    client = Client(base_url)
    wait_for(lambda: client.json("/api/models"), "gateway ready")
    wait_for(lambda: client.request("/").status == 200, "frontend ready")
    anonymous = Client(base_url)
    for path in ("/api/secure-langgraph/threads/search", "/api/secure-knowledge/users/me/knowledge/list"):
        try:
            anonymous.json(path, {} if path.endswith("search") else None)
            raise AssertionError("Anonymous request unexpectedly accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 401, (path, error.code)
    print("PASS authenticated proxy rejects anonymous access", flush=True)

    email = f"hilo-{uuid.uuid4().hex}@example.test"
    password = secrets.token_urlsafe(24)
    client.json("/api/auth/sign-up/email", {"email": email, "password": password, "name": "Hilo acceptance"})
    session = client.json("/api/auth/get-session")
    assert session["user"]["email"] == email
    client.json("/api/auth/sign-out", {})
    client.json("/api/auth/sign-in/email", {"email": email, "password": password})
    session = client.json("/api/auth/get-session")
    user_id = session["user"]["id"]
    print("PASS MariaDB registration, sign-out, sign-in and session", flush=True)

    personal = "/api/secure-knowledge/users/me/knowledge"
    client.upload(personal + "/upload", "personal-smoke.txt", b"Synthetic personal source: worker retry policy uses bounded attempts. " * 8)
    result = wait_for(lambda: data if (data := client.json(personal + "/list"))["indexed_count"] == 1 and data["doc_count"] > 0 else None, "personal upload parsed and indexed in Qdrant")
    assert result["count"] == 1

    thread = wait_for(lambda: client.json("/api/secure-langgraph/threads", {}), "LangGraph thread creation")
    thread_id = thread["thread_id"]
    assert thread["metadata"]["user_id"] == user_id
    result = client.upload(f"/api/threads/{thread_id}/uploads", "thread-smoke.md", b"# Thread source\n\nWorker retry policy is bounded.\n")
    assert result["files"][0]["parse_status"] == "parsed", result
    print("PASS thread Markdown upload parsed without OCR", flush=True)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("hilo-smoke/SKILL.md", "---\nname: hilo-smoke\ndescription: Synthetic acceptance fixture\n---\nRead the configured domain sources.\n")
    result = client.upload(f"/api/threads/{thread_id}/uploads", "hilo-smoke.skill", archive.getvalue())
    result = client.json("/api/skills/install", {"thread_id": thread_id, "path": result["files"][0]["virtual_path"]})
    assert result["success"], result
    assert any(skill["name"] == "hilo-smoke" for skill in client.json("/api/skills")["skills"])
    print("PASS custom Skill installation into shared writable volume", flush=True)

    with client.request(
        f"/api/secure-langgraph/threads/{thread_id}/runs/stream",
        {
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": "What retry policy does the worker use?"}]},
            "stream_mode": ["values", "messages-tuple"],
            "config": {"recursion_limit": 40},
            "context": {"thread_id": thread_id, "user_id": user_id, "thinking_enabled": False},
        },
    ) as response:
        assert "text/event-stream" in response.headers.get("content-type", "")
        events = []
        state = None
        event = ""
        for raw_line in response:
            line = raw_line.decode().strip()
            if line.startswith("event:"):
                event = line[6:].strip()
                events.append(event)
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                assert event != "error", data
                if event == "values":
                    state = data
    assert "messages" in " ".join(events), events
    assert state and state.get("knowledge_citation_registry"), state
    messages = state["messages"]
    answer = str(messages[-1]["content"])
    assert "at most four attempts" in answer, answer
    registry = state["knowledge_citation_registry"]
    assert any(f"[citation:{entry['id']}]" in answer and "retry-policy.md" in entry["url"] for entry in registry)
    state = client.json(f"/api/secure-langgraph/threads/{thread_id}/state")
    assert state["values"]["knowledge_citation_registry"]
    print("PASS real HTTP SSE: catalog → body → answer → persisted citation", flush=True)
    print("Hilo full-stack acceptance passed (deterministic HTTP model fixtures).", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:2026")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    (prepare if args.prepare else verify)(args.base_url.rstrip("/"))
