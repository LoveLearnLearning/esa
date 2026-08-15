# backend/core/web/routers/student_teaching.py

"""提供 `student_teaching` 相关功能。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.teaching_store import TeachingStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.teaching_schemas import InvitationResponseRequest, SubmissionCreateRequest

router = APIRouter(prefix="/student", tags=["student teaching"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]

_AI_REVIEW_FIELDS = (
    "ai_score",
    "ai_error_type",
    "ai_feedback",
    "ai_confidence",
    "ai_kp_id",
)
_FINAL_REVIEW_FIELDS = (
    "final_score",
    "final_error_type",
    "final_feedback",
    "final_kp_id",
)


def _context(request: Request, session: SessionPrincipal) -> tuple[UserRecord, TeachingStore]:
    """处理 `_context` 相关逻辑。"""
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None or user.account_role != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅学生可访问学生作业中心")
    return user, request.app.state.teaching_store


def _student_assignment(item: dict) -> dict:
    """处理 `_student_assignment` 相关逻辑。"""
    result = {**item, "questions": [dict(question) for question in item["questions"]]}
    for question in result["questions"]:
        question.pop("reference_answer", None)
        question.pop("rubric", None)
    return result


def _student_submission(item: dict) -> dict:
    """处理 `_student_submission` 相关逻辑。"""
    result = {**item, "answers": [dict(answer) for answer in item["answers"]]}
    published = result["feedback_status"] == "published"
    for answer in result["answers"]:
        answer.pop("reference_answer", None)
        answer.pop("rubric", None)
        for key in _AI_REVIEW_FIELDS:
            answer.pop(key, None)
        if not published:
            for key in _FINAL_REVIEW_FIELDS:
                answer.pop(key, None)
    if not published:
        result["total_score"] = None
    return result


def _student_assignment_summary(item: dict) -> dict:
    """处理 `_student_assignment_summary` 相关逻辑。"""
    result = dict(item)
    if result.get("feedback_status") != "published":
        result["total_score"] = None
    return result


@router.get("/classes")
def classes(request: Request, session: CurrentSession) -> list[dict]:
    """处理 `classes` 相关逻辑。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    user, store = _context(request, session)
    return store.list_student_classes(user.id)


@router.post("/invitations/{membership_id}/respond")
def respond_invitation(
    membership_id: str,
    body: InvitationResponseRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """处理 `respond_invitation` 相关逻辑。

    Args:
        membership_id: str => membership ID。
        body: InvitationResponseRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user, store = _context(request, session)
    result = store.respond_membership(
        membership_id=membership_id, student_id=user.id, accept=body.accept
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "待处理邀请不存在")
    return result


@router.get("/assignments")
def assignments(request: Request, session: CurrentSession) -> list[dict]:
    """处理 `assignments` 相关逻辑。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    user, store = _context(request, session)
    return [
        _student_assignment_summary(item)
        for item in store.list_student_assignments(user.id)
    ]


@router.get("/assignments/{assignment_id}")
def assignment_detail(
    assignment_id: str, request: Request, session: CurrentSession
) -> dict:
    """处理 `assignment_detail` 相关逻辑。

    Args:
        assignment_id: str => 作业 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user, store = _context(request, session)
    item = store.get_assignment(assignment_id)
    if item is None or item["status"] not in {"published", "closed", "archived"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    membership = store.get_membership_for_student(class_id=item["class_id"], student_id=user.id)
    historical = store.get_latest_submission_for_student(
        assignment_id=assignment_id, student_id=user.id
    )
    can_read_history = (
        membership is not None
        and membership["status"] in {"left", "removed"}
        and historical is not None
        and historical["feedback_status"] == "published"
    )
    if membership is None or (membership["status"] != "active" and not can_read_history):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    return _student_assignment(item)


@router.post("/assignments/{assignment_id}/submissions", status_code=status.HTTP_201_CREATED)
def submit(
    assignment_id: str,
    body: SubmissionCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """处理 `submit` 相关逻辑。

    Args:
        assignment_id: str => 作业 ID。
        body: SubmissionCreateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user, store = _context(request, session)
    assignment = store.get_assignment(assignment_id)
    if assignment is None or assignment["status"] != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "开放作业不存在")
    membership = store.get_membership_for_student(
        class_id=assignment["class_id"], student_id=user.id
    )
    if membership is None or membership["status"] != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "开放作业不存在")
    question_ids = {item["question_id"] for item in assignment["questions"]}
    answers = [item.model_dump() for item in body.answers]
    if {item["question_id"] for item in answers} != question_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "必须提交全部题目")
    result = store.submit(assignment_id=assignment_id, student_id=user.id, answers=answers)
    return _student_submission(result)


@router.get("/submissions/{submission_id}")
def submission_detail(
    submission_id: str, request: Request, session: CurrentSession
) -> dict:
    """处理 `submission_detail` 相关逻辑。

    Args:
        submission_id: str => submission ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user, store = _context(request, session)
    item = store.get_submission(submission_id)
    if item is None or item["student_id"] != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交不存在")
    membership = store.get_membership_for_student(
        class_id=item["class_id"], student_id=user.id
    )
    can_read_history = (
        membership is not None
        and membership["status"] in {"left", "removed"}
        and item["feedback_status"] == "published"
    )
    if membership is None or (membership["status"] != "active" and not can_read_history):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交不存在")
    return _student_submission(item)
