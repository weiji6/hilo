"""Deterministic OpenAI HTTP fixture, exclusively for stack acceptance tests.

This tests transport and orchestration, not model quality or semantic embeddings.
It has no external service calls and uses only synthetic sources.
"""

import hashlib
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"fixture ready")

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/embeddings"):
            inputs = request["input"]
            if isinstance(inputs, str) or (inputs and isinstance(inputs[0], int)):
                inputs = [inputs]
            data = [{"object": "embedding", "index": i, "embedding": [v / 255 for v in hashlib.sha256(json.dumps(value).encode()).digest()]} for i, value in enumerate(inputs)]
            self.reply({"object": "list", "data": data, "model": "fixture", "usage": {"prompt_tokens": 1, "total_tokens": 1}})
            return
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        messages = request["messages"]
        user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"), 0)
        latest_user = str(messages[user_index].get("content", ""))
        results = [m for m in messages[user_index:] if m.get("role") == "tool"]
        suggestion = "第 3 阶段" in str(messages[0].get("content", ""))
        if "HILO_PROVIDER_FAILURE" in latest_user:
            self.reply({"error": {"message": "Synthetic provider outage", "type": "server_error"}}, status=503)
            return
        if suggestion:
            message = {"role": "assistant", "content": "Which errors are retryable?\nWhat delays apply?\nHow many retries follow the first attempt?"}
        elif "HILO_MISSING_EVIDENCE" in latest_user:
            if not results:
                message = self.tool("missing", "knowledge_locate", {"doc_id": "hilo-deliberately-absent.md", "queries": ["NONEXISTENT_SENTINEL"]})
            else:
                message = {"role": "assistant", "content": "The nonexistent source supposedly confirms an invented policy with exactly ninety-nine attempts. This claim has no supporting body evidence at all. [citation:999]"}
        elif "HILO_SCOPE_CHECK" in latest_user:
            if not results:
                doc_id = re.search(r"DOC_ID=(\S+)", latest_user).group(1)
                message = self.tool("scope", "knowledge_locate", {"doc_id": doc_id, "pdf_page_no": 1})
            else:
                body = "\n".join(str(m.get("content", "")) for m in results)
                marker = re.search(r"\[citation:\d+\]", body)
                owners = re.findall(r"OWNER_[AB]_(?:OLD|NEW|ONLY)", body)
                message = {"role": "assistant", "content": f"The source contains {' '.join(sorted(set(owners)))}. {marker.group()}" if marker and owners else "【无法回答】No visible body evidence."}
        elif not results and request.get("tools"):
            message = self.tool("route", "book_search", {"query": "retry policy", "knowledge_folders": ["未分类"]})
        elif results and "knowledge_locate" not in str(messages):
            message = self.tool("read", "knowledge_locate", {"doc_id": "retry-policy.md", "queries": ["retry"]})
        elif results and any("at most four attempts" in str(m.get("content")) for m in results):
            body = "\n".join(str(m.get("content", "")) for m in results)
            marker = re.search(r"\[citation:\d+\]", body)
            if marker:
                message = {"role": "assistant", "content": f"The worker makes at most four attempts, including the initial request. {marker.group()}"}
            else:
                message = self.tool("read", "knowledge_locate", {"doc_id": "retry-policy.md", "queries": ["retry"]})
        elif results:
            message = self.tool("read", "knowledge_locate", {"doc_id": "retry-policy.md", "queries": ["retry"]})
        else:
            message = {"role": "assistant", "content": "Worker retry policy"}
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        base = {"id": "chatcmpl-hilo-fixture", "created": int(time.time()), "model": "fixture"}
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            delta = dict(message)
            if "tool_calls" in delta:
                delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(delta["tool_calls"])]
            for payload in [
                {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            ]:
                self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.reply({**base, "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    def tool(self, call_id, name, args):
        return {"role": "assistant", "content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}

    def reply(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
