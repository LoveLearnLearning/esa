"""上下文隔离相关回归测试

覆盖:
- RC#1: 用户级 TempMemory 已删除 system prompt 不再注入跨对话临时记忆
- RC#3: ChatStore 原子化"读历史+追加消息" 消除读-写竞态
- RC#4: 会话记忆模式接线 (normal/no_write/isolated) 写入工具按模式拒绝
"""
import pytest

from backend.agent.memories.core_memory_models import MemoryPolicyDenied
from backend.agent.memories.core_memory_policy import CoreMemoryPolicy
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.core.router.models import ResourceScope, WorkspaceRoute
from backend.core.message.build_prompt import build_system_prompt
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import PromptContext, UserRecord


def test_system_prompt_no_longer_contains_temp_memory_section():
    """RC#1: 用户级 TempMemory 注入已删除 prompt 不应再包含临时记忆分节。"""
    prompt = build_system_prompt(
        user_name="tester",
        prompt_ctx=PromptContext(),
    )
    assert "# 临时记忆" not in prompt


def test_get_model_history_and_append_is_atomic(tmp_path):
    """RC#3: 原子方法返回追加前的历史 且消息在同一事务内落库。"""
    db_path = tmp_path / "chat.db"
    user_store = UserStore(db_path)
    assert user_store.create(
        UserRecord(
            id="u1",
            username="u1",
            password_hash="hash",
            status="active",
        )
    )
    GroupStore(db_path)
    chat_store = ChatStore(db_path)
    conversation = chat_store.create_conversation(user_id="u1")
    conversation_id = conversation["conversation_id"]

    chat_store.append_messages(
        conversation_id,
        [{"role": "user", "content": "第一条", "is_visible": True}],
    )

    history = chat_store.get_model_history_and_append(
        conversation_id,
        [{"role": "user", "content": "第二条", "is_visible": True}],
    )

    # 返回的是追加前的历史
    assert [m["content"] for m in history] == ["第一条"]
    # 新消息已持久化
    assert [m["content"] for m in chat_store.get_model_messages(conversation_id)] == [
        "第一条",
        "第二条",
    ]


def test_get_model_history_and_append_raises_for_missing_conversation(tmp_path):
    """RC#3: 对话不存在时原子方法抛错 且不产生脏数据。"""
    chat_store = ChatStore(tmp_path / "chat.db")

    try:
        chat_store.get_model_history_and_append(
            "no-such-conversation",
            [{"role": "user", "content": "x"}],
        )
        assert False, "应当抛出 ValueError"
    except ValueError:
        pass

    assert chat_store.get_model_messages("no-such-conversation") == []


def _memory_context(mode: str) -> ToolExecutionContext:
    scope = ResourceScope(metadata={"conversation_id": "c1"})
    route = WorkspaceRoute(
        workspace_type="learning", agent_profile_id="learning.v1",
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}), prompt_key="learning.v1",
        profile_policy="learning.profile.v1", memory_policy_id="learning.memory.v1",
        resource_scope=scope, action_policy="learning.actions.v1",
    )
    return ToolExecutionContext(
        user_id="u1", conversation_id="c1", workspace_route=route,
        authorized_resources=scope, conversation_mode=mode,
        runtime_dependencies=AgentRuntimeDependencies(username="tester"),
        request_id="r1",
    )


def test_memory_write_policy_allows_only_normal_mode():
    policy = CoreMemoryPolicy()
    policy.ensure_write(_memory_context("normal"))
    for mode in ("no_write", "isolated"):
        with pytest.raises(MemoryPolicyDenied):
            policy.ensure_write(_memory_context(mode))
