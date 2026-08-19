# backend/tests/test_context_orchestrator_entry.py

"""验证 `context_orchestrator_entry` 相关行为与回归场景。"""

from types import SimpleNamespace

from backend.core.utils.models import MemorySettings, SessionPrincipal, UserRecord
from backend.core.web.routers.chat import _prepare_message
from backend.core.web.schemas import SendMessageRequest


class ChatStore:
    """封装 `chat store` 数据持久化操作。"""
    def get_conversation(self, conversation_id):
        """获取 `conversation` 相关数据。"""
        return {"id": conversation_id, "user_id": "u1", "group_id": None}

    def get_compressed_model_history_and_append(self, conversation_id, messages):
        """获取 `compressed model history and append` 相关数据。

        Args:
            conversation_id: object => 对话 ID。
            messages: object => 消息列表。

        Returns:
            object => 处理结果。
        """
        return None, [{"role": "user", "content": messages[0]["content"]}]

    def latest_message_id(self, conversation_id):
        """返回刚写入用户消息的测试 ID。"""
        return 1


class UserStore:
    """封装 `user store` 数据持久化操作。"""
    user = UserRecord(
        id="u1",
        username="alice",
        password_hash="h",
        status="active",
    )

    def get_by_id(self, user_id):
        """获取 `by id` 相关数据。"""
        return self.user

    def get_memory_settings(self, user_id):
        """获取 `memory settings` 相关数据。"""
        return MemorySettings(user_id=user_id)


class Resolver:
    """封装 `Resolver` 的状态与行为。"""
    def resolve(self, text, *, limit):
        """解析 `resolve` 相关数据。

        Args:
            text: object => 待处理文本。
            limit: object => 返回数量上限。

        Returns:
            object => 处理结果。
        """
        assert text == "给我讲讲二叉树"
        assert limit == 3
        return [SimpleNamespace(kp_id="二叉树")]


class ProfileBuilder:
    """封装 `ProfileBuilder` 的状态与行为。"""
    def __init__(self):
        """初始化 `ProfileBuilder` 实例。"""
        self.query = None

    def build(self, query):
        """构建 `build` 相关数据。"""
        self.query = query
        return SimpleNamespace(marker="profile")


class PendingPracticeChatStore(ChatStore):
    """返回一条已发出但尚未批改的练习题。"""

    def get_compressed_model_history_and_append(self, conversation_id, messages):
        return None, [
            {"role": "assistant", "content": "【练习题｜知识点：链表】\n判断头结点。"},
            {"role": "user", "content": messages[0]["content"]},
        ]


class PendingPracticeResolver:
    """模拟服务端将练习题标签解析为 canonical kp_id。"""

    def resolve(self, text, *, limit):
        if text == "链表":
            return [SimpleNamespace(kp_id="链表", score=1.0)]
        return []


def test_chat_preparation_passes_resolved_points_to_profile_builder():
    """验证 `chat_preparation_passes_resolved_points_to_profile_builder` 场景。"""
    profile_builder = ProfileBuilder()
    state = SimpleNamespace(
        chat_store=ChatStore(),
        user_store=UserStore(),
        kp_resolver=Resolver(),
        profile_builder=profile_builder,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    context = _prepare_message(
        request,
        "conversation-1",
        SendMessageRequest(content="给我讲讲二叉树"),
        SessionPrincipal(session_id="s1", user_id="u1"),
    )

    assert profile_builder.query.resolved_kp_ids == ["二叉树"]
    assert context.user_profile_context.marker == "profile"


def test_chat_preparation_binds_pending_practice_to_canonical_kp_id():
    """短答案仍继承服务端解析出的待作答练习知识点。"""
    profile_builder = ProfileBuilder()
    state = SimpleNamespace(
        chat_store=PendingPracticeChatStore(),
        user_store=UserStore(),
        kp_resolver=PendingPracticeResolver(),
        profile_builder=profile_builder,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    context = _prepare_message(
        request,
        "conversation-1",
        SendMessageRequest(content="B"),
        SessionPrincipal(session_id="s1", user_id="u1"),
    )

    assert context.resolved_kp_ids == ()
    assert context.pending_practice_kp_id == "链表"
