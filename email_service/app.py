# email_service/app.py

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
    """表示 `verification email request` 数据结构。"""
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    ttl_minutes: int = Field(ge=1, le=60)
    idempotency_key: str = Field(min_length=16, max_length=128)


class DeliveryError(RuntimeError):
    """表示 `DeliveryError` 异常。"""
    pass


class Sender(Protocol):
    """定义 `Sender` 组件协议。"""
    async def send(self, message: VerificationEmailRequest) -> None:
        """发送 `send` 相关数据。"""
        ...

    async def close(self) -> None:
        """释放当前对象持有的资源。"""
        ...


class ResendSender:
    """封装 `ResendSender` 的状态与行为。"""
    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        base_url: str = "https://api.resend.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """初始化 `ResendSender` 实例。"""
        self._api_key = api_key
        self._from_address = from_address
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=15.0
        )
        self._owns_client = client is None

    async def send(self, message: VerificationEmailRequest) -> None:
        """发送 `send` 相关数据。

        Args:
            message: VerificationEmailRequest => `message` 参数。
        """
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
        """释放当前对象持有的资源。"""
        if self._owns_client:
            await self._client.aclose()


def create_app(*, service_token: str, sender: Sender) -> FastAPI:
    """创建 `app` 相关数据。

    Args:
        service_token: str => `service_token` 参数。
        sender: Sender => `sender` 参数。

    Returns:
        FastAPI => 处理结果。
    """
    if len(service_token) < 32:
        raise ValueError("MAIL_SERVICE_TOKEN must contain at least 32 characters")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """处理 `lifespan` 相关逻辑。"""
        try:
            yield
        finally:
            await sender.close()

    app = FastAPI(title="ESA Mail Service", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """处理 `health` 相关逻辑。"""
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
        """发送 `verification email` 相关数据。

        Args:
            body: VerificationEmailRequest => `body` 参数。
            request: Request => 当前 HTTP 请求。
            authorization: str | None => `authorization` 参数。

        Returns:
            Response => 处理结果。
        """
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
