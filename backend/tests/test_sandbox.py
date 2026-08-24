"""Tests for the context-bound command sandbox."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from backend.sandbox.sandbox import SandboxError, SandboxLimits, SandboxService


def test_workspace_isolated_by_user_and_conversation(tmp_path: Path) -> None:
    service = SandboxService(tmp_path, enabled=True, runtime="missing-bwrap")

    first = service.workspace_for("user-a", "conversation-1")
    second = service.workspace_for("user-b", "conversation-1")
    third = service.workspace_for("user-a", "conversation-2")

    assert first != second
    assert first != third
    assert first.is_dir()
    assert (first / ".home").is_dir()
    if os.name == "posix":
        assert oct(first.stat().st_mode & 0o777) == "0o700"


def test_workdir_cannot_escape_workspace(tmp_path: Path) -> None:
    service = SandboxService(tmp_path, enabled=True, runtime="missing-bwrap")
    workspace = service.workspace_for("user", "conversation")

    with pytest.raises(SandboxError):
        service.resolve_workdir(workspace, "../outside")
    with pytest.raises(SandboxError):
        service.resolve_workdir(workspace, "/etc")


def test_disabled_and_missing_runtime_fail_closed(tmp_path: Path) -> None:
    disabled = SandboxService(tmp_path, enabled=False)
    unavailable = SandboxService(tmp_path, enabled=True, runtime="missing-bwrap")

    assert asyncio.run(
        disabled.execute(user_id="u", conversation_id="c", command="echo hi")
    ) == {"ok": False, "error": "sandbox_disabled"}
    result = asyncio.run(
        unavailable.execute(user_id="u", conversation_id="c", command="echo hi")
    )
    assert result["ok"] is False
    assert result["error"] == "sandbox_runtime_unavailable"


def test_bwrap_command_is_network_and_home_isolated(tmp_path: Path) -> None:
    service = SandboxService(
        tmp_path,
        enabled=True,
        runtime="bwrap",
        limits=SandboxLimits(max_timeout_seconds=2),
    )
    workspace = service.workspace_for("u", "c")
    argv = service._bwrap_argv("/usr/bin/bwrap", workspace, "/workspace", "echo ok")

    assert "--unshare-all" in argv
    assert "--share-net" not in argv
    assert "--clearenv" in argv
    assert "--bind" in argv
    assert "/workspace" in argv
    assert "--setenv" in argv
    assert "HOME" in argv
    assert "/usr/bin/prlimit" in argv
    assert "--nproc=64:64" in argv


def test_trusted_install_can_share_network_without_changing_default(
    tmp_path: Path,
) -> None:
    service = SandboxService(tmp_path, enabled=True, runtime="bwrap")
    workspace = service.workspace_for("u", "c")
    argv = service._bwrap_argv(
        "/usr/bin/bwrap",
        workspace,
        "/workspace",
        "python3 -m pip --version",
        allow_network=True,
    )

    assert argv.index("--share-net") > argv.index("--unshare-all")
    assert "/opt/esa-installer/pip" in argv


def test_code_command_quotes_source_and_normalizes_languages() -> None:
    command = SandboxService._code_command("print('a\n$HOME')", "py")
    assert command.startswith("python3 -c ")
    assert "$HOME" in command
    assert SandboxService._code_command("console.log('ok')", "js").startswith(
        "node -e "
    )
    with pytest.raises(SandboxError, match="暂不支持"):
        SandboxService._code_command("int main() {}", "cpp")
