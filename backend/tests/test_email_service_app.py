from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from email_service.app import (
    DeliveryError,
    ResendSender,
    VerificationEmailRequest,
    create_app,
)


class _Sender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[VerificationEmailRequest] = []

    async def send(self, message: VerificationEmailRequest) -> None:
        if self.fail:
            raise DeliveryError("failed")
        self.messages.append(message)

    async def close(self) -> None:
        return None


def test_private_delivery_endpoint_requires_token_and_forwards_message():
    sender = _Sender()
    token = "mail-service-token-that-is-at-least-32-characters"
    client = TestClient(create_app(service_token=token, sender=sender))
    body = {
        "email": "user@example.com",
        "code": "123456",
        "ttl_minutes": 10,
        "idempotency_key": "verification-id-1234567890",
    }

    assert client.post("/internal/v1/verification-email", json=body).status_code == 401
    response = client.post(
        "/internal/v1/verification-email",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
    assert sender.messages == [VerificationEmailRequest(**body)]


def test_delivery_failure_is_reported_without_exposing_upstream_details():
    token = "mail-service-token-that-is-at-least-32-characters"
    client = TestClient(create_app(service_token=token, sender=_Sender(fail=True)))
    response = client.post(
        "/internal/v1/verification-email",
        json={
            "email": "user@example.com",
            "code": "123456",
            "ttl_minutes": 10,
            "idempotency_key": "verification-id-1234567890",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "email delivery failed"}


def test_resend_sender_uses_server_side_credentials_and_idempotency_key():
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["idempotency"] = request.headers["Idempotency-Key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "email-id"})

    client = httpx.AsyncClient(
        base_url="https://api.resend.test",
        transport=httpx.MockTransport(handle),
    )
    sender = ResendSender(
        api_key="resend-secret",
        from_address="ESA <verify@example.com>",
        client=client,
    )
    message = VerificationEmailRequest(
        email="user@example.com",
        code="123456",
        ttl_minutes=10,
        idempotency_key="verification-id-1234567890",
    )

    asyncio.run(sender.send(message))
    asyncio.run(client.aclose())

    assert captured["authorization"] == "Bearer resend-secret"
    assert captured["idempotency"] == message.idempotency_key
    assert captured["body"]["to"] == [message.email]
