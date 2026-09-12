# backend/tests/test_teaching_workflow.py

"""验证 `teaching_workflow` 相关行为与回归场景。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agent.learning.pedagogy_router import PedagogyRouter
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.memory_models import ProfileQuery
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.services.auth_service import AuthService
from backend.core.services.teaching_analysis_service import TeachingAnalysisService
from backend.core.stores.profile_store import ProfileStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.teaching_store import TeachingStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.web.webAPI import create_app


def _app(tmp_path, monkeypatch):
    """处理 `_app` 相关逻辑。"""
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
    app.state.profile_store = ProfileStore(database)
    app.state.teaching_analysis_service = TeachingAnalysisService(app.state.teaching_store)
    app.state.auth = AuthService(app.state.user_store, app.state.session_store)

    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    kg.add_point("binary_search", "二分查找", "数据结构", 1.0, "algorithm")
    kg.add_point("链表", "链表", "数据结构", 0.08)
    app.state.knowledge_graph_store = kg
    app.state.learning_evidence_store = LearningEvidenceStore(tmp_path / "evidence.db")
    app.state.mastery_store = MasteryStore(tmp_path / "mastery.db")
    app.state.profile_builder = ProfileBuilder(
        user_store=app.state.user_store,
        mastery_store=app.state.mastery_store,
        kg_store=app.state.knowledge_graph_store,
        profile_store=app.state.profile_store,
        evidence_store=app.state.learning_evidence_store,
    )
    # 与 webAPI.create_app 保持一致：学习状态唯一写入路径 + 画像缓存失效回调。
    app.state.learning_state_service = LearningStateService(
        kg_store=app.state.knowledge_graph_store,
        mastery_store=app.state.mastery_store,
        evidence_store=app.state.learning_evidence_store,
    )
    app.state.learning_state_service.register_profile_invalidator(
        app.state.profile_builder.invalidate_by_username
    )
    return app


def _identity(client, username, role):
    """处理 `_identity` 相关逻辑。"""
    user = client.app.state.auth.register(username, "correct-password", role)
    assert user is not None
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert login.status_code == 200
    return user, {"Authorization": f"Bearer {login.json()['session_id']}"}


def test_teacher_student_homework_vertical_slice(tmp_path, monkeypatch):
    """验证 `teacher_student_homework_vertical_slice` 场景。"""
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

    duplicate_review = client.post(
        f"/api/teaching/submissions/{submission_id}/review",
        headers=teacher_headers,
        json={"reviews": [
            {"answer_id": answer["answer_id"], "score": 8},
            {"answer_id": answer["answer_id"], "score": 9},
        ]},
    )
    assert duplicate_review.status_code == 422

    reviewed = client.post(
        f"/api/teaching/submissions/{submission_id}/review",
        headers=teacher_headers,
        json={"reviews": [{
            "answer_id": answer["answer_id"],
            "score": 9,
            "feedback": "结论正确，请补充搜索区间规模的递推关系。",
            "kp_id": "二分查找",
        }]},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["total_score"] == 9
    assert reviewed.json()["answers"][0]["final_kp_id"] == "binary_search"
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


def test_published_homework_feedback_refreshes_cached_student_profile(
    tmp_path, monkeypatch
):
    """教师发布正式反馈后，下一轮画像立即读取新的链表掌握度。"""
    client = TestClient(_app(tmp_path, monkeypatch))
    _, teacher_headers = _identity(client, "teacher", "teacher")
    student, student_headers = _identity(client, "student", "student")

    classroom = client.post(
        "/api/teaching/classes",
        headers=teacher_headers,
        json={"name": "数据结构 1 班", "canonical_course": "数据结构"},
    ).json()
    invitation = client.post(
        f"/api/teaching/classes/{classroom['class_id']}/invitations",
        headers=teacher_headers,
        json={"username": "student"},
    ).json()
    assert client.post(
        f"/api/student/invitations/{invitation['membership_id']}/respond",
        headers=student_headers,
        json={"accept": True},
    ).status_code == 200

    assignment = client.post(
        f"/api/teaching/classes/{classroom['class_id']}/assignments",
        headers=teacher_headers,
        json={
            "title": "链表诊断",
            "questions": [
                {
                    "question_type": "short_answer",
                    "prompt": "链表结点包含什么？",
                    "max_points": 10,
                    "reference_answer": "数据域和指针域",
                    "kp_id": "链表",
                },
                {
                    "question_type": "short_answer",
                    "prompt": "单链表如何访问第 k 个结点？",
                    "max_points": 10,
                    "reference_answer": "从头结点沿指针顺序遍历",
                    "kp_id": "链表",
                },
            ],
        },
    ).json()
    assignment_id = assignment["assignment_id"]
    assert client.post(
        f"/api/teaching/assignments/{assignment_id}/publish",
        headers=teacher_headers,
    ).status_code == 200

    submitted = client.post(
        f"/api/student/assignments/{assignment_id}/submissions",
        headers=student_headers,
        json={
            "answers": [
                {"question_id": item["question_id"], "answer_text": "不知道"}
                for item in assignment["questions"]
            ]
        },
    ).json()
    submission_id = submitted["submission_id"]
    analyzed = client.post(
        f"/api/teaching/submissions/{submission_id}/analyze",
        headers=teacher_headers,
    ).json()

    query = ProfileQuery(
        user_id=student.id,
        username=student.username,
        current_message="讲讲链表",
        resolved_kp_ids=["链表"],
    )
    before = client.app.state.profile_builder.build(query)
    before_state = before.relevant_learning_state[0].value
    assert before_state["mastery"]["has_record"] is False
    assert before_state["mastery"]["status"] == "unseen"

    reviewed = client.post(
        f"/api/teaching/submissions/{submission_id}/review",
        headers=teacher_headers,
        json={
            "reviews": [
                {
                    "answer_id": answer["answer_id"],
                    "score": 0,
                    "feedback": "需要重新学习链表基础。",
                    "kp_id": "链表",
                }
                for answer in analyzed["answers"]
            ]
        },
    )
    assert reviewed.status_code == 200
    published = client.post(
        f"/api/teaching/submissions/{submission_id}/publish-feedback",
        headers=teacher_headers,
    )
    assert published.status_code == 200

    after = client.app.state.profile_builder.build(query)
    after_state = after.relevant_learning_state[0].value
    assert after_state["mastery"]["has_record"] is True
    assert after_state["mastery"]["level"] < 50
    assert after_state["mastery"]["practice_count"] == 2
    assert after_state["evidence"]["count"] == 2
    assert PedagogyRouter.route(
        "讲讲链表", profile=after
    ).teaching_depth == "foundation"
