from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.core.services.auth_service import AuthService
from backend.core.services.teaching_analysis_service import TeachingAnalysisService
from backend.core.stores.session_store import SessionStore
from backend.core.stores.teaching_store import TeachingStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.web.routers import teaching
from backend.core.web.webAPI import create_app


def _app(tmp_path, monkeypatch):
    database = tmp_path / "teaching.db"
    app = create_app(
        app_lifespan=None,
        trusted_hosts=("testserver",),
        forwarded_allow_ips=("testclient",),
        enable_legacy_routes=False,
    )
    app.state.user_store = UserStore(database)
    app.state.session_store = SessionStore(database)
    app.state.user_presence_store = UserPresenceStore(database)
    app.state.teaching_store = TeachingStore(database)
    app.state.teaching_analysis_service = TeachingAnalysisService(app.state.teaching_store)
    app.state.auth = AuthService(app.state.user_store, app.state.session_store)

    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    kg.add_point("binary_search", "二分查找", "数据结构", 1.0, "algorithm")
    monkeypatch.setattr(teaching, "kg_store", kg)
    monkeypatch.setattr(teaching, "evidence_store", LearningEvidenceStore(tmp_path / "evidence.db"))
    monkeypatch.setattr(teaching, "mastery_store", MasteryStore(tmp_path / "mastery.db"))
    return app


def _identity(client, username, role):
    user = client.app.state.auth.register(username, "correct-password", role)
    assert user is not None
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert login.status_code == 200
    return user, {"Authorization": f"Bearer {login.json()['session_id']}"}


def test_teacher_student_homework_vertical_slice(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch))
    teacher, teacher_headers = _identity(client, "teacher", "teacher")
    student, student_headers = _identity(client, "student", "student")

    classroom = client.post(
        "/api/teaching/classes",
        headers=teacher_headers,
        json={"name": "数据结构 1 班", "canonical_course": "数据结构", "term": "2026 秋"},
    )
    assert classroom.status_code == 201
    class_id = classroom.json()["class_id"]

    invitation = client.post(
        f"/api/teaching/classes/{class_id}/invitations",
        headers=teacher_headers,
        json={"username": "student"},
    )
    assert invitation.status_code == 201
    membership_id = invitation.json()["membership_id"]
    assert client.get(
        f"/api/teaching/classes/{class_id}", headers=student_headers
    ).status_code == 403

    accepted = client.post(
        f"/api/student/invitations/{membership_id}/respond",
        headers=student_headers,
        json={"accept": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"
    student_classes = client.get("/api/student/classes", headers=student_headers)
    assert student_classes.json()[0]["membership_id"] == membership_id

    assignment = client.post(
        f"/api/teaching/classes/{class_id}/assignments",
        headers=teacher_headers,
        json={
            "title": "二分查找诊断",
            "instructions": "说明循环不变量",
            "questions": [{
                "question_type": "short_answer",
                "prompt": "二分查找为什么是 O(log n)？",
                "max_points": 10,
                "rubric": "每轮搜索区间减半",
                "reference_answer": "每轮搜索区间减半",
                "kp_id": "binary_search",
            }],
        },
    )
    assert assignment.status_code == 201
    assignment_id = assignment.json()["assignment_id"]
    question_id = assignment.json()["questions"][0]["question_id"]
    assert client.post(
        f"/api/teaching/assignments/{assignment_id}/publish",
        headers=teacher_headers,
    ).status_code == 200

    listed = client.get("/api/student/assignments", headers=student_headers)
    assert [item["assignment_id"] for item in listed.json()] == [assignment_id]
    student_assignment = client.get(
        f"/api/student/assignments/{assignment_id}", headers=student_headers
    )
    assert student_assignment.status_code == 200
    assert "reference_answer" not in student_assignment.json()["questions"][0]
    assert "rubric" not in student_assignment.json()["questions"][0]
    submitted = client.post(
        f"/api/student/assignments/{assignment_id}/submissions",
        headers=student_headers,
        json={"answers": [{"question_id": question_id, "answer_text": "每轮搜索区间减半"}]},
    )
    assert submitted.status_code == 201
    assert "reference_answer" not in submitted.json()["answers"][0]
    assert "rubric" not in submitted.json()["answers"][0]
    submission_id = submitted.json()["submission_id"]

    analyzed = client.post(
        f"/api/teaching/submissions/{submission_id}/analyze",
        headers=teacher_headers,
    )
    assert analyzed.status_code == 200
    answer = analyzed.json()["answers"][0]
    assert answer["ai_score"] == 10
    assert answer["ai_confidence"] == 0.35
    batch = client.post(
        f"/api/teaching/assignments/{assignment_id}/analyze",
        headers=teacher_headers,
    )
    assert batch.status_code == 200
    assert batch.json() == {
        "assignment_id": assignment_id,
        "total": 1,
        "completed": 1,
        "failed": 0,
        "status": "completed",
    }

    hidden = client.get(
        f"/api/student/submissions/{submission_id}", headers=student_headers
    )
    assert "ai_score" not in hidden.json()["answers"][0]

    reviewed = client.post(
        f"/api/teaching/submissions/{submission_id}/review",
        headers=teacher_headers,
        json={"reviews": [{
            "answer_id": answer["answer_id"],
            "score": 9,
            "feedback": "结论正确，请补充搜索区间规模的递推关系。",
            "kp_id": "binary_search",
        }]},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["total_score"] == 9
    unpublished_list = client.get("/api/student/assignments", headers=student_headers)
    assert unpublished_list.json()[0]["total_score"] is None
    assert client.post(
        f"/api/teaching/submissions/{submission_id}/publish-feedback",
        headers=teacher_headers,
    ).status_code == 200

    feedback = client.get(
        f"/api/student/submissions/{submission_id}", headers=student_headers
    )
    assert feedback.json()["answers"][0]["final_score"] == 9
    assert "reference_answer" not in feedback.json()["answers"][0]
    assert "rubric" not in feedback.json()["answers"][0]
    assert "ai_score" not in feedback.json()["answers"][0]
    dashboard = client.get(
        f"/api/teaching/classes/{class_id}/dashboard", headers=teacher_headers
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["knowledge_points"][0]["kp_id"] == "binary_search"
    assert dashboard.json()["root_causes"] == []

    other_teacher, other_headers = _identity(client, "other", "teacher")
    assert other_teacher.id != teacher.id
    assert client.get(
        f"/api/teaching/classes/{class_id}", headers=other_headers
    ).status_code == 404
    assert student.id != teacher.id

    assert client.delete(
        f"/api/teaching/classes/{class_id}/members/{student.id}",
        headers=teacher_headers,
    ).status_code == 204
    new_assignment = client.post(
        f"/api/teaching/classes/{class_id}/assignments",
        headers=teacher_headers,
        json={
            "title": "移除后的新作业",
            "questions": [{
                "question_type": "short_answer",
                "prompt": "说明查找前提。",
                "max_points": 5,
                "rubric": "有序数组",
                "reference_answer": "数组必须有序",
                "kp_id": "binary_search",
            }],
        },
    )
    new_assignment_id = new_assignment.json()["assignment_id"]
    new_question_id = new_assignment.json()["questions"][0]["question_id"]
    assert client.post(
        f"/api/teaching/assignments/{new_assignment_id}/publish",
        headers=teacher_headers,
    ).status_code == 200

    historical = client.get("/api/student/assignments", headers=student_headers)
    assert [item["assignment_id"] for item in historical.json()] == [assignment_id]
    assert client.get(
        f"/api/student/assignments/{assignment_id}", headers=student_headers
    ).status_code == 200
    assert client.get(
        f"/api/student/submissions/{submission_id}", headers=student_headers
    ).status_code == 200
    assert client.get(
        f"/api/student/assignments/{new_assignment_id}", headers=student_headers
    ).status_code == 404
    assert client.post(
        f"/api/student/assignments/{new_assignment_id}/submissions",
        headers=student_headers,
        json={"answers": [{"question_id": new_question_id, "answer_text": "有序"}]},
    ).status_code == 404
