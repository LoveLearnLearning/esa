"""Planner persistence regression tests."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.stores.planner_store import PlannerStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.routers.planner import router


def _store(tmp_path):
    database = tmp_path / "planner.db"
    users = UserStore(database)
    for user_id in ("u1", "u2"):
        assert users.create(
            UserRecord(
                id=user_id,
                username=user_id,
                password_hash="hash",
                status="active",
            )
        )
    return PlannerStore(database)


def test_todos_and_goals_are_user_scoped_and_mutable(tmp_path):
    store = _store(tmp_path)

    todo = store.create_todo("u1", "复习线性代数", due_at="2026-09-01T00:00:00Z")
    goal = store.create_goal(
        "u1",
        "完成论文初稿",
        description="先完成方法章节",
        target_at="2026-10-01T00:00:00Z",
        progress=20,
    )

    assert [item["todo_id"] for item in store.list_todos("u1")] == [todo["todo_id"]]
    assert store.list_todos("u2") == []
    assert [item["goal_id"] for item in store.list_goals("u1")] == [goal["goal_id"]]
    assert store.list_goals("u2") == []

    assert store.update_todo(todo["todo_id"], "u1", done=True)
    assert store.get_todo(todo["todo_id"], "u1")["done"] is True
    assert not store.update_todo(todo["todo_id"], "u2", done=True)

    assert store.update_goal(goal["goal_id"], "u1", progress=70)
    assert store.get_goal(goal["goal_id"], "u1")["progress"] == 70
    assert not store.delete_goal(goal["goal_id"], "u2")
    assert store.delete_goal(goal["goal_id"], "u1")


def test_planner_api_uses_authenticated_user_scope(tmp_path):
    store = _store(tmp_path)
    app = FastAPI()
    app.state.planner_store = store
    app.include_router(router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="s1",
        user_id="u1",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    client = TestClient(app)

    created = client.post(
        "/me/planner/todos",
        json={"title": "完成作业", "due_at": "2026-09-01T00:00:00Z"},
    )
    assert created.status_code == 201
    todo_id = created.json()["todo_id"]

    toggled = client.patch(
        f"/me/planner/todos/{todo_id}", json={"done": True}
    )
    assert toggled.status_code == 200
    assert toggled.json()["done"] is True
    assert client.get("/me/planner").json()["todos"][0]["todo_id"] == todo_id
