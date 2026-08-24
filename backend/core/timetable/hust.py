from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from pydantic import SecretStr

from backend.core.timetable.parser import (
    ParsedTimetable,
    TimetableParseError,
    parse_hust_schedule,
    total_weeks_between,
)


DEFAULT_CAS_LOGIN_URL = "https://hubs.hust.edu.cn/cas/login"
DEFAULT_CAPTCHA_URL = "https://pass.hust.edu.cn/cas/code"
DEFAULT_RSA_URL = "https://pass.hust.edu.cn/cas/rsa"
DEFAULT_QUERY_URL = "https://hubs.hust.edu.cn/aam/score/CourseInquiry_ido.action"
DEFAULT_SERVICE_URL = "https://hubs.hust.edu.cn/cas/login"
SHANGHAI_TZ = timezone(timedelta(hours=8))


class HustImportError(RuntimeError):
    """可安全返回给客户端的华科导入错误基类。"""


class HustChallengeError(HustImportError):
    pass


class HustChallengeNotFoundError(HustChallengeError):
    pass


class HustAuthenticationError(HustImportError):
    pass


class HustUpstreamError(HustImportError):
    pass


@dataclass(frozen=True, slots=True)
class HustConfig:
    cas_login_url: str = DEFAULT_CAS_LOGIN_URL
    captcha_url: str = DEFAULT_CAPTCHA_URL
    rsa_url: str = DEFAULT_RSA_URL
    query_url: str = DEFAULT_QUERY_URL
    service_url: str = DEFAULT_SERVICE_URL
    challenge_ttl_seconds: int = 300
    request_timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "HustConfig":
        query_url = os.getenv("HUST_QUERY_URL", DEFAULT_QUERY_URL).strip()
        return cls(
            cas_login_url=os.getenv(
                "HUST_CAS_LOGIN_URL", DEFAULT_CAS_LOGIN_URL
            ).strip(),
            captcha_url=os.getenv("HUST_CAPTCHA_URL", DEFAULT_CAPTCHA_URL).strip(),
            rsa_url=os.getenv("HUST_RSA_URL", DEFAULT_RSA_URL).strip(),
            query_url=query_url,
            service_url=os.getenv("HUST_SERVICE_URL", DEFAULT_SERVICE_URL).strip(),
            challenge_ttl_seconds=int(os.getenv("HUST_CHALLENGE_TTL", "300")),
            request_timeout_seconds=float(os.getenv("HUST_HTTP_TIMEOUT", "20")),
        )


@dataclass(frozen=True, slots=True)
class HustChallengePublic:
    challenge_id: str
    captcha_image_base64: str
    captcha_mime_type: str
    expires_at: str
    recommended_semester_name: str
    recommended_start_date: str
    recommended_end_date: str


@dataclass(slots=True)
class _HustChallenge:
    challenge_id: str
    owner_user_id: str
    client: httpx.AsyncClient
    login_form_url: str
    form_fields: dict[str, str]
    public_key: str | Mapping[str, Any]
    semester_name: str
    semester_start: date
    semester_end: date
    expires_at: datetime
    expires_monotonic: float
    expiry_task: asyncio.Task[None] | None = None


@dataclass(frozen=True, slots=True)
class HustFetchedSchedule:
    semester_name: str
    external_id: str
    start_date: date
    end_date: date
    total_weeks: int
    parsed: ParsedTimetable


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action = ""
        self.fields: dict[str, str] = {}
        self._inside_login_form = False
        self._found_login_form = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "form":
            form_id = values.get("id", "").lower()
            action = values.get("action", "")
            is_login = form_id == "loginform" or "login" in action.lower()
            if is_login and not self._found_login_form:
                self._inside_login_form = True
                self._found_login_form = True
                self.action = action
            else:
                self._inside_login_form = False
            return
        if tag.lower() == "input" and self._inside_login_form:
            name = values.get("name", "")
            if name:
                self.fields[name] = values.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self._inside_login_form = False


def _read_der_value(data: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    if offset >= len(data):
        raise ValueError("RSA 公钥 DER 数据提前结束")
    tag = data[offset]
    offset += 1
    if offset >= len(data):
        raise ValueError("RSA 公钥 DER 长度缺失")
    length = data[offset]
    offset += 1
    if length & 0x80:
        length_bytes = length & 0x7F
        if length_bytes == 0 or length_bytes > 4 or offset + length_bytes > len(data):
            raise ValueError("RSA 公钥 DER 长度非法")
        length = int.from_bytes(data[offset : offset + length_bytes], "big")
        offset += length_bytes
    end = offset + length
    if end > len(data):
        raise ValueError("RSA 公钥 DER 内容不完整")
    return tag, data[offset:end], end


def _integer_from_der(data: bytes, offset: int) -> tuple[int, int]:
    tag, content, end = _read_der_value(data, offset)
    if tag != 0x02 or not content:
        raise ValueError("RSA 公钥中缺少整数")
    return int.from_bytes(content, "big", signed=False), end


def load_rsa_public_numbers(
    public_key: str | Mapping[str, Any],
) -> tuple[int, int]:
    """读取 CAS `/rsa` 返回的 SPKI/PKCS#1 公钥或 modulus/exponent。"""

    if isinstance(public_key, Mapping):
        modulus = public_key.get("modulus") or public_key.get("n")
        exponent = public_key.get("exponent") or public_key.get("e") or "10001"
        if modulus is None:
            nested = public_key.get("publicKey") or public_key.get("key")
            if nested is not None:
                return load_rsa_public_numbers(nested)
            raise ValueError("RSA 公钥响应缺少 modulus/publicKey")
        try:
            return int(str(modulus), 16), int(str(exponent), 16)
        except ValueError as error:
            raise ValueError("RSA modulus/exponent 不是十六进制") from error

    cleaned = re.sub(r"-----[^-]+-----|\s+", "", public_key)
    cleaned += "=" * (-len(cleaned) % 4)
    try:
        der = base64.b64decode(cleaned, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("RSA 公钥不是合法 PEM/Base64") from error

    outer_tag, outer, outer_end = _read_der_value(der)
    if outer_tag != 0x30 or outer_end != len(der):
        raise ValueError("RSA 公钥不是合法 DER SEQUENCE")
    first_tag, first, first_end = _read_der_value(outer)
    if first_tag == 0x02:  # PKCS#1 RSAPublicKey
        modulus = int.from_bytes(first, "big", signed=False)
        exponent, end = _integer_from_der(outer, first_end)
        if end != len(outer):
            raise ValueError("RSA PKCS#1 公钥包含多余数据")
        return modulus, exponent

    if first_tag != 0x30:
        raise ValueError("RSA SPKI 算法标识缺失")
    bit_tag, bit_string, bit_end = _read_der_value(outer, first_end)
    if bit_tag != 0x03 or not bit_string or bit_string[0] != 0 or bit_end != len(outer):
        raise ValueError("RSA SPKI BIT STRING 非法")
    rsa_tag, rsa_body, rsa_end = _read_der_value(bit_string[1:])
    if rsa_tag != 0x30 or rsa_end != len(bit_string) - 1:
        raise ValueError("RSA SPKI 内层结构非法")
    modulus, offset = _integer_from_der(rsa_body, 0)
    exponent, offset = _integer_from_der(rsa_body, offset)
    if offset != len(rsa_body):
        raise ValueError("RSA 公钥包含多余数据")
    return modulus, exponent


def rsa_pkcs1_v1_5_encrypt(
    plaintext: str,
    public_key: str | Mapping[str, Any] | tuple[int, int],
    *,
    randfunc: Callable[[int], bytes] = secrets.token_bytes,
) -> str:
    """生成与浏览器 JSEncrypt 兼容的 PKCS#1 v1.5 Base64 密文。"""

    if isinstance(public_key, tuple):
        modulus, exponent = public_key
    else:
        modulus, exponent = load_rsa_public_numbers(public_key)
    if modulus <= 0 or exponent <= 0:
        raise ValueError("RSA 公钥参数必须为正整数")
    key_size = (modulus.bit_length() + 7) // 8
    message = plaintext.encode("utf-8")
    padding_length = key_size - len(message) - 3
    if padding_length < 8:
        raise ValueError("待加密内容过长，超出 RSA 公钥容量")

    padding = bytearray()
    attempts = 0
    while len(padding) < padding_length:
        attempts += 1
        if attempts > 100:
            raise ValueError("RSA 随机填充生成失败")
        random_bytes = randfunc(padding_length - len(padding))
        padding.extend(value for value in random_bytes if value != 0)
    encoded = b"\x00\x02" + bytes(padding[:padding_length]) + b"\x00" + message
    encrypted = pow(int.from_bytes(encoded, "big"), exponent, modulus)
    return base64.b64encode(encrypted.to_bytes(key_size, "big")).decode("ascii")


def _recommended_semester(today: date) -> tuple[str, date, date]:
    if today.month >= 7:
        academic_start = today.year
        approximate = date(today.year, 9, 1)
        name = f"{academic_start}-{academic_start + 1}学年第一学期"
    else:
        academic_start = today.year - 1
        approximate = date(today.year, 2, 15)
        name = f"{academic_start}-{academic_start + 1}学年第二学期"
    # 秋季校历通常以包含 9 月 1 日的周一作为第 1 教学周；例如
    # 2026-2027 学年第一周从 2026-08-31 开始。这里仅提供启发式值，
    # 用户仍可在完成导入时按当年校历覆盖。
    start = approximate - timedelta(days=approximate.weekday())
    end = start + timedelta(weeks=20) - timedelta(days=1)
    return name, start, end


async def _request_following_safe_redirects(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    stop_before_https_downgrade: bool = False,
    allowed_hosts: set[str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """跟随 CAS ticket，同时拒绝 HTTPS 到 HTTP 的 Cookie 降级。"""

    request_method = method.upper()
    request_url = url
    request_kwargs = dict(kwargs)
    for _ in range(10):
        request_host = (urlsplit(request_url).hostname or "").lower()
        if allowed_hosts is not None and request_host not in allowed_hosts:
            raise HustUpstreamError("华科认证返回了未允许的跳转域名")
        response = await client.request(
            request_method,
            request_url,
            follow_redirects=False,
            **request_kwargs,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        target = urljoin(str(response.url), location)
        target_host = (urlsplit(target).hostname or "").lower()
        if allowed_hosts is not None and target_host not in allowed_hosts:
            await response.aclose()
            raise HustUpstreamError("华科认证返回了未允许的跳转域名")
        if response.url.scheme == "https" and urlsplit(target).scheme == "http":
            if stop_before_https_downgrade:
                # 某些 HUB 回调在已写入 HTTPS 会话 Cookie 后仍给出绝对 HTTP
                # 页面跳转。绝不跟随它；登录流程可直接拿现有 Cookie 查询
                # HTTPS 课表接口，由后续响应判定会话是否真正建立。
                return response
            await response.aclose()
            raise HustAuthenticationError(
                "教务会话未建立，服务器返回了不安全的 HTTP 登录重定向"
            )
        status_code = response.status_code
        await response.aclose()
        request_url = target
        request_kwargs.pop("params", None)
        if status_code == 303 or (
            status_code in {301, 302} and request_method == "POST"
        ):
            request_method = "GET"
            for key in ("data", "json", "content", "files"):
                request_kwargs.pop(key, None)
    raise HustUpstreamError("华科认证重定向次数过多")


def _cookie_value(client: httpx.AsyncClient, name: str) -> str | None:
    for cookie in client.cookies.jar:
        if cookie.name == name:
            return unquote(cookie.value)
    return None


class HustImporter:
    """两阶段 HUST CAS 登录与课表抓取器。

    challenge 只存在本进程内存中，并持有隔离的 httpx client/Cookie Jar；
    它不包含账号或密码，完成时先原子取出，保证最多消费一次。
    """

    def __init__(
        self,
        config: HustConfig | None = None,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.config = config or HustConfig.from_env()
        self._client_factory = client_factory or self._default_client
        self._challenges: dict[str, _HustChallenge] = {}
        self._lock = asyncio.Lock()

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            follow_redirects=False,
            timeout=self.config.request_timeout_seconds,
            headers={
                "User-Agent": "ESA-Timetable-Importer/1.0",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

    def _allowed_hosts(self) -> set[str]:
        hosts = {
            (urlsplit(value).hostname or "").lower()
            for value in (
                self.config.cas_login_url,
                self.config.captcha_url,
                self.config.rsa_url,
                self.config.service_url,
                self.config.query_url,
            )
        }
        hosts.discard("")
        return hosts

    async def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, challenge in self._challenges.items()
            if challenge.expires_monotonic <= now
        ]
        for key in expired:
            challenge = self._challenges.pop(key)
            if (
                challenge.expiry_task is not None
                and challenge.expiry_task is not asyncio.current_task()
            ):
                challenge.expiry_task.cancel()
            await challenge.client.aclose()

    async def _expire_challenge(self, challenge_id: str) -> None:
        try:
            async with self._lock:
                challenge = self._challenges.get(challenge_id)
                if challenge is None:
                    return
                delay = max(0.0, challenge.expires_monotonic - time.monotonic())
            await asyncio.sleep(delay)
            expired: _HustChallenge | None = None
            async with self._lock:
                challenge = self._challenges.get(challenge_id)
                if (
                    challenge is not None
                    and challenge.expires_monotonic <= time.monotonic()
                ):
                    expired = self._challenges.pop(challenge_id)
            if expired is not None:
                await expired.client.aclose()
        except asyncio.CancelledError:
            return
        except Exception:
            # 后台清理不能影响 API；后续访问和应用关闭仍会再次清理。
            return

    async def close(self) -> None:
        async with self._lock:
            challenges = list(self._challenges.values())
            self._challenges.clear()
        tasks = [
            challenge.expiry_task
            for challenge in challenges
            if challenge.expiry_task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for challenge in challenges:
            await challenge.client.aclose()

    async def start_challenge(
        self,
        *,
        owner_user_id: str,
        semester_name: str | None = None,
        semester_start: date | None = None,
        semester_end: date | None = None,
    ) -> HustChallengePublic:
        now_shanghai = datetime.now(SHANGHAI_TZ).date()
        default_name, default_start, default_end = _recommended_semester(now_shanghai)
        name = (semester_name or default_name).strip()
        start = semester_start or default_start
        end = semester_end or default_end
        if not name:
            raise HustChallengeError("学期名称不能为空")
        if end < start:
            raise HustChallengeError("学期结束日期不能早于开始日期")
        if (end - start).days > 366:
            raise HustChallengeError("单次导入的日期范围不能超过 366 天")

        client = self._client_factory()
        allowed_hosts = self._allowed_hosts()
        try:
            login_response = await _request_following_safe_redirects(
                client,
                "GET",
                self.config.cas_login_url,
                allowed_hosts=allowed_hosts,
                params={"service": self.config.service_url},
            )
            if login_response.status_code >= 400:
                login_response.raise_for_status()
            parser = _LoginFormParser()
            parser.feed(login_response.text)
            if not parser.fields.get("lt"):
                raise HustUpstreamError("统一身份认证页面缺少 loginForm/lt，页面结构可能已更新")
            form_url = urljoin(str(login_response.url), parser.action or "")

            captcha_response = await _request_following_safe_redirects(
                client,
                "GET",
                self.config.captcha_url,
                allowed_hosts=allowed_hosts,
                params={"_": secrets.token_hex(8)},
            )
            captcha_response.raise_for_status()
            if not captcha_response.content:
                raise HustUpstreamError("统一身份认证未返回验证码图片")

            key_response = await _request_following_safe_redirects(
                client,
                "POST",
                self.config.rsa_url,
                allowed_hosts=allowed_hosts,
            )
            key_response.raise_for_status()
            try:
                key_payload = key_response.json()
            except json.JSONDecodeError as error:
                raise HustUpstreamError("统一身份认证 RSA 公钥响应不是 JSON") from error
            public_key: str | Mapping[str, Any]
            if isinstance(key_payload, Mapping):
                public_key = key_payload
            elif isinstance(key_payload, str):
                public_key = key_payload
            else:
                raise HustUpstreamError("统一身份认证 RSA 公钥响应格式无法识别")
            try:
                load_rsa_public_numbers(public_key)
            except ValueError as error:
                raise HustUpstreamError(f"统一身份认证 RSA 公钥无效：{error}") from error

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=self.config.challenge_ttl_seconds)
            challenge_id = str(uuid.uuid4())
            challenge = _HustChallenge(
                challenge_id=challenge_id,
                owner_user_id=owner_user_id,
                client=client,
                login_form_url=form_url,
                form_fields=parser.fields,
                public_key=public_key,
                semester_name=name,
                semester_start=start,
                semester_end=end,
                expires_at=expires_at,
                expires_monotonic=time.monotonic()
                + self.config.challenge_ttl_seconds,
            )
            async with self._lock:
                await self._purge_expired_locked()
                # 同一用户只保留最新验证码会话，避免反复刷新验证码堆积
                # AsyncClient/Cookie Jar 直至 TTL 到期。
                previous = [
                    key
                    for key, value in self._challenges.items()
                    if value.owner_user_id == owner_user_id
                ]
                for key in previous:
                    old_challenge = self._challenges.pop(key)
                    await old_challenge.client.aclose()
                self._challenges[challenge_id] = challenge
                challenge.expiry_task = asyncio.create_task(
                    self._expire_challenge(challenge_id)
                )
            mime_type = captcha_response.headers.get("content-type", "image/gif")
            mime_type = mime_type.split(";", 1)[0].strip() or "image/gif"
            return HustChallengePublic(
                challenge_id=challenge_id,
                captcha_image_base64=base64.b64encode(captcha_response.content).decode(
                    "ascii"
                ),
                captcha_mime_type=mime_type,
                expires_at=expires_at.isoformat(),
                recommended_semester_name=name,
                recommended_start_date=start.isoformat(),
                recommended_end_date=end.isoformat(),
            )
        except HustImportError:
            await client.aclose()
            raise
        except httpx.HTTPError as error:
            await client.aclose()
            raise HustUpstreamError("连接华科统一身份认证失败，请稍后重试") from error
        except Exception:
            await client.aclose()
            raise

    async def _consume(self, challenge_id: str, owner_user_id: str) -> _HustChallenge:
        async with self._lock:
            await self._purge_expired_locked()
            challenge = self._challenges.get(challenge_id)
            if challenge is None or challenge.owner_user_id != owner_user_id:
                raise HustChallengeNotFoundError(
                    "导入 challenge 不存在、已过期或不属于当前用户"
                )
            challenge = self._challenges.pop(challenge_id)
            if challenge.expiry_task is not None:
                challenge.expiry_task.cancel()
            return challenge

    async def complete_challenge(
        self,
        *,
        owner_user_id: str,
        challenge_id: str,
        username: str,
        password: SecretStr,
        captcha: str,
        semester_name: str | None = None,
        semester_start: date | None = None,
        semester_end: date | None = None,
    ) -> HustFetchedSchedule:
        challenge = await self._consume(challenge_id, owner_user_id)
        try:
            selected_name = (semester_name or challenge.semester_name).strip()
            selected_start = semester_start or challenge.semester_start
            selected_end = semester_end or challenge.semester_end
            if not selected_name:
                raise HustChallengeError("学期名称不能为空")
            if selected_end < selected_start:
                raise HustChallengeError("学期结束日期不能早于开始日期")
            if (selected_end - selected_start).days > 366:
                raise HustChallengeError("单次导入的日期范围不能超过 366 天")
            username_value = username.strip()
            captcha_value = captcha.strip()
            password_value = password.get_secret_value()
            if not username_value or not captcha_value:
                raise HustAuthenticationError("学号和验证码不能为空")
            if not password_value or len(password_value) > 256:
                raise HustAuthenticationError("统一身份认证密码不能为空或过长")
            try:
                encrypted_username = rsa_pkcs1_v1_5_encrypt(
                    username_value, challenge.public_key
                )
                encrypted_password = rsa_pkcs1_v1_5_encrypt(
                    password_value, challenge.public_key
                )
            except ValueError as error:
                raise HustUpstreamError(f"统一身份认证 RSA 加密失败：{error}") from error

            form = dict(challenge.form_fields)
            form.update(
                {
                    "rsa": "",
                    "ul": encrypted_username,
                    "pl": encrypted_password,
                    "code": captcha_value,
                    "phoneCode": "",
                    "_eventId": form.get("_eventId") or "submit",
                }
            )
            login_response = await _request_following_safe_redirects(
                challenge.client,
                "POST",
                challenge.login_form_url,
                stop_before_https_downgrade=True,
                allowed_hosts=self._allowed_hosts(),
                data=form,
            )
            if login_response.status_code >= 400:
                login_response.raise_for_status()
            body_lower = login_response.text.lower()
            final_host = login_response.url.host or ""
            if final_host.lower() == "pass.hust.edu.cn":
                if "phonecode" in body_lower or "二次认证" in login_response.text:
                    raise HustAuthenticationError(
                        "该账号需要短信或二次认证，当前导入方式暂不支持"
                    )
                raise HustAuthenticationError(
                    "统一身份认证失败，请检查学号、密码或验证码"
                )

            query_url = urlsplit(self.config.query_url)
            query_headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": urljoin(
                    self.config.query_url,
                    "/aam/report/scheduleQuery.jsp",
                ),
                "Origin": f"{query_url.scheme}://{query_url.netloc}",
                "User-Agent": "ESA-Timetable-Importer/1.0",
            }
            xsrf_token = _cookie_value(challenge.client, "XSRF-TOKEN")
            if xsrf_token:
                query_headers["X-XSRF-TOKEN"] = xsrf_token
            query_response = await _request_following_safe_redirects(
                challenge.client,
                "POST",
                self.config.query_url,
                allowed_hosts=self._allowed_hosts(),
                data={
                    "start": selected_start.isoformat(),
                    "end": selected_end.isoformat(),
                },
                headers=query_headers,
            )
            if query_response.status_code == 403:
                raise HustUpstreamError(
                    "华科教务拒绝了访问（403），请尝试校园网、学校 VPN 或校内代理"
                )
            query_response.raise_for_status()
            final_query_path = query_response.url.path.rstrip("/").lower()
            if (
                query_response.url.host == "pass.hust.edu.cn"
                or final_query_path.endswith("/login")
            ):
                raise HustAuthenticationError("教务会话未建立，请重新发起导入")
            try:
                payload = query_response.json()
            except json.JSONDecodeError as error:
                if "loginform" in query_response.text.lower():
                    raise HustAuthenticationError("教务会话未建立，请重新发起导入") from error
                raise HustUpstreamError("华科课表接口返回的不是 JSON，接口可能已更新") from error

            try:
                parsed = parse_hust_schedule(
                    payload,
                    semester_start=selected_start,
                    semester_end=selected_end,
                )
            except TimetableParseError as error:
                raise HustUpstreamError(f"华科课表解析失败：{error}") from error
            external_id = (
                f"{selected_start.isoformat()}_"
                f"{selected_end.isoformat()}"
            )
            return HustFetchedSchedule(
                semester_name=selected_name,
                external_id=external_id,
                start_date=selected_start,
                end_date=selected_end,
                total_weeks=total_weeks_between(
                    selected_start, selected_end
                ),
                parsed=parsed,
            )
        except HustImportError:
            raise
        except httpx.HTTPError as error:
            raise HustUpstreamError("连接华科统一身份认证或教务系统失败，请稍后重试") from error
        finally:
            await challenge.client.aclose()
