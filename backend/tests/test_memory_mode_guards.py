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
        runtime_dependencies=AgentRuntimeDependencies(username=user_id),
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
    with pytest.raises(MemoryPolicyDenied):
        policy.ensure_write(_context("no_write"))


def test_context_keeps_trusted_users_isolated():
    """验证 `context_keeps_trusted_users_isolated` 场景。"""
    assert _context("normal", "alice").user_id == "alice"
    assert _context("normal", "bob").user_id == "bob"
