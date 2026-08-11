from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.agent.tools.memory_tools import core_memory
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import CoreMemoryUpsertRequest

router = APIRouter(prefix="/me/memories", tags=["memories"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
VALID_CATEGORIES = {
    "profile",
    "preference",
    "learning",
    "project",
    "constraint",
    "general",
}


def _user(request: Request, session: SessionPrincipal) -> UserRecord:
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return user


@router.get("")
def list_memories(request: Request, session: CurrentSession) -> list[dict]:
    return core_memory.get_all(_user(request, session).username)


@router.put("", status_code=status.HTTP_201_CREATED)
def upsert_memory(
    body: CoreMemoryUpsertRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"category 非法 合法值: {sorted(VALID_CATEGORIES)}",
        )
    user = _user(request, session)
    saved = core_memory.set(
        user_name=user.username,
        memory_key=body.memory_key,
        content=body.content,
        category=body.category,
    )
    if not saved:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "记忆内容不能为空")
    memory = core_memory.get(user.username, body.memory_key.strip())
    if memory is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "保存记忆失败")
    return memory


@router.delete(
    "/{memory_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_memory(
    memory_key: str,
    request: Request,
    session: CurrentSession,
) -> None:
    if not core_memory.delete(_user(request, session).username, memory_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记忆不存在")
