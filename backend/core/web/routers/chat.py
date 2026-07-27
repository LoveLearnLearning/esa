# backend/core/web/routers/chat.py


from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.agent.agent import Agent
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import RenameRequest, SendMessageRequest

router = APIRouter(prefix="/conversations", tags=["chat"])


def _load_owned(
    request: Request,
    conversation_id: str,
    session: SessionPrincipal,
) -> dict:
    """辅助函数：取出 db 中的对话 并校验对话的归属性
    不存在或不属于当前用户的对话返回 404

    Args:
        request: Request            => 请求对象
        conversation_id: str        => 对话 id
        session: SessionPrincipal   => 用户登陆信息

    Returns:
        dict                        => 对话信息
    """

    chat_store: ChatStore = request.app.state.chat_store
    conversation: dict | None = chat_store.get_conversation(conversation_id)
    if conversation is None or conversation["user_id"] != session.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")

    return conversation


@router.get("")
def list_conversations(
    request: Request,
    session: SessionPrincipal = Depends(get_current_session),
) -> list[dict]:
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.list_conversations(session.user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    session: SessionPrincipal = Depends(get_current_session),
) -> dict:
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.create_conversation(session.user_id)


@router.patch("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def rename_conversation(
    conversation_id: str,
    body: RenameRequest,
    request: Request,
    session: SessionPrincipal = Depends(get_current_session),
) -> None:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    chat_store.rename_conversation(conversation_id, body.title)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    request: Request,
    session: SessionPrincipal = Depends(get_current_session),
) -> None:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    chat_store.delete_conversation(conversation_id)


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    request: Request,
    session: SessionPrincipal = Depends(get_current_session),
) -> list[dict]:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.get_history(conversation_id)


@router.post("/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    session: SessionPrincipal = Depends(get_current_session),
) -> list[dict]:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    user_store: UserStore = request.app.state.user_store
    agent: Agent = request.app.state.agent

    user: UserRecord | None = user_store.get_by_id(session.user_id)

    assert user is not None

    history: list[dict] = chat_store.get_model_messages(conversation_id)
    new_messages: list[dict] = agent.run(
        body.content,
        user.username,
        history=history,
    )

    chat_store.append_messages(
        conversation_id,
        new_messages,
    )

    return new_messages
