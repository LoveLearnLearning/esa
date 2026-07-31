# backend/core/web/routers/chat.py


import asyncio
import sqlite3
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from backend.agent.agent import Agent, build_user_profile_context
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import RenameRequest, SendMessageRequest
from backend.core.web.sse import encode_sse

router = APIRouter(prefix="/conversations", tags=["chat"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


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
    session: CurrentSession,
) -> list[dict]:
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.list_conversations(session.user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    session: CurrentSession,
) -> dict:
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.create_conversation(session.user_id)


@router.patch("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def rename_conversation(
    conversation_id: str,
    body: RenameRequest,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    chat_store.rename_conversation(conversation_id, body.title)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    chat_store.delete_conversation(conversation_id)


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.get_history(conversation_id)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    user_store: UserStore = request.app.state.user_store
    agent: Agent = request.app.state.agent

    user: UserRecord | None = user_store.get_by_id(session.user_id)

    if user is None:
        session_store: SessionStore = request.app.state.session_store
        session_store.revoke(session.session_id)

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在！")

    history: list[dict] = chat_store.get_model_messages(conversation_id)

    user_message: dict = {
        "role": "user",
        "content": body.content,
        "is_visible": True,
    }
    chat_store.append_messages(
        conversation_id,
        [user_message],
    )

    user_profile_context = build_user_profile_context(user)

    new_messages: list[dict] = await agent.run(
        body.content,
        user.username,
        history=history,
        preferred_style=user.preferred_style,
        preferred_tone=user.preferred_tone,
        custom_instruction=user.custom_instruction,
        user_profile_context=user_profile_context,
        total_weeks=user.total_weeks,
    )

    generated_messages: list[dict] = new_messages[1:]

    if generated_messages:
        chat_store.append_messages(
            conversation_id,
            generated_messages,
        )

    return [message for message in new_messages if message.get("is_visible", True)]


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    session: CurrentSession,
) -> StreamingResponse:
    _load_owned(request, conversation_id, session)

    chat_store: ChatStore = request.app.state.chat_store
    user_store: UserStore = request.app.state.user_store
    agent: Agent = request.app.state.agent

    user: UserRecord | None = user_store.get_by_id(session.user_id)

    if user is None:
        session_store: SessionStore = request.app.state.session_store
        session_store.revoke(session.session_id)

        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "用户不存在",
        )

    history: list[dict] = chat_store.get_model_messages(conversation_id)

    user_message: dict = {
        "role": "user",
        "content": body.content,
        "is_visible": True,
    }

    chat_store.append_messages(
        conversation_id,
        [user_message],
    )

    user_profile_context = build_user_profile_context(user)

    async def event_stream() -> AsyncIterator[str]:
        yield encode_sse(
            "start",
            {
                "conversation_id": conversation_id,
            },
        )

        try:
            async for agent_event in agent.run_stream(
                body.content,
                user.username,
                history=history,
                preferred_style=user.preferred_style,
                preferred_tone=user.preferred_tone,
                custom_instruction=user.custom_instruction,
                user_profile_context=user_profile_context,
                total_weeks=user.total_weeks,
            ):
                if agent_event.event == "complete":
                    new_messages = agent_event.data["messages"]

                    generated_messages = new_messages[1:]

                    if generated_messages:
                        chat_store.append_messages(
                            conversation_id,
                            generated_messages,
                        )

                    yield encode_sse(
                        "done",
                        {
                            "conversation_id": conversation_id,
                        },
                    )
                    break

                yield encode_sse(
                    agent_event.event,
                    agent_event.data,
                )
        except asyncio.CancelledError:
            raise

        except (RuntimeError, ValueError, KeyError, sqlite3.Error) as error:
            yield encode_sse(
                "error",
                {
                    "detail": "生成回复失败",
                    "type": type(error).__name__,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
