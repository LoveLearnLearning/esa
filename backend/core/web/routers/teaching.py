from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.services.teaching_analysis_service import TeachingAnalysisService
from backend.core.stores.teaching_store import TeachingStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.teaching_schemas import (
    AssignmentCreateRequest,
    ClassCreateRequest,
    InviteStudentRequest,
    SubmissionReviewRequest,
)

router = APIRouter(prefix="/teaching", tags=["teaching"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _context(request: Request, session: SessionPrincipal) -> tuple[UserRecord, TeachingStore]:
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None or user.account_role != "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅教师可访问教学工作台")
    return user, request.app.state.teaching_store


def _owned_class(store: TeachingStore, class_id: str, teacher_id: str) -> dict:
    item = store.get_class(class_id)
    if item is None or item["owner_teacher_id"] != teacher_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "班级不存在")
    return item


def _owned_assignment(store: TeachingStore, assignment_id: str, teacher_id: str) -> dict:
    item = store.get_assignment(assignment_id)
    if item is None or item["owner_teacher_id"] != teacher_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    return item


def _owned_submission(store: TeachingStore, submission_id: str, teacher_id: str) -> dict:
    item = store.get_submission(submission_id)
    if item is None or item["owner_teacher_id"] != teacher_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交不存在")
    return item


@router.get("/overview")
def overview(request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    return {**store.dashboard(user.id), "classes": store.list_teacher_classes(user.id)}


@router.get("/classes")
def classes(request: Request, session: CurrentSession) -> list[dict]:
    user, store = _context(request, session)
    return store.list_teacher_classes(user.id)


@router.post("/classes", status_code=status.HTTP_201_CREATED)
def create_class(body: ClassCreateRequest, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    course = request.app.state.knowledge_graph_store.resolve_course_name(body.canonical_course)
    if course is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "课程知识图谱不存在")
    try:
        return store.create_class(
            owner_id=user.id,
            name=body.name.strip(),
            course=course,
            term=body.term.strip(),
            description=body.description.strip(),
        )
    except Exception as error:
        if "UNIQUE constraint" in str(error):
            raise HTTPException(status.HTTP_409_CONFLICT, "已有同名活动班级") from error
        raise


@router.get("/classes/{class_id}")
def class_detail(class_id: str, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    item = _owned_class(store, class_id, user.id)
    return {
        **item,
        "members": store.list_members(class_id),
        "assignments": store.list_class_assignments(class_id),
    }


@router.post("/classes/{class_id}/invitations", status_code=status.HTTP_201_CREATED)
def invite(
    class_id: str, body: InviteStudentRequest, request: Request, session: CurrentSession
) -> dict:
    user, store = _context(request, session)
    classroom = _owned_class(store, class_id, user.id)
    if classroom["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "归档班级不能邀请学生")
    student = request.app.state.user_store.get_by_username(body.username.strip())
    if student is None or student.account_role != "student":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学生账号不存在")
    return store.invite_student(class_id=class_id, teacher_id=user.id, student_id=student.id)


@router.delete("/classes/{class_id}/members/{student_id}", status_code=204)
def remove_member(
    class_id: str, student_id: str, request: Request, session: CurrentSession
) -> None:
    user, store = _context(request, session)
    _owned_class(store, class_id, user.id)
    if not store.remove_member(class_id=class_id, student_id=student_id, teacher_id=user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "班级成员不存在")


@router.post("/classes/{class_id}/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(
    class_id: str, body: AssignmentCreateRequest, request: Request, session: CurrentSession
) -> dict:
    user, store = _context(request, session)
    classroom = _owned_class(store, class_id, user.id)
    if classroom["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "归档班级不能创建作业")
    questions = []
    for question in body.questions:
        payload = question.model_dump()
        if payload["kp_id"]:
            resolved = request.app.state.knowledge_graph_store.resolve_kp_id(payload["kp_id"])
            if resolved is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "知识点不存在")
            point = request.app.state.knowledge_graph_store.get_point(resolved)
            if point is None or point["course"] != classroom["canonical_course"]:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "知识点不属于班级课程")
            payload["kp_id"] = resolved
        questions.append(payload)
    return store.create_assignment(
        class_id=class_id,
        title=body.title.strip(),
        instructions=body.instructions.strip(),
        due_at=body.due_at.isoformat() if body.due_at else None,
        questions=questions,
        teacher_id=user.id,
    )


@router.post("/assignments/{assignment_id}/publish")
def publish_assignment(assignment_id: str, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    _owned_assignment(store, assignment_id, user.id)
    if not store.publish_assignment(assignment_id=assignment_id, teacher_id=user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿作业可以发布")
    return store.get_assignment(assignment_id) or {}


@router.get("/assignments/{assignment_id}/submissions")
def submissions(assignment_id: str, request: Request, session: CurrentSession) -> list[dict]:
    user, store = _context(request, session)
    _owned_assignment(store, assignment_id, user.id)
    return store.list_submissions(assignment_id)


@router.get("/submissions/{submission_id}")
def submission_detail(submission_id: str, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    return _owned_submission(store, submission_id, user.id)


@router.post("/submissions/{submission_id}/analyze")
async def analyze_submission(submission_id: str, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    _owned_submission(store, submission_id, user.id)
    service = getattr(request.app.state, "teaching_analysis_service", None)
    if not isinstance(service, TeachingAnalysisService):
        service = TeachingAnalysisService(store)
    return await service.analyze_submission(submission_id, user.id)


@router.post("/assignments/{assignment_id}/analyze")
async def analyze_assignment(
    assignment_id: str, request: Request, session: CurrentSession
) -> dict:
    user, store = _context(request, session)
    _owned_assignment(store, assignment_id, user.id)
    service = getattr(request.app.state, "teaching_analysis_service", None)
    if not isinstance(service, TeachingAnalysisService):
        service = TeachingAnalysisService(store)
    submissions = store.list_submissions(assignment_id)
    completed = 0
    failed = 0
    for item in submissions:
        try:
            await service.analyze_submission(item["submission_id"], user.id)
            completed += 1
        except Exception:
            failed += 1
    return {
        "assignment_id": assignment_id,
        "total": len(submissions),
        "completed": completed,
        "failed": failed,
        "status": "completed" if failed == 0 else "partial",
    }


@router.post("/submissions/{submission_id}/review")
def review_submission(
    submission_id: str,
    body: SubmissionReviewRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    user, store = _context(request, session)
    submission = _owned_submission(store, submission_id, user.id)
    answers = {item["answer_id"]: item for item in submission["answers"]}
    if set(answers) != {item.answer_id for item in body.reviews}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "必须复核全部题目")
    for review in body.reviews:
        answer = answers[review.answer_id]
        if review.score > float(answer["max_points"]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "得分不能超过题目满分")
        if review.kp_id and request.app.state.knowledge_graph_store.resolve_kp_id(review.kp_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "知识点不存在")
    return store.review_submission(
        submission_id=submission_id,
        reviews=[item.model_dump() for item in body.reviews],
        teacher_id=user.id,
    )


@router.post("/submissions/{submission_id}/publish-feedback")
def publish_feedback(submission_id: str, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    submission = _owned_submission(store, submission_id, user.id)
    published = store.mark_feedback_published(submission_id=submission_id, teacher_id=user.id)
    student = request.app.state.user_store.get_by_id(submission["student_id"])
    if student is not None:
        for answer in published["answers"]:
            kp_id = answer.get("final_kp_id") or answer.get("kp_id")
            if not kp_id or store.has_evidence(answer["answer_id"]):
                continue
            ratio = float(answer["final_score"]) / max(0.001, float(answer["max_points"]))
            correct = ratio >= 0.6
            evidence = request.app.state.learning_evidence_store.record(
                user_name=student.username,
                kp_id=kp_id,
                activity_type="homework",
                correct=correct,
                evidence_reliability=0.95,
                independent=True,
                error_type=None if correct else (answer.get("final_error_type") or "unknown"),
                misconception=None if correct else answer.get("final_feedback"),
            )
            request.app.state.mastery_store.apply_evidence(
                user_name=student.username,
                kp_id=kp_id,
                activity_type="homework",
                correct=correct,
                evidence_reliability=0.95,
                independent=True,
            )
            store.mark_evidence_written(answer["answer_id"], evidence["id"])
    return published


@router.get("/classes/{class_id}/dashboard")
def class_dashboard(class_id: str, request: Request, session: CurrentSession) -> dict:
    user, store = _context(request, session)
    classroom = _owned_class(store, class_id, user.id)
    members = [item for item in store.list_members(class_id) if item["status"] == "active"]
    rows = store.class_learning_rows(class_id)
    by_kp: dict[str, list[dict]] = defaultdict(list)
    by_student: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("kp_id"):
            by_kp[row["kp_id"]].append(row)
        by_student[row["student_id"]].append(row)
    knowledge = []
    for kp_id, evidence in by_kp.items():
        point = request.app.state.knowledge_graph_store.get_point(kp_id) or {"name": kp_id}
        ratios = [float(item["final_score"]) / max(.001, float(item["max_points"])) for item in evidence]
        knowledge.append({
            "kp_id": kp_id,
            "name": point["name"],
            "average_score_ratio": round(sum(ratios) / len(ratios), 3),
            "weak_student_count": len({item["student_id"] for item, ratio in zip(evidence, ratios) if ratio < .6}),
            "evaluated_student_count": len({item["student_id"] for item in evidence}),
            "student_count": len(members),
        })
    knowledge.sort(key=lambda item: item["average_score_ratio"])
    alerts = []
    for member in members:
        evidence = by_student.get(member["student_id"], [])
        weak = sum(float(item["final_score"]) / max(.001, float(item["max_points"])) < .6 for item in evidence)
        if weak >= 2:
            alerts.append({
                "student_id": member["student_id"],
                "student_username": member["student_username"],
                "type": "continuous_weakness",
                "level": "important",
                "evidence_count": weak,
                "reason": f"{weak} 道已发布题目表现薄弱",
            })
    knowledge_by_id = {item["kp_id"]: item for item in knowledge}
    root_causes_by_id: dict[str, dict] = {}
    for item in knowledge:
        if item["average_score_ratio"] >= 0.6:
            continue
        for prerequisite in request.app.state.knowledge_graph_store.get_prerequisites(item["kp_id"], max_depth=3):
            if prerequisite["depth"] == 0:
                continue
            prerequisite_stats = knowledge_by_id.get(prerequisite["kp_id"])
            candidate = root_causes_by_id.setdefault(
                prerequisite["kp_id"],
                {
                    "kp_id": prerequisite["kp_id"],
                    "name": prerequisite["name"],
                    "affected_knowledge_points": [],
                    "max_depth": prerequisite["depth"],
                    "evidence_status": "needs_diagnosis",
                    "average_score_ratio": None,
                },
            )
            candidate["affected_knowledge_points"].append(item["kp_id"])
            candidate["max_depth"] = min(
                candidate["max_depth"], prerequisite["depth"]
            )
            if prerequisite_stats is not None:
                candidate["average_score_ratio"] = prerequisite_stats[
                    "average_score_ratio"
                ]
                candidate["evidence_status"] = (
                    "confirmed_weak"
                    if prerequisite_stats["average_score_ratio"] < 0.6
                    else "not_weak"
                )
    root_causes = sorted(
        root_causes_by_id.values(),
        key=lambda item: (
            0 if item["evidence_status"] == "confirmed_weak" else 1,
            -len(item["affected_knowledge_points"]),
            item["max_depth"],
        ),
    )[:5]
    return {
        "class": classroom,
        "student_count": len(members),
        "published_evidence_count": len(rows),
        "knowledge_points": knowledge,
        "root_causes": root_causes,
        "alerts": alerts,
    }


@router.get("/classes/{class_id}/students/{student_id}")
def student_detail(
    class_id: str, student_id: str, request: Request, session: CurrentSession
) -> dict:
    user, store = _context(request, session)
    _owned_class(store, class_id, user.id)
    membership = store.get_membership_for_student(class_id=class_id, student_id=student_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学生不属于该班级")
    store.audit(
        actor_id=user.id,
        action="student_detail.viewed",
        resource_type="membership",
        resource_id=membership["membership_id"],
    )
    return store.student_class_summary(class_id=class_id, student_id=student_id)
