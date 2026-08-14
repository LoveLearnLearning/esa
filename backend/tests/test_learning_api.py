from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.routers import learning


class _UserStore:
    def get_by_id(self, user_id):
        return UserRecord(
            id=user_id,
            username="alice",
            password_hash="hash",
            status="active",
        )


class _KnowledgeMapService:
    def get_courses(self, *, user_name, course_names=None):
        return {"courses": [{"name": "数据结构", "total_points": 2}]}

    def get_course_map(self, *, user_name, course):
        if course == "不存在":
            return {"course": course, "nodes": [], "edges": []}
        return {
            "course": course,
            "nodes": [{"id": "tree", "status": "unseen"}],
            "edges": [{"from": "recursion", "to": "tree"}],
        }

    def get_point_detail(self, *, user_name, kp_id):
        if kp_id == "missing":
            return None
        return {"point": {"id": kp_id}, "state": {"status": "unseen"}}

    def get_review_queue(self, *, user_name, course=None):
        return {"items": [], "course": course}


class _KnowledgeGraph:
    def resolve_course_name(self, name):
        return name

    def list_courses(self):
        return ["数据结构", "高等数学"]

    def list_course_aliases(self):
        return []


class _UserCourseStore:
    def __init__(self):
        self.items = [
            {
                "name": "数据结构",
                "canonical_course": "数据结构",
                "source": "timetable",
            }
        ]

    def list_for_user(self, user_id):
        return list(self.items)

    def upsert(self, *, user_id, name, canonical_course, source):
        for item in self.items:
            if item["name"] == name:
                item.update(
                    canonical_course=canonical_course,
                    source=source,
                )
                return True
        self.items.append(
            {
                "name": name,
                "canonical_course": canonical_course,
                "source": source,
            }
        )
        return True

    def delete(self, *, user_id, name):
        before = len(self.items)
        self.items = [item for item in self.items if item["name"] != name]
        return len(self.items) != before


def _app(monkeypatch):
    app = FastAPI()
    app.state.user_store = _UserStore()
    app.state.user_course_store = _UserCourseStore()
    app.state.knowledge_graph_store = _KnowledgeGraph()
    app.state.knowledge_map_service = _KnowledgeMapService()
    app.include_router(learning.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="session", user_id="user"
    )
    return app


def test_knowledge_map_api_contract(monkeypatch):
    client = TestClient(_app(monkeypatch))
    courses = client.get("/me/learning/courses")
    graph = client.get(
        "/me/learning/knowledge-map", params={"course": "数据结构"}
    )
    detail = client.get("/me/learning/knowledge-points/tree")
    review = client.get(
        "/me/learning/review-queue", params={"course": "数据结构"}
    )
    assert courses.status_code == 200
    assert courses.json()["courses"][0]["supported"] is True
    assert courses.json()["courses"][0]["source"] == "timetable"
    assert graph.json()["nodes"][0]["status"] == "unseen"
    assert graph.json()["edges"][0]["from"] == "recursion"
    assert detail.json()["point"]["id"] == "tree"
    assert review.json()["course"] == "数据结构"


def test_unknown_course_and_point_return_404(monkeypatch):
    client = TestClient(_app(monkeypatch))
    assert client.get(
        "/me/learning/knowledge-map", params={"course": "不存在"}
    ).status_code == 404
    assert client.get(
        "/me/learning/knowledge-points/missing"
    ).status_code == 404


def test_user_courses_can_be_added_and_removed(monkeypatch):
    app = _app(monkeypatch)
    monkeypatch.setattr(app.state.knowledge_graph_store, "resolve_course_name", lambda name: name)
    monkeypatch.setattr(app.state.knowledge_graph_store, "list_courses", lambda: ["数据结构", "高等数学"])
    client = TestClient(app)

    catalog = client.get("/me/learning/course-catalog")
    added = client.post(
        "/me/learning/courses",
        json={"courses": [{"name": "高等数学", "source": "manual"}]},
    )
    removed = client.delete("/me/learning/courses/高等数学")

    assert catalog.status_code == 200
    assert catalog.json()["courses"][0]["added"] is True
    assert added.status_code == 201
    assert added.json()["added"] == ["高等数学"]
    assert removed.status_code == 204


def test_timetable_course_without_kg_is_kept_as_unsupported(monkeypatch):
    app = _app(monkeypatch)
    monkeypatch.setattr(app.state.knowledge_graph_store, "resolve_course_name", lambda _name: None)
    client = TestClient(app)

    response = client.post(
        "/me/learning/courses",
        json={"courses": [{"name": "日语口语训练", "source": "timetable"}]},
    )
    courses = client.get("/me/learning/courses")

    assert response.status_code == 201
    unsupported = next(
        item for item in courses.json()["courses"] if item["name"] == "日语口语训练"
    )
    assert unsupported["supported"] is False
    assert unsupported["canonical_course"] is None


def test_unsupported_course_can_be_bound_to_canonical_course(monkeypatch):
    app = _app(monkeypatch)
    store = app.state.user_course_store
    store.items.append(
        {
            "name": "数字电路技术",
            "canonical_course": None,
            "source": "timetable",
        }
    )
    monkeypatch.setattr(
        app.state.knowledge_graph_store,
        "resolve_course_name",
        lambda _name: "数字逻辑与数字电路",
    )
    client = TestClient(app)

    response = client.patch(
        "/me/learning/courses/数字电路技术",
        json={"canonical_course": "数字逻辑与数字电路"},
    )

    assert response.status_code == 200
    assert response.json()["canonical_course"] == "数字逻辑与数字电路"
    bound = next(item for item in store.items if item["name"] == "数字电路技术")
    assert bound["canonical_course"] == "数字逻辑与数字电路"
