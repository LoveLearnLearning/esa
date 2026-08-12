from __future__ import annotations

import asyncio
import json
import sqlite3

import httpx
import pytest

from backend.core.services.email_verification_service import (
    EmailDeliveryError,
    EmailServiceSender,
    EmailVerificationService,
    VerificationPolicy,
    normalize_email,
)
from backend.core.stores.email_verification_store import (
    EmailVerificationStore,
    VerificationRateLimited,
)


class _Sender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.code = ""

    async def send_code(self, **values) -> None:
        if self.fail:
            raise EmailDeliveryError("failed")
        self.code = values["code"]

    async def close(self) -> None:
        return None


def _service(tmp_path, *, sender: _Sender | None = None, max_attempts: int = 3):
    actual_sender = sender or _Sender()
    store = EmailVerificationStore(tmp_path / "verification.db")
    service = EmailVerificationService(
        store=store,
        sender=actual_sender,
        digest_secret="test-secret-that-is-at-least-32-characters",
        policy=VerificationPolicy(
            cooldown_seconds=60,
            email_hourly_limit=5,
            ip_hourly_limit=20,
            max_attempts=max_attempts,
        ),
    )
    return service, store, actual_sender


def test_code_is_hashed_rate_limited_and_single_use(tmp_path):
    service, store, sender = _service(tmp_path)
    email = normalize_email("User@Example.COM")
    asyncio.run(service.request_code(email=email, purpose="register", ip="127.0.0.1"))

    with sqlite3.connect(store.database_path) as connection:
        digest = connection.execute(
            "SELECT code_digest FROM email_verification_codes"
        ).fetchone()[0]
    assert sender.code not in digest
    assert service.verify(email=email, purpose="register", code="000000") == "invalid"
    assert service.verify(email=email, purpose="register", code=sender.code) == "ok"
    assert service.verify(email=email, purpose="register", code=sender.code) == "invalid"

    with pytest.raises(VerificationRateLimited):
        asyncio.run(
            service.request_code(email=email, purpose="register", ip="127.0.0.1")
        )


def test_failed_delivery_removes_challenge(tmp_path):
    service, store, _ = _service(tmp_path, sender=_Sender(fail=True))

    with pytest.raises(EmailDeliveryError):
        asyncio.run(
            service.request_code(
                email="user@example.com", purpose="register", ip="127.0.0.1"
            )
        )

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM email_verification_codes"
        ).fetchone()[0] == 0


def test_supercomputer_sender_calls_only_the_standalone_email_service():
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    sender = EmailServiceSender(
        base_url="https://mail-api.example.com",
        service_token="service-token-that-is-at-least-32-characters",
        transport=httpx.MockTransport(handle),
    )

    asyncio.run(
        sender.send_code(
            email="user@example.com",
            code="123456",
            ttl_minutes=10,
            idempotency_key="verification-id-1234567890",
        )
    )
    asyncio.run(sender.close())

    assert captured["path"] == "/internal/v1/verification-email"
    assert captured["authorization"] == (
        "Bearer service-token-that-is-at-least-32-characters"
    )
    assert captured["body"] == {
        "email": "user@example.com",
        "code": "123456",
        "ttl_minutes": 10,
        "idempotency_key": "verification-id-1234567890",
    }
