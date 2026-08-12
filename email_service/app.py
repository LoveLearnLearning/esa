"""Private HTTPS email-delivery API deployed outside the supercomputer."""

from __future__ import annotations

import hmac
import html
import os
from contextlib import asynccontextmanager
from typing import Protocol

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field


class VerificationEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    ttl_minutes: int = Field(ge=1, le=60)
    idempotency_key: str = Field(min_length=16, max_length=128)


class DeliveryError(RuntimeError):
    pass


class Sender(Protocol):
    async def send(self, message: VerificationEmailRequest) -> None: ...

    async def close(self) -> None: ...


class ResendSender:
    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        base_url: str = "https://api.resend.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._from_address = from_address
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=15.0
        )
        self._owns_client = client is None

    async def send(self, message: VerificationEmailRequest) -> None:
        safe_code = html.escape(message.code)
        try:
            response = await self._client.post(
                "/emails",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Idempotency-Key": message.idempotency_key,
                },
                json={
                    "from": self._from_address,
                    "to": [message.email],
                    "subject": "星知智链邮箱验证码",
                    "text": (
                        f"你的验证码是 {message.code}，{message.ttl_minutes} 分钟内有效。"
                        "请勿转发给他人。"
                    ),
                    "html": (
                        "<div style='font-family:system-ui,sans-serif;line-height:1.7'>"
                        "<h2>星知智链邮箱验证</h2><p>你的验证码是：</p>"
                        "<p style='font-size:30px;font-weight:700;letter-spacing:6px'>"
                        f"{safe_code}</p><p>{message.ttl_minutes} 分钟内有效，"
                        "请勿转发给他人。</p></div>"
                    ),
                },
            )
            response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            raise DeliveryError("upstream email delivery failed") from error

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def create_app(*, service_token: str, sender: Sender) -> FastAPI:
    if len(service_token) < 32:
        raise ValueError("MAIL_SERVICE_TOKEN must contain at least 32 characters")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await sender.close()

    app = FastAPI(title="ESA Mail Service", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/internal/v1/verification-email",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    async def send_verification_email(
        body: VerificationEmailRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Response:
        expected = f"Bearer {service_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid service token")
        try:
            await sender.send(body)
        except DeliveryError as error:
            request.app.state.last_delivery_failed = True
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "email delivery failed"
            ) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def create_app_from_env() -> FastAPI:
    """Uvicorn factory used on the standalone mail server."""

    service_token = os.environ.get("MAIL_SERVICE_TOKEN", "").strip()
    resend_api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_address = os.environ.get("MAIL_FROM", "").strip()
    if not resend_api_key:
        raise RuntimeError("RESEND_API_KEY is required")
    if not from_address:
        raise RuntimeError("MAIL_FROM is required")
    return create_app(
        service_token=service_token,
        sender=ResendSender(
            api_key=resend_api_key,
            from_address=from_address,
            base_url=os.environ.get("RESEND_BASE_URL", "https://api.resend.com"),
        ),
    )
