from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.paths import KNOWLEDGE_GRAPH_DB_PATH
from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_store import UserStore
from backend.core.timetable.hust import (
    HustAuthenticationError,
    HustChallengeError,
    HustChallengeNotFoundError,
    HustImporter,
    HustUpstreamError,
)
from backend.core.timetable.models import TimetableEntryDraft
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schedule_hust_schemas import (
    HustChallengeCompleteRequest,
    HustChallengeOut,
    HustChallengeStartRequest,
)

router = APIRouter(prefix="/me/schedule/import/hust", tags=["schedule"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
COURSE_COLORS = (
    0xFF2563EB,
    0xFF7C3AED,
    0xFF059669,
    0xFFD97706,
    0xFFDC2626,
    0xFF0891B2,
    0xFFDB2777,
)
kg_store = KnowledgeGraphStore(database_path=KNOWLEDGE_GRAPH_DB_PATH)


def _user(request: Request, session: SessionPrincipal) -> UserRecord:
    store: UserStore = request.app.state.user_store
    user = store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return user


def _clock_minutes(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def _period_for_time(minutes: int, settings: dict, *, is_end: bool) -> int:
    """把教务时间映射到用户当前节次设置，允许几分钟的校方时间差。"""
    duration = settings["period_duration_minutes"]
    break_duration = settings["break_duration_minutes"]
    sessions = (
        (settings["morning_start_minutes"], settings["morning_period_count"]),
        (settings["afternoon_start_minutes"], settings["afternoon_period_count"]),
        (settings["evening_start_minutes"], settings["evening_period_count"]),
    )
    period = 1
    candidates: list[tuple[int, int]] = []
    for session_start, count in sessions:
        for index in range(count):
            start = session_start + index * (duration + break_duration)
            reference = start + duration if is_end else start
            candidates.append((abs(minutes - reference), period))
            period += 1
    if not candidates:
        raise ValueError("课表节次设置为空")
    return min(candidates)[1]


def _collapse_events(entries: list[TimetableEntryDraft], settings: dict) -> list[dict]:
    """将具体日期事件合并为 ScheduleStore 使用的连续周次规则。"""
    grouped: dict[tuple, dict] = {}
    for entry in entries:
        start_period = _period_for_time(
            _clock_minutes(entry.start_time), settings, is_end=False
        )
        end_period = _period_for_time(
            _clock_minutes(entry.end_time), settings, is_end=True
        )
        if end_period < start_period:
            end_period = start_period
        key = (
            entry.course_name,
            entry.teacher,
            entry.location,
            entry.weekday,
            start_period,
            end_period,
        )
        current = grouped.get(key)
        if current is None:
            grouped[key] = {
                "course": {
                    "name": entry.course_name,
                    "teacher": entry.teacher,
                    "location": entry.location,
                    "weekday": entry.weekday,
                    "start_period": start_period,
                    "end_period": end_period,
                },
                "weeks": {entry.week_number},
            }
        else:
            current["weeks"].add(entry.week_number)

    collapsed: list[dict] = []
    for value in grouped.values():
        weeks = sorted(value["weeks"])
        range_start = range_end = weeks[0]
        for week in weeks[1:] + [None]:
            if week is not None and week == range_end + 1:
                range_end = week
                continue
            collapsed.append(
                {
                    **value["course"],
                    "start_week": range_start,
                    "end_week": range_end,
                }
            )
            if week is not None:
                range_start = range_end = week
    return collapsed


def _default_table_name(store: ScheduleStore, user_id: str, preferred: str) -> str:
    existing = {table["name"] for table in store.list_tables(user_id)}
    base = preferred[:40] or "华科教务课表"
    if base not in existing:
        return base
    index = 2
    while f"{base[:36]} {index}" in existing:
        index += 1
    return f"{base[:36]} {index}"


def _sync_learning_courses(request: Request, user_id: str, courses: list[dict]) -> None:
    store: UserCourseStore = request.app.state.user_course_store
    for course in courses:
        name = course["name"]
        store.upsert(
            user_id=user_id,
            name=name,
            canonical_course=kg_store.resolve_course_name(name),
            source="timetable",
        )


@router.post("/challenge", response_model=HustChallengeOut)
async def start_hust_challenge(
    request: Request,
    session: CurrentSession,
    body: HustChallengeStartRequest | None = None,
) -> HustChallengeOut:
    _user(request, session)
    importer: HustImporter = request.app.state.hust_importer
    payload = body or HustChallengeStartRequest()
    try:
        challenge = await importer.start_challenge(
            owner_user_id=session.user_id,
            semester_name=payload.semester_name,
            semester_start=payload.start_date,
            semester_end=payload.end_date,
        )
    except HustChallengeError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except (HustAuthenticationError, HustUpstreamError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return HustChallengeOut(
        challenge_id=challenge.challenge_id,
        captcha_image_base64=challenge.captcha_image_base64,
        captcha_mime_type=challenge.captcha_mime_type,
        expires_at=challenge.expires_at,
        recommended_semester_name=challenge.recommended_semester_name,
        recommended_start_date=challenge.recommended_start_date,
        recommended_end_date=challenge.recommended_end_date,
    )


@router.post("/complete")
async def complete_hust_import(
    body: HustChallengeCompleteRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    user = _user(request, session)
    # 在 SecretStr 已构造后做跨字段校验；Pydantic model validator 的错误会
    # 回显整个原始请求 input，可能连同教务密码一起返回。
    if (body.start_date is None) != (body.end_date is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "start_date 和 end_date 必须同时提供",
        )
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "end_date 不能早于 start_date",
        )
    importer: HustImporter = request.app.state.hust_importer
    store: ScheduleStore = request.app.state.schedule_store
    try:
        fetched = await importer.complete_challenge(
            owner_user_id=session.user_id,
            challenge_id=body.challenge_id,
            username=body.username,
            password=body.password,
            captcha=body.captcha,
            semester_name=body.semester_name,
            semester_start=body.start_date,
            semester_end=body.end_date,
        )
    except HustChallengeNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except HustChallengeError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except HustAuthenticationError as error:
        # 不能返回 401，否则客户端会误判 ESA Bearer 会话已失效。
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except HustUpstreamError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    settings = store.get_settings(user.id)
    prepared = _collapse_events(fetched.parsed.entries, settings)
    if not prepared:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "华科教务没有返回可导入课程",
        )
    if any(course["end_week"] > 30 for course in prepared):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "所选日期范围超过现有课表支持的 30 周，请缩短学期日期范围",
        )
    for index, course in enumerate(prepared):
        course["color_value"] = COURSE_COLORS[index % len(COURSE_COLORS)]
    created_table_id: str | None = None
    if body.target == "new":
        name = (body.table_name or fetched.semester_name).strip()
        table = store.create_table(
            user.id,
            _default_table_name(store, user.id, name),
            activate=True,
        )
        target_table_id = table["id"]
        created_table_id = target_table_id
    else:
        target_table_id = store.ensure_active_table(user.id)
    try:
        imported, conflicts = store.import_courses(user.id, prepared, target_table_id)
    except Exception:
        # 新表只为本次导入创建；若写入失败则撤销空/部分表，避免留下垃圾。
        if created_table_id is not None:
            try:
                store.delete_table(user.id, created_table_id)
            except (ValueError, OSError):
                pass
        raise
    _sync_learning_courses(request, user.id, imported)
    # 现有课表页以 term_start_date 计算当前周；首次导入时采用教务学期日期。
    store.save_settings(
        user.id,
        {**settings, "term_start_date": fetched.start_date.isoformat()},
    )
    if fetched.total_weeks <= 30 and fetched.total_weeks != user.total_weeks:
        request.app.state.user_store.update_profile(
            user.id,
            current_week=min(user.current_week, fetched.total_weeks),
            total_weeks=fetched.total_weeks,
        )
    return {
        "courses": imported,
        "imported_count": len(imported),
        "skipped_count": fetched.parsed.skipped_entries + len(conflicts),
        "warnings": fetched.parsed.warnings,
        "tables": store.list_tables(user.id),
        "active_table_id": store.ensure_active_table(user.id),
        "semester_name": fetched.semester_name,
        "start_date": fetched.start_date.isoformat(),
        "end_date": fetched.end_date.isoformat(),
    }
