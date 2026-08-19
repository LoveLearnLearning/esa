# backend/core/services/lsp_service.py

"""提供领域服务实现。"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Mapping, Sequence

logger = logging.getLogger(__name__)


class LanguageServerUnavailable(RuntimeError):
    """表示 `LanguageServerUnavailable` 异常。"""
    pass


class LspSessionLimitExceeded(RuntimeError):
    """表示 `LspSessionLimitExceeded` 异常。"""
    pass


class LspProtocolError(RuntimeError):
    """表示 `LspProtocolError` 异常。"""
    pass


@dataclass(frozen=True)
class LspServerSpec:
    """封装 `LspServerSpec` 的状态与行为。"""
    command: tuple[str, ...]
    filename: str


class LspProcessBridge:
    """封装 `LspProcessBridge` 的状态与行为。"""
    def __init__(
        self,
        *,
        language: str,
        user_id: str,
        spec: LspServerSpec,
        max_message_bytes: int,
    ) -> None:
        """初始化 `LspProcessBridge` 实例。"""
        self.language = language
        self.user_id = user_id
        self.spec = spec
        self.max_message_bytes = max_message_bytes
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self.root_path: Path | None = None
        self.document_path: Path | None = None

    @property
    def root_uri(self) -> str:
        """处理 `root_uri` 相关逻辑。"""
        if self.root_path is None:
            raise RuntimeError("language server has not started")
        return self.root_path.as_uri()

    @property
    def document_uri(self) -> str:
        """处理 `document_uri` 相关逻辑。"""
        if self.document_path is None:
            raise RuntimeError("language server has not started")
        return self.document_path.as_uri()

    async def start(self) -> None:
        """启动 `start` 相关数据。"""
        executable = shutil.which(self.spec.command[0])
        if executable is None:
            raise LanguageServerUnavailable(
                f"{self.language} language server is not installed"
            )

        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix=f"esa-lsp-{self.language}-"
        )
        self.root_path = Path(self._temporary_directory.name).resolve()
        self.document_path = self.root_path / self.spec.filename
        self.document_path.touch()

        try:
            self._process = await asyncio.create_subprocess_exec(
                executable,
                *self.spec.command[1:],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.root_path,
            )
        except Exception:
            self._temporary_directory.cleanup()
            self._temporary_directory = None
            raise

        self._stderr_task = asyncio.create_task(self._drain_stderr())
        logger.info(
            "LSP[%s] started user=%s pid=%s",
            self.language,
            self.user_id,
            self._process.pid,
        )

    async def send(self, message: str) -> None:
        """发送 `send` 相关数据。

        Args:
            message: str => `message` 参数。
        """
        process = self._require_process()
        if process.stdin is None:
            raise LspProtocolError("language server stdin is unavailable")
        payload = message.encode("utf-8")
        if len(payload) > self.max_message_bytes:
            raise LspProtocolError("LSP message exceeds the configured limit")
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as error:
            raise LspProtocolError("invalid LSP JSON") from error
        if not isinstance(parsed, dict):
            raise LspProtocolError("LSP message must be a JSON object")

        process.stdin.write(
            f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        )
        await process.stdin.drain()

    async def receive(self) -> str:
        """处理 `receive` 相关逻辑。"""
        process = self._require_process()
        if process.stdout is None:
            raise LspProtocolError("language server stdout is unavailable")

        content_length: int | None = None
        while True:
            line = await process.stdout.readline()
            if not line:
                raise EOFError("language server closed stdout")
            if len(line) > 8192:
                raise LspProtocolError("LSP header line is too large")
            if line in {b"\r\n", b"\n"}:
                break
            name, separator, value = line.decode("ascii", "strict").partition(":")
            if not separator:
                raise LspProtocolError("malformed LSP header")
            if name.strip().lower() == "content-length":
                try:
                    content_length = int(value.strip())
                except ValueError as error:
                    raise LspProtocolError("invalid LSP content length") from error

        if content_length is None or content_length < 0:
            raise LspProtocolError("missing LSP content length")
        if content_length > self.max_message_bytes:
            raise LspProtocolError("LSP response exceeds the configured limit")
        payload = await process.stdout.readexactly(content_length)
        message = payload.decode("utf-8")
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as error:
            raise LspProtocolError("language server returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise LspProtocolError("language server response must be a JSON object")
        return message

    async def close(self) -> None:
        """释放当前对象持有的资源。"""
        process = self._process
        self._process = None
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
                with suppress(BrokenPipeError):
                    await process.stdin.wait_closed()
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=1.5)
                except asyncio.TimeoutError:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=1.5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()

        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stderr_task
            self._stderr_task = None

        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None
        logger.info("LSP[%s] stopped user=%s", self.language, self.user_id)

    def _require_process(self) -> asyncio.subprocess.Process:
        """处理 `_require_process` 相关逻辑。"""
        if self._process is None or self._process.returncode is not None:
            raise LanguageServerUnavailable("language server is not running")
        return self._process

    async def _drain_stderr(self) -> None:
        """处理 `_drain_stderr` 相关逻辑。"""
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            logger.debug(
                "LSP[%s] user=%s stderr=%s",
                self.language,
                self.user_id,
                line.decode("utf-8", "replace").rstrip()[:2000],
            )


class LspService:
    """提供 `lsp service` 领域服务。"""
    def __init__(
        self,
        *,
        commands: Mapping[str, Sequence[str]],
        filenames: Mapping[str, str],
        enabled: bool = True,
        max_sessions: int = 24,
        max_sessions_per_user: int = 2,
        max_message_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        """初始化 `LspService` 实例。"""
        self.enabled = enabled
        self.max_sessions = max_sessions
        self.max_sessions_per_user = max_sessions_per_user
        self.max_message_bytes = max_message_bytes
        self._specs = {
            language: LspServerSpec(tuple(command), filenames[language])
            for language, command in commands.items()
            if command and language in filenames
        }
        self._active_total = 0
        self._active_by_user: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def supports(self, language: str) -> bool:
        """处理 `supports` 相关逻辑。"""
        return self.enabled and language in self._specs

    @asynccontextmanager
    async def open(
        self, *, user_id: str, language: str
    ) -> AsyncIterator[LspProcessBridge]:
        """打开 `open` 相关数据。

        Args:
            user_id: str => 用户 ID。
            language: str => `language` 参数。

        Returns:
            AsyncIterator[LspProcessBridge] => 处理结果。
        """
        if not self.enabled:
            raise LanguageServerUnavailable("LSP is disabled")
        spec = self._specs.get(language)
        if spec is None:
            raise LanguageServerUnavailable(f"unsupported LSP language: {language}")

        async with self._lock:
            active_for_user = self._active_by_user.get(user_id, 0)
            if self._active_total >= self.max_sessions:
                raise LspSessionLimitExceeded("global LSP session limit reached")
            if active_for_user >= self.max_sessions_per_user:
                raise LspSessionLimitExceeded("user LSP session limit reached")
            self._active_total += 1
            self._active_by_user[user_id] = active_for_user + 1

        bridge = LspProcessBridge(
            language=language,
            user_id=user_id,
            spec=spec,
            max_message_bytes=self.max_message_bytes,
        )
        try:
            await bridge.start()
            yield bridge
        finally:
            try:
                await bridge.close()
            finally:
                async with self._lock:
                    self._active_total -= 1
                    remaining = self._active_by_user.get(user_id, 1) - 1
                    if remaining > 0:
                        self._active_by_user[user_id] = remaining
                    else:
                        self._active_by_user.pop(user_id, None)
