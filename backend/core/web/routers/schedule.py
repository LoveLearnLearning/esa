# backend/core/web/routers/schedule.py

"""提供 `schedule` 相关功能。"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, model_validator

from backend.core.services.schedule_import_service import (
    extract_schedule_document,
    extract_schedule_document_via_docir,
    extract_schedule_courses,
    prefers_visual_schedule,
    supports_docir_schedule,
)
from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.config import AUXILIARY_MODEL_MAX_OUTPUT_TOKENS
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session

router = APIRouter(prefix="/me/schedule", tags=["schedule"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
COURSE_COLORS = (
    0xFF2563EB,
    0xFF7C3AED,
    0xFF059669,
    0xFFD97706,
    0xFFDC2626,
    0xFF0891B2,
    0xFFDB2777,
)


class ScheduleCoursePayload(BaseModel):
    """封装 `ScheduleCoursePayload` 的状态与行为。"""
    id: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    teacher: str = Field(default="", max_length=80)
    location: str = Field(default="", max_length=80)
    weekday: int = Field(ge=1, le=7)
    start_period: int = Field(ge=1, le=24)
    end_period: int = Field(ge=1, le=24)
    start_week: int = Field(ge=1, le=30)
    end_week: int = Field(ge=1, le=30)
    color_value: int = Field(default=0xFF2563EB, ge=0, le=0xFFFFFFFF)

    @model_validator(mode="after")
    def validate_ranges(self) -> "ScheduleCoursePayload":
        """校验 `ranges` 相关数据。"""
        if self.end_period < self.start_period:
            raise ValueError("结束节次不能小于开始节次")
        if self.end_week < self.start_week:
            raise ValueError("结束周不能小于开始周")
        return self


class ScheduleSettingsPayload(BaseModel):
    """封装 `ScheduleSettingsPayload` 的状态与行为。"""
    morning_period_count: int = Field(ge=0, le=8)
    afternoon_period_count: int = Field(ge=0, le=8)
    evening_period_count: int = Field(ge=0, le=8)
    morning_start_minutes: int = Field(ge=0, le=1439)
    afternoon_start_minutes: int = Field(ge=0, le=1439)
    evening_start_minutes: int = Field(ge=0, le=1439)
    period_duration_minutes: int = Field(ge=20, le=180)
    break_duration_minutes: int = Field(ge=0, le=120)
    term_start_date: str = Field(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_period_count(self) -> "ScheduleSettingsPayload":
        """校验 `period count` 相关数据。"""
        if (
            self.morning_period_count
            + self.afternoon_period_count
            + self.evening_period_count
            == 0
        ):
            raise ValueError("课表至少需要一节课")
        return self


def _user(request: Request, session: SessionPrincipal) -> UserRecord:
    """处理 `_user` 相关逻辑。"""
    store: UserStore = request.app.state.user_store
    user = store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return user


def _sync_learning_course(request: Request, user_id: str, name: str) -> None:
    """同步 `learning course` 相关数据。"""
    store: UserCourseStore = request.app.state.user_course_store
    canonical = request.app.state.knowledge_graph_store.resolve_course_name(name)
    store.upsert(
        user_id=user_id,
        name=name,
        canonical_course=canonical,
        source="timetable",
    )


def _remove_unused_learning_course(
    request: Request, user_id: str, name: str
) -> None:
    """移除 `unused learning course` 相关数据。"""
    schedule_store: ScheduleStore = request.app.state.schedule_store
    if any(course["name"] == name for course in schedule_store.list_courses(user_id)):
        return
    course_store: UserCourseStore = request.app.state.user_course_store
    association = next(
        (
            item
            for item in course_store.list_for_user(user_id)
            if item["name"] == name and item["source"] == "timetable"
        ),
        None,
    )
    if association is not None:
        course_store.delete(user_id=user_id, name=name)


class ScheduleTablePayload(BaseModel):
    """封装 `ScheduleTablePayload` 的状态与行为。"""
    name: str = Field(min_length=1, max_length=40)
    activate: bool = True


@router.get("")
def get_schedule(request: Request, session: CurrentSession) -> dict:
    """获取 `schedule` 相关数据。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    active_table_id = store.ensure_active_table(user.id)
    return {
        "tables": store.list_tables(user.id),
        "active_table_id": active_table_id,
        "courses": store.list_courses(user.id, active_table_id),
        "settings": store.get_settings(user.id),
    }


@router.post("/tables", status_code=status.HTTP_201_CREATED)
def create_schedule_table(
    payload: ScheduleTablePayload, request: Request, session: CurrentSession
) -> dict:
    """创建 `schedule table` 相关数据。

    Args:
        payload: ScheduleTablePayload => 请求载荷。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    store.ensure_active_table(user.id)
    return store.create_table(user.id, payload.name, activate=payload.activate)


@router.patch("/tables/{table_id}")
def rename_schedule_table(
    table_id: str,
    payload: ScheduleTablePayload,
    request: Request,
    session: CurrentSession,
) -> dict:
    """处理 `rename_schedule_table` 相关逻辑。

    Args:
        table_id: str => table ID。
        payload: ScheduleTablePayload => 请求载荷。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    if not store.rename_table(user.id, table_id, payload.name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程表不存在")
    table = store.get_table(user.id, table_id)
    assert table is not None
    return table


@router.post("/tables/{table_id}/activate")
def activate_schedule_table(
    table_id: str, request: Request, session: CurrentSession
) -> dict:
    """处理 `activate_schedule_table` 相关逻辑。

    Args:
        table_id: str => table ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    if not store.activate_table(user.id, table_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程表不存在")
    return {
        "tables": store.list_tables(user.id),
        "active_table_id": table_id,
        "courses": store.list_courses(user.id, table_id),
        "settings": store.get_settings(user.id),
    }


@router.delete(
    "/tables/{table_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_schedule_table(
    table_id: str, request: Request, session: CurrentSession
) -> None:
    """删除 `schedule table` 相关数据。

    Args:
        table_id: str => table ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    if store.get_table(user.id, table_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程表不存在")
    try:
        removed = store.delete_table(user.id, table_id)
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    for name in {course["name"] for course in removed}:
        _remove_unused_learning_course(request, user.id, name)


@router.put("/courses")
def save_schedule_course(
    payload: ScheduleCoursePayload,
    request: Request,
    session: CurrentSession,
) -> dict:
    """保存 `schedule course` 相关数据。

    Args:
        payload: ScheduleCoursePayload => 请求载荷。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    previous = store.get_course(user.id, payload.id) if payload.id else None
    course = store.upsert_course(user.id, payload.model_dump(exclude_none=True))
    _sync_learning_course(request, user.id, course["name"])
    if previous is not None and previous["name"] != course["name"]:
        _remove_unused_learning_course(request, user.id, previous["name"])
    return course


@router.delete(
    "/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_schedule_course(
    course_id: str, request: Request, session: CurrentSession
) -> None:
    """删除 `schedule course` 相关数据。

    Args:
        course_id: str => course ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    course = store.get_course(user.id, course_id)
    if not store.delete_course(user.id, course_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程不存在")
    if course is not None:
        _remove_unused_learning_course(request, user.id, course["name"])


@router.put("/settings")
def save_schedule_settings(
    payload: ScheduleSettingsPayload,
    request: Request,
    session: CurrentSession,
) -> dict:
    """保存 `schedule settings` 相关数据。

    Args:
        payload: ScheduleSettingsPayload => 请求载荷。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    user = _user(request, session)
    store: ScheduleStore = request.app.state.schedule_store
    return store.save_settings(user.id, payload.model_dump())


@router.post("/import")
async def import_schedule(
    request: Request,
    session: CurrentSession,
    file: Annotated[UploadFile, File()],
    target: Annotated[str, Form()] = "current",
    table_name: Annotated[str | None, Form()] = None,
) -> dict:
    """导入 `schedule` 相关数据。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
        file: Annotated[UploadFile, File()] => `file` 参数。
        target: Annotated[str, Form()] => `target` 参数。
        table_name: Annotated[str | None, Form()] => `table_name` 参数。

    Returns:
        dict => 处理结果。
    """
    if target not in {"current", "new"}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "target 必须是 current 或 new"
        )
    user = _user(request, session)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件不能超过 15 MB")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件为空")
    filename = file.filename or "schedule"
    content_type = file.content_type or "application/octet-stream"
    try:
        mm_sessions = getattr(request.app.state, "mm_sessions", None)
        if prefers_visual_schedule(filename, content_type):
            document = await extract_schedule_document(
                filename=filename,
                content_type=content_type,
                data=data,
            )
        elif mm_sessions is not None and supports_docir_schedule(filename):
            document = await extract_schedule_document_via_docir(
                mm_sessions=mm_sessions,
                session_key=f"schedule:{user.id}:{uuid4()}",
                filename=filename,
                data=data,
            )
        else:
            document = await extract_schedule_document(
                filename=filename,
                content_type=content_type,
                data=data,
            )
        store: ScheduleStore = request.app.state.schedule_store
        courses = await extract_schedule_courses(
            llm_client=request.app.state.auxiliary_llm_client,
            document=document,
            total_weeks=user.total_weeks,
            settings=store.get_settings(user.id),
            max_output_tokens=AUXILIARY_MODEL_MAX_OUTPUT_TOKENS,
        )
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            str(error),
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "模型暂时无法解析课表",
        ) from error

    prepared = [
        {**course, "color_value": COURSE_COLORS[index % len(COURSE_COLORS)]}
        for index, course in enumerate(courses)
    ]
    if target == "new":
        # 识别成功后才建新课程表并切换过去，避免留下空表
        name = (table_name or "").strip() or _default_table_name(store, user.id)
        table = store.create_table(user.id, name[:40], activate=True)
        target_table_id = table["id"]
    else:
        target_table_id = store.ensure_active_table(user.id)
    imported, skipped = store.import_courses(user.id, prepared, target_table_id)
    for course in imported:
        _sync_learning_course(request, user.id, course["name"])
    return {
        "courses": imported,
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "tables": store.list_tables(user.id),
        "active_table_id": store.ensure_active_table(user.id),
        "document": document.metadata,
    }


def _default_table_name(store: ScheduleStore, user_id: str) -> str:
    """处理 `_default_table_name` 相关逻辑。"""
    existing = {table["name"] for table in store.list_tables(user_id)}
    base = "导入课表"
    if base not in existing:
        return base
    index = 2
    while f"{base} {index}" in existing:
        index += 1
    return f"{base} {index}"
