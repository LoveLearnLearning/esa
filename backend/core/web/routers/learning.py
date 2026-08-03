from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.agent.tools.mastery_tools import (
    get_mastery_report,
    recommend_practice,
    set_current_total_weeks,
)
from backend.agent.tools.memory_tools import set_current_user
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session

router = APIRouter(prefix="/me/learning", tags=["learning"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


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
