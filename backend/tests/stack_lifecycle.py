"""Exercise synthetic lifecycle/isolation cases before and after a Compose restart.

Use only with stack_smoke.py in a disposable Compose project, never a deployment.
The state file contains synthetic credentials and belongs outside the checkout.
"""

import argparse
import json
import secrets
import urllib.error
import uuid
from pathlib import Path

from stack_smoke import Client, save_state, wait_for

PERSONAL = "/api/secure-knowledge/users/me/knowledge"
THREADS = "/api/secure-langgraph/threads"


def expect_status(client, path, status, payload=None, *, method=None):
    try:
        with client.request(path, payload, method=method) as response:
            actual = response.status
    except urllib.error.HTTPError as error:
        actual = error.code
        error.close()
    assert actual == status, (path, actual, status)


def login(base_url, account):
    client = Client(base_url)
    wait_for(lambda: client.json("/api/auth/get-session") is not False, "session endpoint ready")
    client.json("/api/auth/sign-in/email", {"email": account["email"], "password": account["password"]})
    assert client.json("/api/auth/get-session")["user"]["id"] == account["user_id"]
    return client


def indexed(client, count=1):
    return wait_for(
        lambda: data if (data := client.json(PERSONAL + "/list"))["count"] == count and data["indexed_count"] == count and data["doc_count"] > 0 else None,
        f"{count} personal source(s) indexed",
    )


def body(client, filename):
    data = client.json(PERSONAL + f"/docs/{filename}/structured-page?pdf_page_no=1")
    return "\n".join(p["text"] for p in data["paragraphs"])


def run(client, thread_id, question, *, context=None, configurable=None, expect_error=False):
    run_config = {"recursion_limit": 40}
    if configurable is not None:
        run_config["configurable"] = {"thinking_enabled": False, **configurable}
    payload = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": question}]},
        "stream_mode": ["values", "messages-tuple"],
        "context": {"thinking_enabled": False, **(context or {})},
        "config": run_config,
    }
    state, errors, event = None, [], ""
    with client.request(f"{THREADS}/{thread_id}/runs/stream", payload) as response:
        assert "text/event-stream" in response.headers.get("content-type", "")
        for line in response:
            line = line.decode().strip()
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
                if event == "values":
                    state = data
                elif event == "error":
                    errors.append(data)
    if expect_error:
        assert errors, "Expected a provider error event"
    else:
        assert not errors, errors
        assert state and state.get("messages"), "Missing final state"
    return state


def verify_before(base_url, state):
    owner = login(base_url, state)
    other = Client(base_url)
    other.json("/api/auth/sign-up/email", {"email": f"hilo-other-{uuid.uuid4().hex}@example.test", "password": secrets.token_urlsafe(24), "name": "Other synthetic owner"})
    other_id = other.json("/api/auth/get-session")["user"]["id"]
    other_thread = other.json(THREADS, {})["thread_id"]
    thread_id = state["thread_id"]
    expect_status(other, f"{THREADS}/{thread_id}/state", 403)
    threads = other.json(THREADS + "/search", {"metadata": {"user_id": state["user_id"]}})
    assert other_thread in [t["thread_id"] for t in threads]
    assert thread_id not in [t["thread_id"] for t in threads]
    expect_status(other, f"/api/secure-knowledge/users/{state['user_id']}/knowledge/list", 400)
    expect_status(owner, "/api/secure-langgraph/runs/stream", 400, {"assistant_id": "lead_agent"})
    print("PASS authenticated proxies enforce thread ownership and users/me", flush=True)

    old = owner.json(PERSONAL + "/list")["records"][0]
    other.upload(PERSONAL + "/upload", "personal-smoke.txt", b"OWNER_B_ONLY synthetic personal evidence. " * 10)
    other_record = indexed(other)["records"][0]
    owner.upload(PERSONAL + "/upload", "personal-smoke.txt", b"OWNER_A_NEW synthetic personal evidence. " * 10)
    current = indexed(owner)
    record = current["records"][0]
    assert record["id"] != old["id"]
    assert "OWNER_A_NEW" in body(owner, "personal-smoke.txt")
    assert "OWNER_B_ONLY" in body(other, "personal-smoke.txt")
    spoofed = {"user_id": other_id, "thread_id": other_thread}
    final = run(owner, thread_id, f"HILO_SCOPE_CHECK DOC_ID={record['id']}", context=spoofed)
    serialized = json.dumps(final)
    assert "OWNER_A_NEW" in str(final["messages"][-1]["content"]), serialized
    assert "OWNER_B_ONLY" not in serialized
    assert any(m.get("name") == "knowledge_locate" and "OWNER_A_NEW" in str(m["content"]) for m in final["messages"])
    denied_thread = owner.json(THREADS, {})["thread_id"]
    denied = run(owner, denied_thread, f"HILO_SCOPE_CHECK DOC_ID={other_record['id']}", context=spoofed)
    assert "OWNER_B_ONLY" not in json.dumps(denied)
    assert "【无法回答】" in str(denied["messages"][-1]["content"])
    print("PASS personal retrieval ignores spoofed identity and cannot locate another user's document", flush=True)

    for client, target, marker in ((owner, thread_id, "OWNER_A_NEW"), (other, other_thread, "OWNER_B_ONLY")):
        uploaded = client.upload(f"/api/threads/{target}/uploads", "thread-scope.md", (marker + " synthetic thread evidence. ").encode() * 10)
        assert uploaded["files"][0]["parse_status"] == "parsed", uploaded
    final = run(owner, thread_id, "HILO_SCOPE_CHECK DOC_ID=thread-scope.md", context=spoofed)
    assert "OWNER_A_NEW" in str(final["messages"][-1]["content"]), final["messages"][-1]
    assert "OWNER_B_ONLY" not in json.dumps(final)
    print("PASS thread attachment retrieval remains bound to the owned URL thread", flush=True)

    owner.upload(PERSONAL + "/upload", "recovery.txt", b"\xff\xfeinvalid UTF-8")
    failed = wait_for(lambda: next((r for r in owner.json(PERSONAL + "/list")["records"] if r["filename"] == "recovery.txt" and r["parse_status"] == "failed"), None), "invalid text marked failed")
    assert failed["error"]
    owner.upload(PERSONAL + "/upload", "recovery.txt", b"RECOVERED synthetic Unicode source. " * 10)
    recovered = indexed(owner, 2)
    recovery = next(r for r in recovered["records"] if r["filename"] == "recovery.txt")
    assert not recovery["error"]
    assert "RECOVERED" in body(owner, "recovery.txt")
    owner.json(PERSONAL + f"/{recovery['id']}", method="DELETE")
    remaining = indexed(owner)
    assert remaining["doc_count"] == current["doc_count"], (remaining, current)
    expect_status(owner, PERSONAL + "/docs/recovery.txt", 404)
    expect_status(owner, PERSONAL + f"/{recovery['id']}", 404, method="DELETE")
    expect_status(owner, "/api/knowledge/uploads/hilo-deliberately-absent.txt", 404, method="DELETE")
    print("PASS failed parse recovers on replacement; deletion removes source and vector points", flush=True)

    missing_thread = owner.json(THREADS, {})["thread_id"]
    missing = run(owner, missing_thread, "HILO_MISSING_EVIDENCE")
    answer = str(missing["messages"][-1]["content"])
    assert answer.startswith("【无法回答】"), answer
    assert "[citation:999]" not in answer and not missing.get("knowledge_citation_registry")
    print("PASS missing evidence blocks the fixture's deliberately fabricated citation", flush=True)
    outage_thread = owner.json(THREADS, {})["thread_id"]
    run(owner, outage_thread, "HILO_PROVIDER_FAILURE", expect_error=True)
    recovered_run = run(owner, outage_thread, "What retry policy does the worker use?")
    assert "at most four attempts" in str(recovered_run["messages"][-1]["content"])
    print("PASS model outage surfaces an SSE error; a subsequent run succeeds", flush=True)

    state.update(record_id=record["id"], doc_count=remaining["doc_count"], citations=owner.json(f"{THREADS}/{thread_id}/state")["values"]["knowledge_citation_registry"])
    return state


def verify_after(base_url, state):
    owner = login(base_url, state)
    current = indexed(owner)
    assert current["records"][0]["id"] == state["record_id"]
    assert current["doc_count"] == state["doc_count"]
    assert "OWNER_A_NEW" in body(owner, "personal-smoke.txt")
    persisted = owner.json(f"{THREADS}/{state['thread_id']}/state")["values"]
    assert persisted["knowledge_citation_registry"] == state["citations"]
    assert "OWNER_A_NEW" in str(persisted["messages"][-1]["content"])
    assert any(skill["name"] == "hilo-smoke" for skill in owner.json("/api/skills")["skills"])
    final = run(owner, state["thread_id"], "HILO_SCOPE_CHECK DOC_ID=thread-scope.md")
    assert "OWNER_A_NEW" in str(final["messages"][-1]["content"])
    print("PASS recreated containers retain accounts, sources, vectors, thread state, citations and custom Skills", flush=True)
    owner.json(PERSONAL + f"/{state['record_id']}", method="DELETE")
    empty = owner.json(PERSONAL + "/list")
    assert empty["count"] == empty["indexed_count"] == empty["doc_count"] == 0, empty
    expect_status(owner, PERSONAL + "/docs/personal-smoke.txt", 404)
    print("PASS post-restart deletion removes the retained source and all its vector points", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:2026")
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    state = json.loads(args.state_file.read_text())
    if args.phase == "before":
        save_state(args.state_file, verify_before(args.base_url.rstrip("/"), state))
    else:
        verify_after(args.base_url.rstrip("/"), state)
