"""Email identity normalization, verification-code lifecycle, and delivery."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Protocol

import httpx

from backend.core.stores.email_verification_store import EmailVerificationStore

_EMAIL_PATTERN = re.compile(r"^[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+$")


class InvalidEmail(ValueError):
    pass


class EmailDeliveryError(RuntimeError):
    pass


class EmailSender(Protocol):
    async def send_code(
        self,
        *,
        email: str,
        code: str,
        ttl_minutes: int,
        idempotency_key: str,
    ) -> None: ...

    async def close(self) -> None: ...


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_PATTERN.fullmatch(email):
        raise InvalidEmail("邮箱格式不正确")
    local, domain = email.rsplit("@", 1)
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise InvalidEmail("邮箱域名不正确") from error
    normalized = f"{local}@{domain}"
    if len(normalized) > 254:
        raise InvalidEmail("邮箱地址过长")
    return normalized


class EmailServiceSender:
    """Deliver codes through the separately deployed transactional-mail service."""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=15.0,
            headers={"Authorization": f"Bearer {service_token}"},
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def send_code(
        self,
        *,
        email: str,
        code: str,
        ttl_minutes: int,
        idempotency_key: str,
    ) -> None:
        try:
            response = await self._client.post(
                "/internal/v1/verification-email",
                json={
                    "email": email,
                    "code": code,
                    "ttl_minutes": ttl_minutes,
                    "idempotency_key": idempotency_key,
                },
            )
            response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            raise EmailDeliveryError("邮件投递失败") from error


@dataclass(frozen=True)
class VerificationPolicy:
    ttl_seconds: int = 600
    cooldown_seconds: int = 60
    email_hourly_limit: int = 5
    ip_hourly_limit: int = 20
    max_attempts: int = 5


class EmailVerificationService:
    def __init__(
        self,
        *,
        store: EmailVerificationStore,
        sender: EmailSender,
        digest_secret: str,
        policy: VerificationPolicy,
    ) -> None:
        if len(digest_secret) < 32:
            raise ValueError("EMAIL_VERIFICATION_SECRET 至少需要 32 个字符")
        self.store = store
        self.sender = sender
        self._secret = digest_secret.encode()
        self.policy = policy

    def _digest(self, *, email: str, purpose: str, code: str) -> str:
        payload = f"{purpose}\n{email}\n{code}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    async def request_code(self, *, email: str, purpose: str, ip: str) -> int:
        code = f"{secrets.randbelow(1_000_000):06d}"
        issued = self.store.issue(
            email=email,
            purpose=purpose,
            code_digest=self._digest(email=email, purpose=purpose, code=code),
            requested_ip=ip,
            ttl_seconds=self.policy.ttl_seconds,
            cooldown_seconds=self.policy.cooldown_seconds,
            email_hourly_limit=self.policy.email_hourly_limit,
            ip_hourly_limit=self.policy.ip_hourly_limit,
            max_attempts=self.policy.max_attempts,
        )
        try:
            await self.sender.send_code(
                email=email,
                code=code,
                ttl_minutes=max(1, self.policy.ttl_seconds // 60),
                idempotency_key=issued.verification_id,
            )
        except EmailDeliveryError:
            self.store.discard(issued.verification_id)
            raise
        return self.policy.cooldown_seconds

    def verify(self, *, email: str, purpose: str, code: str) -> str:
        return self.store.consume(
            email=email,
            purpose=purpose,
            code_digest=self._digest(email=email, purpose=purpose, code=code),
        )

    async def close(self) -> None:
        await self.sender.close()
