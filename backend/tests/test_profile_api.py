"""Profile V2 API 端点测试

覆盖 SubTask 13.3:
- GET /me/profile 结构化响应
- PATCH /me/profile/explicit 只更新显式字段
- GET /me/profile/sources 来源解释
- DELETE /me/profile/inferred/{field_key} 抑制推断字段
- GET/PATCH /me/memory-settings 开关读写
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.stores.profile_store import ProfileStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.routers.preferences import (
    memory_settings_router,
    profile_router,
)

# ===== Stub stores 与 fixtures =====


class StubMasteryStore:
    def get(self, user_name, kp_id):
        return None

    def get_weak_prerequisites(
        self, user_name, kp_id, kg_store, mastery_threshold=50.0, max_depth=5
    ):
        return []


class StubKGStore:
    def list_all(self):
        return []


class StubCoreMemory:
    def get_all(self, user_name):
        return []


def _make_user() -> UserRecord:
    return UserRecord(
        id="u1",
        username="alice",
        password_hash="h",
        status="active",
        preferred_style="concise",
        preferred_tone="friendly",
        custom_instruction="",
        major="cs",
        grade="大二",
        current_week=3,
        total_weeks=18,
        profile_enabled=True,
        learning_profile_enabled=True,
        inferred_profile_enabled=True,
    )


def _make_session() -> SessionPrincipal:
    return SessionPrincipal(
        session_id="s1",
        user_id="u1",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _create_app(tmp_path) -> FastAPI:
    """构造最小 FastAPI app 仅挂载 profile 与 memory_settings 路由

    使用真实的 UserStore / ProfileStore (tmp_path 临时库) 和 stub mastery/kg/core_memory。
    """
    db_path = tmp_path / "test_api.db"
    user_store = UserStore(db_path)
    user_store.create(_make_user())

    profile_store = ProfileStore(db_path)
    profile_builder = ProfileBuilder(
        user_store=user_store,
        mastery_store=StubMasteryStore(),
        kg_store=StubKGStore(),
        core_memory=StubCoreMemory(),
        profile_store=profile_store,
    )

    app = FastAPI()
    app.state.user_store = user_store
    app.state.profile_store = profile_store
    app.state.profile_builder = profile_builder

    app.include_router(profile_router)
    app.include_router(memory_settings_router)

    # 覆盖 get_current_session 依赖 跳过 Bearer token 校验
    from backend.core.web.deps import get_current_session

    def _override_session():
        return _make_session()

    app.dependency_overrides[get_current_session] = _override_session
    return app


# ===== 测试用例 =====


def test_get_profile_returns_structured_view(tmp_path):
    """GET /me/profile 返回完整 ProfileView 含 explicit/preferences/profile_version"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.get("/me/profile")
    assert resp.status_code == 200
    body = resp.json()

    # 结构化分节存在
    assert "explicit" in body
    assert "preferences" in body
    assert "learning_state" in body
    assert "inferred_patterns" in body
    assert "profile_version" in body
    assert "generated_at" in body

    # explicit 包含 major 字段 origin=explicit_setting confidence=1.0
    explicit_fields = {item["field"]: item for item in body["explicit"]}
    assert "major" in explicit_fields
    assert explicit_fields["major"]["value"] == "cs"
    assert explicit_fields["major"]["origin"] == "explicit_setting"
    assert explicit_fields["major"]["confidence"] == 1.0


def test_patch_profile_explicit_updates_only_explicit_fields(tmp_path):
    """PATCH /me/profile/explicit 更新显式字段后返回最新画像视图"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/me/profile/explicit",
        json={"grade": "大三", "current_week": 5},
    )
    assert resp.status_code == 200
    body = resp.json()

    # 更新后 explicit 中 grade 应为新值
    explicit_fields = {item["field"]: item for item in body["explicit"]}
    assert explicit_fields["grade"]["value"] == "大三"
    assert explicit_fields["current_week"]["value"] == 5


def test_patch_profile_explicit_validates_style_enum(tmp_path):
    """PATCH /me/profile/explicit 传入非法 style 时返回 400"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/me/profile/explicit",
        json={"preferred_style": "invalid_style"},
    )
    assert resp.status_code == 400


def test_get_profile_sources_returns_not_found_for_missing(tmp_path):
    """GET /me/profile/sources 未命中字段时 found=False"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.get("/me/profile/sources", params={"field_key": "nonexistent"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False


def test_get_profile_sources_returns_source_for_existing(tmp_path):
    """GET /me/profile/sources 命中字段时返回 origin/confidence/source_memory_ids"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    # 先写入一条推断维度
    profile_store: ProfileStore = app.state.profile_store
    profile_store.upsert_dimension(
        user_id="u1",
        field_key="preferred_code_language",
        value="Python",
        origin="inferred_pattern",
        confidence=0.7,
        source_memory_ids=["mem_001"],
    )

    resp = client.get(
        "/me/profile/sources",
        params={"field_key": "preferred_code_language"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["origin"] == "inferred_pattern"
    assert body["confidence"] == 0.7
    assert "mem_001" in body["source_memory_ids"]


def test_delete_inferred_field_suppresses_and_returns_success(tmp_path):
    """DELETE /me/profile/inferred/{field_key} 抑制字段后返回 deleted=True"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    # 先写入一条推断维度
    profile_store: ProfileStore = app.state.profile_store
    profile_store.upsert_dimension(
        user_id="u1",
        field_key="preferred_code_language",
        value="Python",
        origin="inferred_pattern",
        confidence=0.7,
    )

    resp = client.delete("/me/profile/inferred/preferred_code_language")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["field_key"] == "preferred_code_language"

    # 再次删除应返回 404 (已被抑制)
    resp2 = client.delete("/me/profile/inferred/preferred_code_language")
    assert resp2.status_code == 404


def test_delete_inferred_nonexistent_returns_404(tmp_path):
    """DELETE /me/profile/inferred/{field_key} 不存在时返回 404"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.delete("/me/profile/inferred/nonexistent_field")
    assert resp.status_code == 404


def test_get_memory_settings_returns_defaults_when_unset(tmp_path):
    """GET /me/memory-settings 未配置时返回默认值(两项均 true)"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.get("/me/memory-settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["learning_profile_enabled"] is True
    assert body["inferred_profile_enabled"] is True
    assert body["default_conversation_mode"] == "normal"


def test_patch_memory_settings_updates_switches(tmp_path):
    """PATCH /me/memory-settings 更新开关后返回最新值"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/me/memory-settings",
        json={"learning_profile_enabled": False, "default_conversation_mode": "isolated"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["learning_profile_enabled"] is False
    assert body["inferred_profile_enabled"] is True  # 未传的保持默认
    assert body["default_conversation_mode"] == "isolated"

    # 再次 GET 确保持久化
    resp2 = client.get("/me/memory-settings")
    body2 = resp2.json()
    assert body2["learning_profile_enabled"] is False
    assert body2["default_conversation_mode"] == "isolated"


def test_patch_memory_settings_validates_conversation_mode(tmp_path):
    """PATCH /me/memory-settings 传入非法 mode 时返回 400"""
    app = _create_app(tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/me/memory-settings",
        json={"default_conversation_mode": "invalid_mode"},
    )
    assert resp.status_code == 400
