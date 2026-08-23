"""Tests for auxiliary-model-assisted code execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from backend.core.services.auxiliary_llm_service import AuxiliaryLLMUnavailable
from backend.core.services.code_execution_service import CodeExecutionService


class _LLM:
    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> str:
        del max_tokens, temperature
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _Sandbox:
    def __init__(self, root: Path, *run_results: dict[str, Any]) -> None:
        self.root = root
        self.run_results = list(run_results)
        self.calls: list[dict[str, Any]] = []

    def workspace_for(self, user_id: str, conversation_id: str) -> Path:
        workspace = self.root / user_id / conversation_id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if "pip install" in kwargs["command"]:
            return {"ok": True, "returncode": 0, "stdout": "installed", "stderr": ""}
        if self.run_results:
            return self.run_results.pop(0)
        return {"ok": True, "returncode": 0, "stdout": "ok\n", "stderr": ""}


def _payload(**overrides: Any) -> str:
    value = {
        "language": "python",
        "code": "print('ok')",
        "dependencies": [],
        "notes": [],
    }
    value.update(overrides)
    return json.dumps(value)


def test_python_dependencies_are_import_bound_and_allowlisted(tmp_path: Path) -> None:
    llm = _LLM(
        _payload(
            code="import requests\nprint(requests.__name__)",
            dependencies=["requests", "evil-package"],
            notes=["补充依赖"],
        )
    )
    sandbox = _Sandbox(tmp_path)
    service = CodeExecutionService(
        llm_client=llm,  # type: ignore[arg-type]
        sandbox_service=sandbox,  # type: ignore[arg-type]
        package_install_enabled=True,
    )

    result = asyncio.run(
        service.execute(
            user_id="u",
            conversation_id="c",
            language="py",
            code="print('ok')",
        )
    )

    assert result["ok"] is True
    assert result["dependencies"] == ["requests"]
    assert result["rejected_dependencies"] == ["evil-package"]
    install_call, run_call = sandbox.calls
    assert install_call["allow_network"] is True
    assert "requests" in install_call["command"]
    assert "evil-package" not in install_call["command"]
    assert run_call.get("allow_network", False) is False
    source = next(tmp_path.rglob("main.py"))
    assert source.read_text(encoding="utf-8").startswith("import requests")


def test_execution_error_gets_one_model_repair(tmp_path: Path) -> None:
    llm = _LLM(
        _payload(language="cpp", code="int main() { missing(); }"),
        _payload(
            language="cpp",
            code="#include <iostream>\nint main(){std::cout << 42;}",
            notes=["补充标准头文件并修复调用"],
        ),
    )
    sandbox = _Sandbox(
        tmp_path,
        {"ok": False, "returncode": 1, "stdout": "", "stderr": "missing not declared"},
        {"ok": True, "returncode": 0, "stdout": "42", "stderr": ""},
    )
    service = CodeExecutionService(
        llm_client=llm,  # type: ignore[arg-type]
        sandbox_service=sandbox,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        service.execute(
            user_id="u",
            conversation_id="c",
            language="c++",
            code="int main() { missing(); }",
        )
    )

    assert result["ok"] is True
    assert result["attempt_count"] == 2
    assert "#include <iostream>" in result["code"]
    repair_input = json.loads(llm.calls[1][1]["content"])
    assert "missing not declared" in repair_input["execution_error"]


def test_invalid_auxiliary_response_falls_back_to_original_code(tmp_path: Path) -> None:
    llm = _LLM(AuxiliaryLLMUnavailable("offline"))
    sandbox = _Sandbox(tmp_path)
    service = CodeExecutionService(
        llm_client=llm,  # type: ignore[arg-type]
        sandbox_service=sandbox,  # type: ignore[arg-type]
        repair_attempts=0,
    )

    result = asyncio.run(
        service.execute(
            user_id="u",
            conversation_id="c",
            language="python",
            code="print(7)",
        )
    )

    assert result["ok"] is True
    assert result["model_used"] is False
    assert result["code"] == "print(7)"
    assert result["warnings"]


def test_model_cannot_supply_a_shell_command(tmp_path: Path) -> None:
    llm = _LLM(
        _payload(
            code="print('safe')",
            dependencies=["requests; touch /workspace/pwned"],
        )
    )
    sandbox = _Sandbox(tmp_path)
    service = CodeExecutionService(
        llm_client=llm,  # type: ignore[arg-type]
        sandbox_service=sandbox,  # type: ignore[arg-type]
        package_install_enabled=True,
    )

    result = asyncio.run(
        service.execute(
            user_id="u",
            conversation_id="c",
            language="python",
            code="print('safe')",
        )
    )

    assert result["rejected_dependencies"] == [
        "requests; touch /workspace/pwned"
    ]
    assert all("touch" not in call["command"] for call in sandbox.calls)


def test_model_cannot_switch_the_requested_language(tmp_path: Path) -> None:
    llm = _LLM(
        _payload(
            language="shell",
            code="touch /workspace/pwned",
        )
    )
    sandbox = _Sandbox(tmp_path)
    service = CodeExecutionService(
        llm_client=llm,  # type: ignore[arg-type]
        sandbox_service=sandbox,  # type: ignore[arg-type]
        repair_attempts=0,
    )

    result = asyncio.run(
        service.execute(
            user_id="u",
            conversation_id="c",
            language="python",
            code="print('safe')",
        )
    )

    assert result["ok"] is True
    assert result["language"] == "python"
    assert result["code"] == "print('safe')"
    assert sandbox.calls[0]["command"].endswith("python3 main.py")


def test_unsupported_language_is_rejected_before_model_call(tmp_path: Path) -> None:
    llm = _LLM(_payload())
    service = CodeExecutionService(
        llm_client=llm,  # type: ignore[arg-type]
        sandbox_service=_Sandbox(tmp_path),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="unsupported"):
        asyncio.run(
            service.execute(
                user_id="u",
                conversation_id="c",
                language="sql",
                code="select 1",
            )
        )
    assert llm.calls == []
