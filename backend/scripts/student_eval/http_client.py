from __future__ import annotations
import json
import urllib.error
import urllib.request
from typing import Any

class EsaHttp:
    def __init__(self, base_url: str, session_id: str, timeout: float = 300.0):
        self.base = base_url.rstrip("/")
        self.session_id = session_id
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {detail}") from e

    def health(self) -> Any:
        # Canonical health is GET /api/health when base already ends with /api.
        url = self.base + "/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {"ok": True}

    def create_learning_conversation(self, title: str) -> Any:
        return self._request("POST", "/conversations", {
            "title": title, "workspace_type": "learning"
        })

    def send(self, conversation_id: str, content: str, knowledge_sources: list[str]) -> Any:
        return self._request("POST", f"/conversations/{conversation_id}/messages", {
            "content": content,
            "knowledge_sources": knowledge_sources,
        })

def conversation_id(obj: Any) -> str:
    if isinstance(obj, dict):
        for key in ("conversation_id", "id"):
            if isinstance(obj.get(key), str):
                return obj[key]
        for value in obj.values():
            try:
                return conversation_id(value)
            except ValueError:
                pass
    raise ValueError(f"cannot find conversation id in response: {obj}")

def extract_answer(obj: Any) -> str:
    # Preserve raw JSON separately; this is only a convenience extractor.
    if isinstance(obj, dict):
        for key in ("content", "answer", "assistant_content", "response"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                found = extract_answer(val)
                if found:
                    return found
        msg = obj.get("message")
        if isinstance(msg, dict):
            val = msg.get("content")
            if isinstance(val, str):
                return val
        for value in obj.values():
            if isinstance(value, (dict, list)):
                found = extract_answer(value)
                if found:
                    return found
    if isinstance(obj, list):
        for item in reversed(obj):
            found = extract_answer(item)
            if found:
                return found
    return ""
