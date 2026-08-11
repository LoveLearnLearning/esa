from types import SimpleNamespace

from backend.core.utils.models import MemorySettings, SessionPrincipal, UserRecord
from backend.core.web.routers.chat import _prepare_message
from backend.core.web.schemas import SendMessageRequest


class ChatStore:
    def get_conversation(self, conversation_id):
        return {"id": conversation_id, "user_id": "u1", "group_id": None}

    def get_compressed_model_history_and_append(self, conversation_id, messages):
        return None, [{"role": "user", "content": messages[0]["content"]}]


class UserStore:
    user = UserRecord(
        id="u1",
        username="alice",
        password_hash="h",
        status="active",
    )

    def get_by_id(self, user_id):
        return self.user

    def get_memory_settings(self, user_id):
        return MemorySettings(user_id=user_id)


class Resolver:
    def resolve(self, text, *, limit):
        assert text == "给我讲讲二叉树"
        assert limit == 3
        return [SimpleNamespace(kp_id="二叉树")]


class ProfileBuilder:
    def __init__(self):
        self.query = None

    def build(self, query):
        self.query = query
        return SimpleNamespace(marker="profile")


def test_chat_preparation_passes_resolved_points_to_profile_builder():
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
