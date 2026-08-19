# backend/tests/test_memory_mode_guards.py

"""验证 `memory_mode_guards` 相关行为与回归场景。"""

import pytest

from backend.agent.memories.core_memory_models import MemoryPolicyDenied
from backend.agent.memories.core_memory_policy import CoreMemoryPolicy
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.core.router.models import ResourceScope, WorkspaceRoute


def _context(mode: str, user_id: str = "u1") -> ToolExecutionContext:
    """处理 `_context` 相关逻辑。"""
    scope = ResourceScope(metadata={"conversation_id": "c1"})
    route = WorkspaceRoute(
        workspace_type="learning", agent_profile_id="learning.v1",
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}), prompt_key="learning.v1",
        profile_policy="learning.profile.v1", memory_policy_id="learning.memory.v1",
        resource_scope=scope, action_policy="learning.actions.v1",
    )
    return ToolExecutionContext(
        user_id=user_id, conversation_id="c1", workspace_route=route,
        authorized_resources=scope, conversation_mode=mode,
        runtime_dependencies=AgentRuntimeDependencies(), username=user_id,
        request_id="r1",
    )


def test_isolated_mode_blocks_reads_and_writes():
    """验证 `isolated_mode_blocks_reads_and_writes` 场景。"""
    policy = CoreMemoryPolicy()
    with pytest.raises(MemoryPolicyDenied):
        policy.ensure_read(_context("isolated"))
    with pytest.raises(MemoryPolicyDenied):
        policy.ensure_write(_context("isolated"))


def test_no_write_mode_still_allows_reads():
    """验证 `no_write_mode_still_allows_reads` 场景。"""
    policy = CoreMemoryPolicy()
    policy.ensure_read(_context("no_write"))


def test_saved_memory_preference_blocks_reads_and_writes():
    """验证关闭已保存记忆后读写均被拒绝。"""

    class _Settings:
        """提供关闭状态的测试设置。"""
        saved_memory_enabled = False

    class _Users:
        """提供测试用户记忆设置读取接口。"""

        def get_memory_settings(self, _user_id):
            """返回关闭已保存记忆的设置。"""
            return _Settings()

    context = _context("normal")
    object.__setattr__(
        context,
        "runtime_dependencies",
        AgentRuntimeDependencies(user_store=_Users()),
    )
    policy = CoreMemoryPolicy()
    with pytest.raises(MemoryPolicyDenied, match="disabled"):
        policy.ensure_read(context)
    with pytest.raises(MemoryPolicyDenied, match="disabled"):
        policy.ensure_write(context)
    with pytest.raises(MemoryPolicyDenied):
        policy.ensure_write(_context("no_write"))


def test_context_keeps_trusted_users_isolated():
    """验证 `context_keeps_trusted_users_isolated` 场景。"""
    assert _context("normal", "alice").user_id == "alice"
    assert _context("normal", "bob").user_id == "bob"
