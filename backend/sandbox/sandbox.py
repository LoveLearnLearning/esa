"""Restricted command execution for Agent turns.

The sandbox deliberately requires Bubblewrap.  Running model supplied shell
commands directly on the ESA host is not an acceptable fallback, even when a
working directory and a timeout are applied.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import importlib.util
import math
import os
from pathlib import Path, PurePosixPath
import resource
import shlex
import shutil
import signal
import time
from contextlib import suppress
from typing import Any


class SandboxError(RuntimeError):
    """Expected, user-visible sandbox failure."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Hard limits applied to one sandbox process tree."""

    max_timeout_seconds: float = 30.0
    max_output_chars: int = 50_000
    max_command_chars: int = 12_000
    cpu_seconds: int = 20
    memory_bytes: int = 1_024 * 1_024 * 1_024
    file_size_bytes: int = 128 * 1_024 * 1_024
    process_count: int = 64


def _safe_component(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:32]


def _set_limits(limits: SandboxLimits) -> None:
    """Set host-safe limits before Bubblewrap starts the shell.

    RLIMIT_NPROC is deliberately applied *inside* the new user namespace in
    ``_bwrap_argv``.  Applying it here counts every process owned by the same
    account on the Slurm node; a busy shared account would then prevent
    Bubblewrap itself from creating its namespace with ``EAGAIN``.
    """

    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(
        resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes)
    )
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes)
    )


class SandboxService:
    """Own per-user workspaces and execute commands inside Bubblewrap."""

    def __init__(
        self,
        root: Path,
        *,
        enabled: bool,
        runtime: str = "bwrap",
        limits: SandboxLimits | None = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.enabled = enabled
        self.runtime = runtime
        self.limits = limits or SandboxLimits()
        pip_spec = importlib.util.find_spec("pip")
        pip_locations = (
            tuple(pip_spec.submodule_search_locations or ()) if pip_spec else ()
        )
        self.pip_package_path = (
            Path(pip_locations[0]).resolve() if pip_locations else None
        )
        if self.limits.max_timeout_seconds <= 0:
            raise ValueError("sandbox timeout must be positive")

    @property
    def runtime_path(self) -> str | None:
        return shutil.which(self.runtime)

    def workspace_for(self, user_id: str, conversation_id: str) -> Path:
        if not user_id or not conversation_id:
            raise SandboxError("sandbox requires a trusted user and conversation")
        workspace = (
            self.root
            / _safe_component(user_id)
            / _safe_component(conversation_id)
        )
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(workspace, 0o700)
        home = workspace / ".home"
        home.mkdir(exist_ok=True, mode=0o700)
        os.chmod(home, 0o700)
        return workspace

    def resolve_workdir(self, workspace: Path, workdir: str | None) -> str:
        value = (workdir or ".").strip()
        if not value:
            value = "."
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SandboxError("workdir must stay inside the sandbox workspace")
        resolved = (workspace / Path(*candidate.parts)).resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError as error:
            raise SandboxError("workdir must stay inside the sandbox workspace") from error
        resolved.mkdir(parents=True, exist_ok=True)
        return "/workspace" + ("/" + resolved.relative_to(workspace).as_posix() if resolved != workspace else "")

    async def execute(
        self,
        *,
        user_id: str,
        conversation_id: str,
        command: str,
        workdir: str | None = None,
        timeout_seconds: float | None = None,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        """Execute one command and return bounded, JSON-safe output."""

        if not self.enabled:
            return {"ok": False, "error": "sandbox_disabled"}
        command = command.strip()
        if not command:
            raise SandboxError("command cannot be blank")
        if "\x00" in command:
            raise SandboxError("command contains a null byte")
        if len(command) > self.limits.max_command_chars:
            raise SandboxError("command exceeds the sandbox command limit")
        runtime = self.runtime_path
        if runtime is None:
            return {
                "ok": False,
                "error": "sandbox_runtime_unavailable",
                "runtime": self.runtime,
            }
        if allow_network and (
            self.pip_package_path is None or not self.pip_package_path.is_dir()
        ):
            return {"ok": False, "error": "sandbox_package_installer_unavailable"}
        workspace = self.workspace_for(user_id, conversation_id)
        cwd = self.resolve_workdir(workspace, workdir)
        requested_timeout = float(
            self.limits.max_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if not math.isfinite(requested_timeout) or requested_timeout <= 0:
            raise SandboxError("timeout_seconds must be a finite positive number")
        timeout = min(
            self.limits.max_timeout_seconds,
            max(0.1, requested_timeout),
        )
        argv = self._bwrap_argv(
            runtime,
            workspace,
            cwd,
            command,
            allow_network=allow_network,
        )
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                preexec_fn=lambda: _set_limits(self.limits),
            )
        except OSError as error:
            return {
                "ok": False,
                "error": "sandbox_start_failed",
                "detail": str(error),
            }

        try:
            stdout_task = asyncio.create_task(
                self._read_limited(process.stdout, self.limits.max_output_chars)
            )
            stderr_task = asyncio.create_task(
                self._read_limited(process.stderr, self.limits.max_output_chars)
            )
            await asyncio.wait_for(process.wait(), timeout=timeout)
            try:
                stdout, stdout_truncated = await asyncio.wait_for(
                    stdout_task, timeout=0.5
                )
                stderr, stderr_truncated = await asyncio.wait_for(
                    stderr_task, timeout=0.5
                )
            except asyncio.TimeoutError:
                # A descendant can inherit the pipes after the shell exits.
                # Do not let that orphan keep an Agent turn blocked forever.
                self._terminate_process_group(process)
                stdout_task.cancel()
                stderr_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stdout_task
                with suppress(asyncio.CancelledError):
                    await stderr_task
                stdout, stderr = "", ""
                stdout_truncated = stderr_truncated = True
            return self._result(
                process.returncode,
                stdout,
                stderr,
                stdout_truncated or stderr_truncated,
                started,
            )
        except asyncio.TimeoutError:
            stdout_task.cancel()
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stdout_task
            with suppress(asyncio.CancelledError):
                await stderr_task
            self._terminate_process_group(process)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=1.0)
            try:
                stdout, _ = await asyncio.wait_for(
                    self._read_limited(process.stdout, self.limits.max_output_chars),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                stdout = ""
            try:
                stderr, _ = await asyncio.wait_for(
                    self._read_limited(process.stderr, self.limits.max_output_chars),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                stderr = ""
            result = self._result(
                process.returncode,
                stdout,
                stderr,
                True,
                started,
            )
            result["timed_out"] = True
            result["error"] = "sandbox_timeout"
            return result

    async def execute_code(
        self,
        *,
        user_id: str,
        conversation_id: str,
        code: str,
        language: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run an interpreted code block through the same isolated command path."""

        source = code.strip()
        if not source:
            raise SandboxError("code cannot be blank")
        command = self._code_command(source, language)
        return await self.execute(
            user_id=user_id,
            conversation_id=conversation_id,
            command=command,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _code_command(code: str, language: str) -> str:
        normalized = language.strip().lower()
        aliases = {
            "py": "python",
            "python3": "python",
            "js": "javascript",
            "node": "javascript",
            "sh": "shell",
            "bash": "shell",
            "zsh": "shell",
        }
        normalized = aliases.get(normalized, normalized)
        interpreters = {
            "python": ("python3", "-c"),
            "javascript": ("node", "-e"),
            "shell": ("/bin/sh", "-c"),
            "ruby": ("ruby", "-e"),
            "perl": ("perl", "-e"),
            "php": ("php", "-r"),
        }
        try:
            executable, flag = interpreters[normalized]
        except KeyError as error:
            raise SandboxError(
                f"暂不支持直接运行 {language!r} 代码，请使用 Python、JavaScript、Shell、Ruby、Perl 或 PHP"
            ) from error
        # shlex.quote keeps source code one argument to the interpreter. The
        # outer sandbox shell therefore cannot reinterpret quotes or newlines.
        return " ".join(shlex.quote(value) for value in (executable, flag, code))

    def _bwrap_argv(
        self,
        runtime: str,
        workspace: Path,
        cwd: str,
        command: str,
        *,
        allow_network: bool = False,
    ) -> list[str]:
        argv = [
            runtime,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
        ]
        # Normal code execution remains network-isolated.  A trusted caller may
        # temporarily share the host namespace for a policy-validated package
        # install; the subsequent user program is still run without networking.
        if allow_network:
            argv.append("--share-net")
        argv.append("--clearenv")
        for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
            if Path(path).exists():
                argv.extend(("--ro-bind", path, path))
        argv.extend(
            (
                "--bind",
                str(workspace),
                "/workspace",
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--chdir",
                cwd,
                "--setenv",
                "HOME",
                "/workspace/.home",
                "--setenv",
                "PATH",
                "/usr/local/bin:/usr/bin:/bin",
                "--setenv",
                "LANG",
                "C.UTF-8",
            )
        )
        if allow_network:
            # The compute-node system Python intentionally has no pip module.
            # Expose only the backend environment's pip package (read-only),
            # and only to the trusted dependency-install invocation.
            assert self.pip_package_path is not None
            argv.extend(
                (
                    "--dir",
                    "/opt",
                    "--dir",
                    "/opt/esa-installer",
                    "--ro-bind",
                    str(self.pip_package_path),
                    "/opt/esa-installer/pip",
                )
            )
            for env_name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "NO_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "no_proxy",
                "all_proxy",
                "SSL_CERT_FILE",
            ):
                value = os.environ.get(env_name)
                if value:
                    argv.extend(("--setenv", env_name, value))
        # Set the process hard limit after Bubblewrap has entered its private
        # user/PID namespaces.  This preserves fork-bomb protection without
        # counting unrelated processes belonging to the same HPC account.
        argv.extend(
            (
                "/usr/bin/prlimit",
                f"--nproc={self.limits.process_count}:{self.limits.process_count}",
                "--",
                "/bin/sh",
                "-lc",
                command,
            )
        )
        return argv

    async def _read_limited(
        self, stream: asyncio.StreamReader | None, limit: int
    ) -> tuple[str, bool]:
        if stream is None:
            return "", False
        chunks: list[bytes] = []
        total = 0
        truncated = False
        while True:
            block = await stream.read(8192)
            if not block:
                break
            kept_length = 0
            if total < limit:
                kept = block[: limit - total]
                chunks.append(kept)
                total += len(kept)
                kept_length = len(kept)
            if len(block) > kept_length:
                truncated = True
        return b"".join(chunks).decode("utf-8", errors="replace"), truncated

    @staticmethod
    def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if process.returncode is None:
                process.kill()

    def _result(
        self,
        returncode: int | None,
        stdout: str,
        stderr: str,
        truncated: bool,
        started: float,
    ) -> dict[str, Any]:
        return {
            "ok": returncode == 0,
            "exit_code": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output_truncated": truncated,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "workspace": "/workspace",
        }
