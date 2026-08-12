# backend/core/web/routers/chat.py

from __future__ import annotations

import asyncio
import logging
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from backend.agent.agent import Agent
from backend.agent.mm import MultimodalSessionService
from backend.agent.DocIR.tools.batch_corpus import SUPPORTED_SOURCE_SUFFIXES
from backend.agent.rag.retrieval.contracts import SearchResponse
from backend.agent.memories.memory_models import ProfileQuery
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import (
    MessageContext,
    PromptContext,
    SessionPrincipal,
    UserRecord,
)
from backend.core.web.concurrency import (
    ConversationTurnCoordinator,
    ConversationTurnLease,
    ConversationTurnTargetMissingError,
    ConversationTurnTimeoutError,
)
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    ConversationCreateRequest,
    ConversationPatchRequest,
    SendMessageRequest,
)
from backend.core.web.sse import encode_sse
from backend.core.workspaces import WorkspaceAccessPolicy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["chat"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENT_CONTEXT_CHARS = 120_000


def _mm_sessions(request: Request) -> MultimodalSessionService:
    service = getattr(request.app.state, "mm_sessions", None)
    if service is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DocIR 附件解析尚未启用",
        )
    return service


def _attachment_out(item) -> dict:
    document = item.document
    return {
        "id": document.document_id,
        "filename": document.source.filename,
        "mode": item.mode.value,
        "token_count": item.token_count,
        "element_count": len(document.elements),
        "page_count": document.source_page_count or document.parsed_page_count,
        "validation_status": document.validation.status.value,
        "quality_issue_count": len(document.quality_issues),
    }


def _render_retrieval(response: SearchResponse) -> str:
    parts: list[str] = []
    for index, hit in enumerate(response.hits, start=1):
        evidence = hit.evidence[0] if hit.evidence else None
        source = evidence.document_name if evidence is not None else "附件"
        location = ""
        if evidence is not None and evidence.locators:
            locator = evidence.locators[0]
            label = locator.get("label") or locator.get("container_id")
            if label:
                location = f" · {label}"
        parts.append(f"## 命中 {index}：{source}{location}\n\n{hit.context_text}")
    return "\n\n".join(parts)


def _attachment_context(
    request: Request,
    conversation_id: str,
    attachment_ids: list[str],
    query: str,
) -> str:
    if not attachment_ids:
        return ""
    service = _mm_sessions(request)
    sections: list[str] = []
    for attachment_id in dict.fromkeys(attachment_ids):
        try:
            value = service.context_for(conversation_id, attachment_id, query)
        except KeyError as error:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "附件不存在或不属于当前对话",
            ) from error
        sections.append(value if isinstance(value, str) else _render_retrieval(value))
    merged = "\n\n".join(sections)
    if len(merged) > MAX_ATTACHMENT_CONTEXT_CHARS:
        merged = merged[:MAX_ATTACHMENT_CONTEXT_CHARS] + "\n\n[附件上下文已按预算截断]"
    return merged


def _turn_coordinator(request: Request) -> ConversationTurnCoordinator:
    coordinator = getattr(
        request.app.state,
        "conversation_turn_coordinator",
        None,
    )
    if not isinstance(coordinator, ConversationTurnCoordinator):
        raise RuntimeError("对话并发协调器尚未初始化")
    return coordinator


async def _acquire_turn(
    request: Request,
    conversation_id: str,
) -> ConversationTurnLease:
    try:
        return await _turn_coordinator(request).acquire(conversation_id)
    except ConversationTurnTargetMissingError as error:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "对话不存在",
        ) from error
    except ConversationTurnTimeoutError as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "上一条消息仍在生成，请稍后重试",
        ) from error


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


def _validate_group_owned(
    request: Request,
    group_id: str | None,
    session: SessionPrincipal,
) -> None:
    """辅助函数：创建/移动对话时校验分组存在且属于当前用户
    非法 group_id 返回 404 保证不会产生孤儿引用

    Args:
        request: Request            => 请求对象
        group_id: str | None        => 分组 id  None 表示未分组 直接通过
        session: SessionPrincipal   => 用户登陆信息
    """
    if group_id is None:
        return

    group_store: GroupStore = request.app.state.group_store
    group = group_store.get_group(group_id)
    if group is None or group["user_id"] != session.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")


def _load_group_params(
    request: Request,
    conversation: dict,
) -> tuple[str | None, str | None, str]:
    """辅助函数：按对话归属分组取出分组级指令参数
    未分组时返回 (None, None, "") 表示风格/语调/指令全部继承用户级

    Args:
        request: Request      => 请求对象
        conversation: dict    => 对话信息(含 group_id)

    Returns:
        tuple[str | None, str | None, str]:
            (group_style, group_tone, group_custom_instruction)
    """
    group_id = conversation.get("group_id")
    if group_id is None:
        return None, None, ""

    group_store: GroupStore = request.app.state.group_store
    group = group_store.get_group(group_id)
    if group is None:
        # 分组已被删除的防御性兜底 按未分组处理
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
    """公共前置: 取对话 + 校验归属 + 取用户 + 401 + 加载历史 + 落库用户消息 + 学情档案 + 分组参数

    send_message 与 stream_message 共用 消除前 35 行重复代码

    Args:
        request: Request            => 请求对象
        conversation_id: str        => 对话 id
        body: SendMessageRequest    => 用户消息体
        session: SessionPrincipal   => 用户登陆信息

    Returns:
        MessageContext              => agent 调用所需的全部上下文
    """
    conversation = _load_owned(request, conversation_id, session)

    chat_store: ChatStore = request.app.state.chat_store
    user_store: UserStore = request.app.state.user_store

    user: UserRecord | None = user_store.get_by_id(session.user_id)
    if user is None:
        session_store: SessionStore = request.app.state.session_store
        session_store.revoke(session.session_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在！")

    # 读取模型历史 + 落库用户消息 同一事务原子完成 避免并发读-写竞态
    conversation_summary, history = (
        chat_store.get_compressed_model_history_and_append(
            conversation_id,
            [{"role": "user", "content": body.content, "is_visible": True}],
        )
    )

    # 会话记忆模式: normal(读+写) / no_write(只读) / isolated(不读不写)
    settings = user_store.get_memory_settings(user.id)
    conversation_mode = (
        settings.default_conversation_mode if settings is not None else "normal"
    )
    workspace_type = conversation.get("workspace_type", "learning")
    kp_resolver = getattr(request.app.state, "kp_resolver", None)
    kp_matches = (
        kp_resolver.resolve(body.content, limit=3)
        if kp_resolver is not None and workspace_type == "learning"
        else []
    )
    resolved_kp_ids = [match.kp_id for match in kp_matches]

    group_style, group_tone, group_custom_instruction = _load_group_params(
        request,
        conversation,
    )

    # isolated 会话不读取长期记忆 不构建画像快照
    user_profile_context = (
        None
        if conversation_mode == "isolated" or workspace_type != "learning"
        else request.app.state.profile_builder.build(
            ProfileQuery(
                user_id=user.id,
                username=user.username,
                conversation_id=conversation_id,
                group_id=conversation.get("group_id"),
                current_message=body.content,
                recent_messages=history,
                resolved_kp_ids=resolved_kp_ids,
                group_style=group_style,
                group_tone=group_tone,
                group_custom_instruction=group_custom_instruction,
            )
        )
    )

    return MessageContext(
        user=user,
        history=history,
        user_profile_context=user_profile_context,
        group_style=group_style,
        group_tone=group_tone,
        group_custom_instruction=group_custom_instruction,
        conversation_summary=conversation_summary or "",
        conversation_mode=conversation_mode,
        workspace_type=workspace_type,
    )


def _build_prompt_context(
    ctx: MessageContext, *, attachment_context: str = ""
) -> PromptContext:
    """将 MessageContext 收敛为 PromptContext 供 agent 构建提示词

    Args:
        ctx: MessageContext => 发消息公共前置结果

    Returns:
        PromptContext => prompt 构建上下文
    """
    return PromptContext(
        preferred_style=ctx.user.preferred_style,
        preferred_tone=ctx.user.preferred_tone,
        custom_instruction=ctx.user.custom_instruction,
        user_profile_context=ctx.user_profile_context,
        group_style=ctx.group_style,
        group_tone=ctx.group_tone,
        group_custom_instruction=ctx.group_custom_instruction,
        conversation_summary=ctx.conversation_summary,
        conversation_mode=ctx.conversation_mode,
        attachment_context=attachment_context,
        workspace_type=ctx.workspace_type,
    )


@router.get("")
def list_conversations(
    request: Request,
    session: CurrentSession,
    workspace_type: str | None = None,
) -> list[dict]:
    chat_store: ChatStore = request.app.state.chat_store
    if workspace_type is not None:
        user_store: UserStore = request.app.state.user_store
        user = user_store.get_by_id(session.user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
        if not WorkspaceAccessPolicy.can_access(user.account_role, workspace_type):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace access denied")
    return chat_store.list_conversations(
        session.user_id,
        workspace_type=workspace_type,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    session: CurrentSession,
    body: ConversationCreateRequest | None = None,
) -> dict:
    body = body or ConversationCreateRequest()
    _validate_group_owned(request, body.group_id, session)
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    if not WorkspaceAccessPolicy.can_access(user.account_role, body.workspace_type):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace access denied")
    if body.research_project_id is not None:
        project_store: ResearchProjectStore = request.app.state.research_project_store
        project = project_store.get_project(body.research_project_id, session.user_id)
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "research project not found")
        if project["status"] != "active":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "archived research project cannot accept new conversations",
            )
    chat_store: ChatStore = request.app.state.chat_store
    return chat_store.create_conversation(
        session.user_id,
        title=body.title,
        group_id=body.group_id,
        workspace_type=body.workspace_type,
        research_project_id=body.research_project_id,
    )


@router.patch(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def update_conversation(
    conversation_id: str,
    body: ConversationPatchRequest,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned(request, conversation_id, session)
    updates = body.model_dump(exclude_unset=True)

    # title 为非空列 显式 null 视为未提供 避免写入 NULL 触发 500
    if "title" in updates and updates["title"] is None:
        del updates["title"]

    if not updates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "至少需要提供 title 或 group_id 中的一个",
        )

    # 移动分组时校验目标分组归属
    if "group_id" in updates:
        _validate_group_owned(request, updates["group_id"], session)

    chat_store: ChatStore = request.app.state.chat_store

    if "title" in updates:
        chat_store.rename_conversation(conversation_id, updates["title"])

    if "group_id" in updates:
        chat_store.set_conversation_group(conversation_id, updates["group_id"])


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned(request, conversation_id, session)
    chat_store: ChatStore = request.app.state.chat_store
    chat_store.delete_conversation(conversation_id)
    mm_sessions = getattr(request.app.state, "mm_sessions", None)
    if mm_sessions is not None:
        await mm_sessions.clear(conversation_id)


@router.post("/{conversation_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    conversation_id: str,
    request: Request,
    session: CurrentSession,
    file: Annotated[UploadFile, File()],
) -> dict:
    _load_owned(request, conversation_id, session)
    filename = Path((file.filename or "attachment").replace("\\", "/")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        supported = "、".join(sorted(item.lstrip(".") for item in SUPPORTED_SOURCE_SUFFIXES))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"DocIR 不支持该文件类型；支持：{supported}",
        )
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件为空")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件不能超过 15 MB")

    try:
        with tempfile.TemporaryDirectory(prefix="esa-attachment-") as temporary:
            source = Path(temporary) / filename
            source.write_bytes(data)
            prepared = await _mm_sessions(request).prepare(
                conversation_id,
                [source],
            )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "DocIR 解析附件失败") from error
    return _attachment_out(prepared[0])


@router.delete(
    "/{conversation_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_attachment(
    conversation_id: str,
    attachment_id: str,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned(request, conversation_id, session)
    if not await _mm_sessions(request).remove(conversation_id, attachment_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "附件不存在")


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
    # 在排队前先校验归属，避免无权用户占用其他会话的租约。
    _load_owned(request, conversation_id, session)
    lease = await _acquire_turn(request, conversation_id)
    async with lease:
        attachment_context = _attachment_context(
            request, conversation_id, body.attachment_ids, body.content
        )
        ctx = _prepare_message(request, conversation_id, body, session)
        chat_store: ChatStore = request.app.state.chat_store
        agent: Agent = request.app.state.agent

        new_messages: list[dict] = await agent.run(
            body.content,
            ctx.user.username,
            history=ctx.history,
            prompt_ctx=_build_prompt_context(
                ctx, attachment_context=attachment_context
            ),
            total_weeks=ctx.user.total_weeks,
        )

        generated_messages: list[dict] = new_messages[1:]
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
    _load_owned(request, conversation_id, session)
    lease = await _acquire_turn(request, conversation_id)
    try:
        attachment_context = _attachment_context(
            request, conversation_id, body.attachment_ids, body.content
        )
        ctx = _prepare_message(request, conversation_id, body, session)
        chat_store: ChatStore = request.app.state.chat_store
        agent: Agent = request.app.state.agent
        prompt_ctx = _build_prompt_context(
            ctx, attachment_context=attachment_context
        )
    except BaseException:
        await lease.release()
        raise

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
                ctx.user.username,
                history=ctx.history,
                prompt_ctx=prompt_ctx,
                total_weeks=ctx.user.total_weeks,
            ):
                if agent_event.event == "complete":
                    new_messages = agent_event.data["messages"]

                    generated_messages = new_messages[1:]

                    if generated_messages:
                        chat_store.append_messages(conversation_id, generated_messages)

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
            logger.exception("agent 推理失败")
            yield encode_sse(
                "error",
                {
                    "detail": "生成回复失败",
                    "type": type(error).__name__,
                },
            )
        finally:
            await lease.release()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
