from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.agent.learning.knowledge_map_service import KnowledgeMapService
from backend.agent.tools.learning_tools import evidence_store
from backend.agent.tools.mastery_tools import (
    get_mastery_report,
    kg_store,
    mastery_store,
    recommend_practice,
    set_current_total_weeks,
)
from backend.agent.tools.memory_tools import set_current_user
from backend.core.stores.user_store import UserStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session

router = APIRouter(prefix="/me/learning", tags=["learning"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
knowledge_map_service = KnowledgeMapService(
    kg_store=kg_store,
    mastery_store=mastery_store,
    evidence_store=evidence_store,
)


class UserCourseInput(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    source: str = Field(default="manual", pattern="^(manual|timetable)$")


class AddUserCoursesRequest(BaseModel):
    courses: list[UserCourseInput] = Field(min_length=1, max_length=100)


class BindUserCourseRequest(BaseModel):
    canonical_course: str = Field(min_length=1, max_length=64)


def _prepare_user(request: Request, session: SessionPrincipal) -> UserRecord:
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    set_current_user(user.username)
    set_current_total_weeks(user.total_weeks)
    return user


@router.get("/mastery")
def mastery_report(
    request: Request,
    session: CurrentSession,
    course: str = Query(default="", max_length=64),
) -> dict:
    _prepare_user(request, session)
    return get_mastery_report(course)


@router.get("/recommendations")
def practice_recommendations(
    request: Request,
    session: CurrentSession,
    course: str = Query(min_length=1, max_length=64),
    weeks_to_exam: int = Query(default=4, ge=0, le=52),
) -> dict:
    _prepare_user(request, session)
    result = recommend_practice(course, weeks_to_exam)
    if result.get("count", 0) == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, result.get("note", "暂无推荐"))
    return result


@router.get("/courses")
def learning_courses(request: Request, session: CurrentSession) -> dict:
    user = _prepare_user(request, session)
    store: UserCourseStore = request.app.state.user_course_store
    associations = store.list_for_user(user.id)
    for item in associations:
        if item["canonical_course"]:
            continue
        resolved = kg_store.resolve_course_name(item["name"])
        if resolved is None:
            continue
        store.upsert(
            user_id=user.id,
            name=item["name"],
            canonical_course=resolved,
            source=item["source"],
        )
        item["canonical_course"] = resolved
    unique_associations = []
    seen_courses: set[str] = set()
    for item in associations:
        identity = item["canonical_course"] or (
            "unmatched:" + "".join(item["name"].split()).casefold()
        )
        if identity in seen_courses:
            continue
        seen_courses.add(identity)
        unique_associations.append(item)
    associations = unique_associations
    supported_names = [
        item["canonical_course"]
        for item in associations
        if item["canonical_course"]
    ]
    summaries = {
        item["name"]: item
        for item in knowledge_map_service.get_courses(
            user_name=user.username,
            course_names=supported_names,
        )["courses"]
    }
    courses = []
    for item in associations:
        canonical = item["canonical_course"]
        summary = summaries.get(canonical, {})
        courses.append(
            {
                "name": item["name"],
                "canonical_course": canonical,
                "supported": canonical is not None,
                "source": item["source"],
                "total_points": summary.get("total_points", 0),
                "evaluated_points": summary.get("evaluated_points", 0),
                "weak_points": summary.get("weak_points", 0),
                "review_points": summary.get("review_points", 0),
                "average_mastery": summary.get("average_mastery"),
            }
        )
    return {"courses": courses}


@router.get("/course-catalog")
def learning_course_catalog(
    request: Request,
    session: CurrentSession,
    query: str = Query(default="", max_length=64),
) -> dict:
    user = _prepare_user(request, session)
    store: UserCourseStore = request.app.state.user_course_store
    added = {
        item["canonical_course"]
        for item in store.list_for_user(user.id)
        if item["canonical_course"]
    }
    needle = "".join(query.split()).casefold()
    alias_matches = {
        item["course"]
        for item in kg_store.list_course_aliases()
        if needle and needle in item["alias"]
    }
    courses = [
        {"name": name, "added": name in added}
        for name in kg_store.list_courses()
        if not needle
        or needle in "".join(name.split()).casefold()
        or name in alias_matches
    ]
    return {"courses": courses}


@router.post("/courses", status_code=status.HTTP_201_CREATED)
def add_learning_courses(
    payload: AddUserCoursesRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    user = _prepare_user(request, session)
    store: UserCourseStore = request.app.state.user_course_store
    added = []
    for item in payload.courses:
        name = item.name.strip()
        canonical = kg_store.resolve_course_name(name)
        if item.source == "manual" and canonical is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"“{name}”不是可用的课程知识地图",
            )
        current = store.list_for_user(user.id)
        if canonical and any(
            existing["canonical_course"] == canonical for existing in current
        ):
            added.append(canonical)
            continue
        store.upsert(
            user_id=user.id,
            name=canonical or name,
            canonical_course=canonical,
            source=item.source,
        )
        added.append(canonical or name)
    return {"added": added}


@router.patch("/courses/{course_name}")
def bind_learning_course(
    course_name: str,
    payload: BindUserCourseRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    user = _prepare_user(request, session)
    store: UserCourseStore = request.app.state.user_course_store
    association = next(
        (
            item
            for item in store.list_for_user(user.id)
            if item["name"] == course_name
        ),
        None,
    )
    if association is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程不在我的学习空间中")
    canonical = kg_store.resolve_course_name(payload.canonical_course)
    if canonical is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "目标课程不是可用的 canonical 课程",
        )
    store.upsert(
        user_id=user.id,
        name=association["name"],
        canonical_course=canonical,
        source=association["source"],
    )
    return {
        "name": association["name"],
        "canonical_course": canonical,
        "supported": True,
    }


@router.delete("/courses/{course_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_learning_course(
    course_name: str, request: Request, session: CurrentSession
) -> None:
    user = _prepare_user(request, session)
    store: UserCourseStore = request.app.state.user_course_store
    if not store.delete(user_id=user.id, name=course_name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程不在我的学习空间中")


@router.get("/knowledge-map")
def knowledge_map(
    request: Request,
    session: CurrentSession,
    course: str = Query(min_length=1, max_length=64),
) -> dict:
    user = _prepare_user(request, session)
    result = knowledge_map_service.get_course_map(
        user_name=user.username,
        course=course,
    )
    if not result["nodes"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程不存在或没有知识点")
    return result


@router.get("/knowledge-points/{kp_id}")
def knowledge_point_detail(
    kp_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    user = _prepare_user(request, session)
    result = knowledge_map_service.get_point_detail(
        user_name=user.username,
        kp_id=kp_id,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识点不存在")
    return result


@router.get("/review-queue")
def review_queue(
    request: Request,
    session: CurrentSession,
    course: str = Query(default="", max_length=64),
) -> dict:
    user = _prepare_user(request, session)
    return knowledge_map_service.get_review_queue(
        user_name=user.username,
        course=course.strip() or None,
    )
