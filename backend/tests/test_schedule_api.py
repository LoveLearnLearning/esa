from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import ParsedOutput, SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.routers import schedule


class _LLMProvider:
    async def generate(self, messages, tools):
        assert "数据结构" in messages[-1]["content"]
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

    def parse_output(self, raw):
        return ParsedOutput(content=raw)


def _app(tmp_path, monkeypatch):
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
    app.state.agent = SimpleNamespace(llm_provider=_LLMProvider())
    app.include_router(schedule.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="session", user_id=user.id
    )
    monkeypatch.setattr(schedule.kg_store, "resolve_course_name", lambda name: name)
    return app


def test_schedule_crud_and_html_model_import(tmp_path, monkeypatch):
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
