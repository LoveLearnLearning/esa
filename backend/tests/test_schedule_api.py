# backend/tests/test_schedule_api.py

"""验证 `schedule_api` 相关行为与回归场景。"""

import io

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.core.services.schedule_import_service import ExtractedScheduleDocument
from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.routers import schedule
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore


class _LLMClient:
    """封装 `_LLMClient` 的状态与行为。"""
    async def chat(self, messages, *, max_tokens, temperature):
        """处理 `chat` 相关逻辑。

        Args:
            messages: object => 消息列表。
            max_tokens: object => `max_tokens` 参数。
            temperature: object => `temperature` 参数。

        Returns:
            object => 处理结果。
        """
        content = messages[-1]["content"]
        if isinstance(content, list):
            assert any(part.get("type") == "image_url" for part in content)
        else:
            assert "数据结构" in content
        assert max_tokens > 0
        assert temperature == 0.0
        return """[
          {
            "name": "数据结构",
            "teacher": "张老师",
            "location": "A101",
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "start_week": 1,
            "end_week": 18
          }
        ]"""


def _schedule_png() -> bytes:
    """处理 `_schedule_png` 相关逻辑。"""
    output = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(output, format="PNG")
    return output.getvalue()


def _app(tmp_path, monkeypatch):
    """处理 `_app` 相关逻辑。"""
    database = tmp_path / "schedule-api.db"
    user_store = UserStore(database)
    user = UserRecord(
        id="user-id",
        username="alice",
        password_hash="hash",
        status="active",
    )
    assert user_store.create(user)
    app = FastAPI()
    app.state.user_store = user_store
    app.state.schedule_store = ScheduleStore(database)
    app.state.user_course_store = UserCourseStore(database)
    app.state.auxiliary_llm_client = _LLMClient()
    app.state.knowledge_graph_store = KnowledgeGraphStore(tmp_path / "kg.db")
    app.include_router(schedule.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="session", user_id=user.id
    )
    monkeypatch.setattr(
        app.state.knowledge_graph_store, "resolve_course_name", lambda name: name
    )
    return app


def test_schedule_crud_and_html_model_import(tmp_path, monkeypatch):
    """验证 `schedule_crud_and_html_model_import` 场景。"""
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    initial = client.get("/me/schedule")
    saved = client.put(
        "/me/schedule/courses",
        json={
            "name": "操作系统",
            "teacher": "李老师",
            "location": "B201",
            "weekday": 2,
            "start_period": 3,
            "end_period": 4,
            "start_week": 1,
            "end_week": 18,
            "color_value": 4280701931,
        },
    )
    imported = client.post(
        "/me/schedule/import",
        files={
            "file": (
                "schedule.html",
                b"<html><body>Monday: Data Structure / \xe6\x95\xb0\xe6\x8d\xae\xe7\xbb\x93\xe6\x9e\x84</body></html>",
                "text/html",
            )
        },
    )
    final = client.get("/me/schedule")

    assert initial.status_code == 200
    assert initial.json()["courses"] == []
    assert saved.status_code == 200
    assert imported.status_code == 200
    assert imported.json()["imported_count"] == 1
    assert len(final.json()["courses"]) == 2
    assert client.delete(
        f"/me/schedule/courses/{saved.json()['id']}"
    ).status_code == 204
    names = [
        item["name"] for item in app.state.user_course_store.list_for_user("user-id")
    ]
    assert "操作系统" not in names
    assert "数据结构" in names


def test_schedule_image_import_uses_multimodal_auxiliary_model(
    tmp_path, monkeypatch
):
    """验证 `schedule_image_import_uses_multimodal_auxiliary_model` 场景。"""
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)

    imported = client.post(
        "/me/schedule/import",
        files={"file": ("schedule.png", _schedule_png(), "image/png")},
    )

    assert imported.status_code == 200
    assert imported.json()["imported_count"] == 1
    assert imported.json()["courses"][0]["name"] == "数据结构"


def test_schedule_table_management_and_import_to_new_table(tmp_path, monkeypatch):
    """验证 `schedule_table_management_and_import_to_new_table` 场景。"""
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)

    initial = client.get("/me/schedule").json()
    assert len(initial["tables"]) == 1
    assert initial["tables"][0]["is_active"]
    default_id = initial["active_table_id"]

    created = client.post("/me/schedule/tables", json={"name": "大二上"})
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert client.get("/me/schedule").json()["active_table_id"] == new_id

    renamed = client.patch(
        f"/me/schedule/tables/{new_id}", json={"name": "大二上学期"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "大二上学期"

    imported = client.post(
        "/me/schedule/import",
        data={"target": "new", "table_name": "导入的课表"},
        files={"file": ("schedule.html", "<p>数据结构</p>".encode(), "text/html")},
    )
    assert imported.status_code == 200
    body = imported.json()
    assert body["imported_count"] == 1
    imported_table_id = body["active_table_id"]
    assert imported_table_id not in {default_id, new_id}
    assert {t["name"] for t in body["tables"]} == {"默认课表", "大二上学期", "导入的课表"}
    assert body["courses"][0]["table_id"] == imported_table_id

    # 切回默认表看不到导入的课
    activated = client.post(f"/me/schedule/tables/{default_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["courses"] == []

    # 删除导入的课表连带清理 timetable 来源的学习课程关联
    deleted = client.delete(f"/me/schedule/tables/{imported_table_id}")
    assert deleted.status_code == 204
    names = [
        item["name"] for item in app.state.user_course_store.list_for_user("user-id")
    ]
    assert "数据结构" not in names

    # 剩两张，逐个删到最后一张时拒绝
    assert client.delete(f"/me/schedule/tables/{new_id}").status_code == 204
    assert client.delete(f"/me/schedule/tables/{default_id}").status_code == 409


def test_schedule_import_prefers_docir_when_mm_is_enabled(tmp_path, monkeypatch):
    """验证 `schedule_import_prefers_docir_when_mm_is_enabled` 场景。"""
    app = _app(tmp_path, monkeypatch)
    app.state.mm_sessions = object()

    async def _docir(**kwargs):
        """处理 `_docir` 相关逻辑。"""
        assert kwargs["filename"] == "schedule.xlsx"
        assert kwargs["data"] == b"xlsx"
        return ExtractedScheduleDocument(
            text="周一第1-2节 数据结构",
            pipeline="docir",
            docir_document_id="docir-schedule",
            docir_validation_status="passed",
            docir_element_count=8,
            docir_page_count=1,
        )

    monkeypatch.setattr(schedule, "extract_schedule_document_via_docir", _docir)
    response = TestClient(app).post(
        "/me/schedule/import",
        files={
            "file": (
                "schedule.xlsx",
                b"xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["document"] == {
        "pipeline": "docir",
        "document_id": "docir-schedule",
        "validation_status": "passed",
        "element_count": 8,
        "page_count": 1,
    }
