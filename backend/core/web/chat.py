# backend/core/web/routers/chat.py

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from backend.agent.agent import Agent, build_user_profile_context
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import (
    MessageContext,
    PromptContext,
    SessionPrincipal,
    UserRecord,
)
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    ConversationCreateRequest,
    ConversationPatchRequest,
    SendMessageRequest,
)
from backend.core.web.sse import encode_sse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["chat"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _load_owned(
    request: Request,
    conversation_id: str,
    session: SessionPrincipal,
) -> dict:
    chat_store: ChatStore = request.app.state.chat_store
    conversation = chat_store.get_conversation(
        conversation_id,
        user_id=session.user_id,
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return conversation


def _validate_group_owned(
    request: Request,
    group_id: str | None,
    session: SessionPrincipal,
) -> None:
    if group_id is None:
        return

    group_store: GroupStore = request.app.state.group_store
    if group_store.get_group(group_id, user_id=session.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")


def _load_group_params(
    request: Request,
    conversation: dict,
) -> tuple[str | None, str | None, str]:
    group_id = conversation.get("group_id")
    if group_id is None:
        return None, None, ""

    group_store: GroupStore = request.app.state.group_store
    group = group_store.get_group(
        group_id,
        user_id=conversation["user_id"],
    )
    if group is None:
        # 数据被手工修改或分组已删除时，安全降级为未分组。
        return None, None, ""

    return (
        group.get("style"),
        group.get("tone"),
        group.get("custom_instruction", ""),
    )


def _prepare_message(
    request: Request,
    conversation_id: str,
    body: SendMessageRequest,
    session: SessionPrincipal,
) -> MessageContext:
    conversation = _load_owned(request, conversation_id, session)

    chat_store: ChatStore = request.app.state.chat_store
    user_store: UserStore = request.app.state.user_store
    user: UserRecord | None = user_store.get_by_id(session.user_id)
    if user is None:
        session_store: SessionStore = request.app.state.session_store
        session_store.revoke(session.session_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在！")

    history = chat_store.get_model_messages(conversation_id)
    chat_store.append_messages(
        conversation_id,
        [{"role": "user", "content": body.content, "is_visible": True}],
    )

    group_style, group_tone, group_custom_instruction = _load_group_params(
        request,
        conversation,
    )
    return MessageContext(
        user=user,
        history=history,
        user_profile_context=build_user_profile_context(user),
        group_style=group_style,
        group_tone=group_tone,
        group_custom_instruction=group_custom_instruction,
    )


def _build_prompt_context(ctx: MessageContext) -> PromptContext:
    return PromptContext(
        preferred_style=ctx.user.preferred_style,
        preferred_tone=ctx.user.preferred_tone,
        custom_instruction=ctx.user.custom_instruction,
        user_profile_context=ctx.user_profile_context,
        group_style=ctx.group_style,
        group_tone=ctx.group_tone,
        group_custom_instruction=ctx.group_custom_instruction,
    )


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
    body: ConversationCreateRequest | None = None,
) -> dict:
    body = body or ConversationCreateRequest()
    _validate_group_owned(request, body.group_id, session)

    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.create_conversation(
        session.user_id,
        title=body.title,
        group_id=body.group_id,
    )


@router.patch("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_conversation(
    conversation_id: str,
    body: ConversationPatchRequest,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned(request, conversation_id, session)
    updates = body.model_dump(exclude_unset=True)

    # title 是 NOT NULL 字段；显式 null 不应落库。
    if updates.get("title") is None:
        updates.pop("title", None)
    if not updates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "至少需要提供 title 或 group_id 中的一个",
        )

    if "group_id" in updates:
        _validate_group_owned(request, updates["group_id"], session)

    chat_store: ChatStore = request.app.state.chat_store
    if "title" in updates and not chat_store.rename_conversation(
        conversation_id,
        updates["title"],
        user_id=session.user_id,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")

    if "group_id" in updates and not chat_store.set_conversation_group(
        conversation_id,
        updates["group_id"],
        user_id=session.user_id,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    request: Request,
    session: CurrentSession,
) -> None:
    chat_store: ChatStore = request.app.state.chat_store
    if not chat_store.delete_conversation(
        conversation_id,
        user_id=session.user_id,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")


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
    ctx = _prepare_message(request, conversation_id, body, session)
    chat_store: ChatStore = request.app.state.chat_store
    agent: Agent = request.app.state.agent

    new_messages = await agent.run(
        body.content,
        ctx.user.username,
        history=ctx.history,
        prompt_ctx=_build_prompt_context(ctx),
        total_weeks=ctx.user.total_weeks,
    )
    generated_messages = new_messages[1:]
    if generated_messages:
        chat_store.append_messages(conversation_id, generated_messages)

    return [message for message in new_messages if message.get("is_visible", True)]


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    session: CurrentSession,
) -> StreamingResponse:
    ctx = _prepare_message(request, conversation_id, body, session)
    chat_store: ChatStore = request.app.state.chat_store
    agent: Agent = request.app.state.agent
    prompt_ctx = _build_prompt_context(ctx)

    async def event_stream() -> AsyncIterator[str]:
        yield encode_sse(
            "start",
            {"conversation_id": conversation_id},
        )
        try:
            async for agent_event in agent.run_stream(
                body.content,
                ctx.user.username,
                history=ctx.history,
                prompt_ctx=prompt_ctx,
                total_weeks=ctx.user.total_weeks,
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
                        {"conversation_id": conversation_id},
                    )
                    break

                yield encode_sse(agent_event.event, agent_event.data)
        except asyncio.CancelledError:
            raise
        except (RuntimeError, ValueError, KeyError, sqlite3.Error) as error:
            logger.exception("agent 推理失败")
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
