# backend/core/web/routers/chat.py

from __future__ import annotations

import asyncio
import logging
import sqlite3
from uuid import uuid4
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from backend.agent.agent import Agent
from backend.agent.tools.context import AgentRuntimeDependencies
from backend.agent.workspaces.models import AgentTurnInput
from backend.agent.workspaces.runtime import WorkspaceRuntime
from backend.agent.mm import MultimodalSessionService
from backend.agent.DocIR.tools.batch_corpus import SUPPORTED_SOURCE_SUFFIXES
from backend.agent.memories.memory_models import ProfileQuery
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.classroom_conversation_store import ClassroomConversationStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.router import (
    AttachmentAuthorization,
    ConversationContext,
    RoutingContext,
    authorize_classroom_resources,
    resolve_identity,
    route_workspace,
)
from backend.core.services.teaching_context_adapter import TeachingContextAdapter
from backend.core.services.user_attachment_service import (
    AttachmentTooLarge,
    StoredAttachment,
    UserAttachmentStore,
)
from backend.core.utils.models import (
    MessageContext,
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


def _mm_sessions(request: Request) -> MultimodalSessionService:
    service = getattr(request.app.state, "mm_sessions", None)
    if service is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DocIR 附件解析尚未启用",
        )
    return service


def _attachment_store(request: Request) -> UserAttachmentStore:
    store = getattr(request.app.state, "user_attachment_store", None)
    if not isinstance(store, UserAttachmentStore):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "附件存储尚未配置",
        )
    return store


def _attachment_out(item: StoredAttachment) -> dict:
    return {
        "id": item.attachment_id,
        "filename": item.filename,
        "mode": "pending",
        "token_count": 0,
        "element_count": 0,
        "page_count": 0,
        "validation_status": "pending",
        "quality_issue_count": 0,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
    }


def _attachment_inventory(
    request: Request,
    user_id: str,
    conversation_id: str,
    attachment_ids: list[str],
) -> tuple[tuple[dict, ...], list[dict]]:
    if not attachment_ids:
        return (), []
    store = _attachment_store(request)
    try:
        items = store.require_many(
            user_id=user_id,
            conversation_id=conversation_id,
            attachment_ids=attachment_ids,
        )
    except KeyError as error:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "附件不存在或不属于当前用户和对话",
        ) from error
    _mm_sessions(request)
    authorized_attachments = tuple(
        {
            "attachment_id": item.attachment_id,
            "filename": item.filename,
            "suffix": item.suffix,
            "media_type": item.media_type,
            "size_bytes": item.size_bytes,
            "status": "stored_unparsed",
        }
        for item in items
    )
    return (
        authorized_attachments,
        [
            {
                "id": item.attachment_id,
                "filename": item.filename,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
            }
            for item in items
        ],
    )


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


def _classroom_binding_out(request: Request, binding: dict | None) -> dict | None:
    if binding is None:
        return None
    result = dict(binding)
    teaching_store = getattr(request.app.state, "teaching_store", None)
    if teaching_store is None:
        return result
    classroom = teaching_store.get_class(result["class_id"])
    if classroom is not None:
        result["class_name"] = classroom.get("name")
    assignment_id = result.get("assignment_id")
    if assignment_id:
        assignment = teaching_store.get_assignment(assignment_id)
        if assignment is not None:
            result["assignment_title"] = assignment.get("title")
    return result


def _authorize_classroom_binding(
    request: Request,
    *,
    session: SessionPrincipal,
    user: UserRecord,
    workspace_type: str,
    class_id: str | None,
    assignment_id: str | None,
):
    identity = resolve_identity(session, user)
    if class_id is None and assignment_id is None:
        return authorize_classroom_resources(
            teaching_store=None,
            identity=identity,
            workspace_type=workspace_type,
            class_id=None,
            assignment_id=None,
        )
    teaching_store = getattr(request.app.state, "teaching_store", None)
    if teaching_store is None:
        raise RuntimeError("teaching store is required for classroom bindings")
    return authorize_classroom_resources(
        teaching_store=teaching_store,
        identity=identity,
        workspace_type=workspace_type,
        class_id=class_id,
        assignment_id=assignment_id,
    )


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
    attachments: list[dict] | None = None,
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
    if body.replace_message_id is None:
        conversation_summary, history = (
            chat_store.get_compressed_model_history_and_append(
                conversation_id,
                [
                    {
                        "role": "user",
                        "content": body.content,
                        "attachments": attachments or [],
                        "is_visible": True,
                    }
                ],
            )
        )
        user_message_id = chat_store.latest_message_id(conversation_id)
    else:
        conversation_summary, history = chat_store.revise_user_message(
            conversation_id,
            body.replace_message_id,
            body.content,
            attachments or [],
        )
        user_message_id = body.replace_message_id

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
        user_message_id=user_message_id,
    )


def _runtime_dependencies(
    request: Request,
    ctx: MessageContext,
) -> AgentRuntimeDependencies:
    state = request.app.state
    teaching_store = getattr(state, "teaching_store", None)
    return AgentRuntimeDependencies(
        user_store=getattr(state, "user_store", None),
        profile_store=getattr(state, "profile_store", None),
        chat_store=getattr(state, "chat_store", None),
        teaching_store=teaching_store,
        teaching_context_reader=(
            TeachingContextAdapter(teaching_store) if teaching_store is not None else None
        ),
        research_project_store=getattr(state, "research_project_store", None),
        research_project_profile_service=getattr(
            state, "research_project_profile_service", None
        ),
        agent_action_service=getattr(state, "agent_action_service", None),
        core_memory_service=getattr(state, "core_memory_service", None),
        frontier_tracking_service=getattr(state, "frontier_tracking_service", None),
        research_writing_service=getattr(state, "research_writing_service", None),
        research_data_service=getattr(state, "research_data_service", None),
        attachment_store=getattr(state, "user_attachment_store", None),
        multimodal_sessions=getattr(state, "mm_sessions", None),
        knowledge_graph_store=getattr(state, "knowledge_graph_store", None),
        mastery_store=getattr(state, "mastery_store", None),
        learning_evidence_store=getattr(state, "learning_evidence_store", None),
        learning_state_service=getattr(state, "learning_state_service", None),
        rag_service=getattr(state, "rag_service", None),
    )


def _build_run_spec(
    request: Request,
    session: SessionPrincipal,
    conversation_id: str,
    body: SendMessageRequest,
    ctx: MessageContext,
    authorized_attachments: tuple[dict, ...],
):
    conversation = _load_owned(request, conversation_id, session)
    identity = resolve_identity(session, ctx.user)
    project_id = conversation.get("research_project_id")
    binding_store = getattr(request.app.state, "classroom_conversation_store", None)
    classroom_binding = (
        binding_store.get(conversation_id, session.user_id)
        if isinstance(binding_store, ClassroomConversationStore)
        else None
    )
    class_id = classroom_binding.get("class_id") if classroom_binding else None
    assignment_id = (
        classroom_binding.get("assignment_id") if classroom_binding else None
    )
    project_profile = ""
    profile_service = getattr(
        request.app.state, "research_project_profile_service", None
    )
    if project_id and profile_service is not None:
        profile = profile_service.get(project_id, session.user_id)
        if profile is not None:
            project_profile = profile["agent_instructions"]
    project = (
        request.app.state.research_project_store.get_project(
            project_id, session.user_id
        )
        if project_id
        else None
    )
    classroom_authorization = _authorize_classroom_binding(
        request,
        session=session,
        user=ctx.user,
        workspace_type=conversation.get("workspace_type", "learning"),
        class_id=class_id,
        assignment_id=assignment_id,
    )
    route = route_workspace(
        identity,
        RoutingContext(
            conversation=ConversationContext(
                conversation_id=conversation_id,
                user_id=session.user_id,
                workspace_type=conversation.get("workspace_type", "learning"),
                research_project_id=project_id,
                class_id=class_id,
                assignment_id=assignment_id,
            ),
            attachments=AttachmentAuthorization(
                tuple(item["attachment_id"] for item in authorized_attachments)
            ),
            project_owned=project_id is None
            or (project is not None and project.get("status") == "active"),
            class_authorized=classroom_authorization.class_authorized,
            assignment_authorized=classroom_authorization.assignment_authorized,
            resource_capabilities=frozenset(
                {"attachments"} if authorized_attachments else set()
            )
            | frozenset({"research_project"} if project_id else set())
            | classroom_authorization.capabilities,
        ),
    )
    group = {
        "style": ctx.group_style,
        "tone": ctx.group_tone,
        "custom_instruction": ctx.group_custom_instruction,
    }
    turn = AgentTurnInput(
        route=route,
        identity=identity,
        conversation_id=conversation_id,
        current_message=body.content,
        history=tuple(ctx.history),
        conversation_summary=ctx.conversation_summary,
        conversation_mode=ctx.conversation_mode,
        user_preferences={
            "preferred_style": ctx.user.preferred_style,
            "preferred_tone": ctx.user.preferred_tone,
            "custom_instruction": ctx.user.custom_instruction,
        },
        group_context=group,
        workspace_profile_context=project_profile,
        profile_snapshot=ctx.user_profile_context,
        authorized_attachments=authorized_attachments,
        request_metadata={
            "request_id": uuid4().hex,
            "total_weeks": ctx.user.total_weeks,
        },
    )
    runtime = WorkspaceRuntime(
        _runtime_dependencies(request, ctx)
    )
    return runtime.prepare(turn)


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
    conversations = chat_store.list_conversations(
        session.user_id,
        workspace_type=workspace_type,
    )
    binding_store = getattr(request.app.state, "classroom_conversation_store", None)
    if isinstance(binding_store, ClassroomConversationStore):
        for conversation in conversations:
            conversation["classroom_binding"] = binding_store.get(
                conversation["conversation_id"], session.user_id
            )
            conversation["classroom_binding"] = _classroom_binding_out(
                request, conversation["classroom_binding"]
            )
    return conversations


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
    conversation = chat_store.create_conversation(
        session.user_id,
        title=body.title,
        group_id=body.group_id,
        workspace_type=body.workspace_type,
        research_project_id=body.research_project_id,
    )
    if body.workspace_type in {"learning", "teaching"} and body.class_id is not None:
        authorization = _authorize_classroom_binding(
            request,
            session=session,
            user=user,
            workspace_type=body.workspace_type,
            class_id=body.class_id,
            assignment_id=body.assignment_id,
        )
        if not authorization.authorized:
            chat_store.delete_conversation(
                conversation["conversation_id"], session.user_id
            )
            raise HTTPException(status.HTTP_404_NOT_FOUND, "classroom resource not found")
        binding_store = request.app.state.classroom_conversation_store
        conversation["classroom_binding"] = _classroom_binding_out(
            request,
            binding_store.bind(
            conversation_id=conversation["conversation_id"],
            user_id=session.user_id,
            class_id=body.class_id,
            assignment_id=body.assignment_id,
            ),
        )
    elif body.class_id is not None or body.assignment_id is not None:
        chat_store.delete_conversation(conversation["conversation_id"], session.user_id)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "classroom binding requires learning or teaching workspace",
        )
    return conversation


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
            "至少需要提供 title、group_id、class_id 或 assignment_id 中的一个",
        )

    # 移动分组时校验目标分组归属
    if "group_id" in updates:
        _validate_group_owned(request, updates["group_id"], session)

    if "class_id" in updates or "assignment_id" in updates:
        conversation = _load_owned(request, conversation_id, session)
        workspace_type = conversation.get("workspace_type", "learning")
        if workspace_type not in {"learning", "teaching"}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "classroom binding requires learning or teaching workspace",
            )
        binding_store = request.app.state.classroom_conversation_store
        current = binding_store.get(conversation_id, session.user_id) or {}
        class_id = updates.get("class_id", current.get("class_id"))
        assignment_id = updates.get("assignment_id", current.get("assignment_id"))
        if "class_id" in updates and class_id != current.get("class_id"):
            assignment_id = updates.get("assignment_id")
        if class_id is None:
            if assignment_id is not None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "assignment_id requires class_id",
                )
            binding_store.unbind(conversation_id, session.user_id)
        else:
            user = request.app.state.user_store.get_by_id(session.user_id)
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
            authorization = _authorize_classroom_binding(
                request,
                session=session,
                user=user,
                workspace_type=workspace_type,
                class_id=class_id,
                assignment_id=assignment_id,
            )
            if not authorization.authorized:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "classroom resource not found"
                )
            binding_store.bind(
                conversation_id=conversation_id, user_id=session.user_id,
                class_id=class_id, assignment_id=assignment_id,
            )

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
    attachment_store = getattr(request.app.state, "user_attachment_store", None)
    if isinstance(attachment_store, UserAttachmentStore):
        attachment_store.delete_conversation(
            user_id=session.user_id,
            conversation_id=conversation_id,
        )
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
    try:
        stored = await _attachment_store(request).save(
            user_id=session.user_id,
            conversation_id=conversation_id,
            filename=filename,
            media_type=file.content_type or "application/octet-stream",
            read=file.read,
        )
    except AttachmentTooLarge as error:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    finally:
        await file.close()
    return _attachment_out(stored)


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
    removed = _attachment_store(request).delete(
        user_id=session.user_id,
        conversation_id=conversation_id,
        attachment_id=attachment_id,
    )
    mm_sessions = getattr(request.app.state, "mm_sessions", None)
    if isinstance(mm_sessions, MultimodalSessionService):
        await mm_sessions.remove(conversation_id, attachment_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "附件不存在")


@router.get("/{conversation_id}/attachments/{attachment_id}")
def get_attachment(
    conversation_id: str,
    attachment_id: str,
    request: Request,
    session: CurrentSession,
    download: bool = False,
) -> FileResponse:
    _load_owned(request, conversation_id, session)
    item = _attachment_store(request).get(
        user_id=session.user_id,
        conversation_id=conversation_id,
        attachment_id=attachment_id,
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "附件不存在")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        item.source_path,
        media_type=item.media_type,
        filename=item.filename,
        content_disposition_type=disposition,
    )


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
        authorized_attachments, attachments = _attachment_inventory(
            request,
            session.user_id,
            conversation_id,
            body.attachment_ids,
        )
        try:
            ctx = _prepare_message(
                request, conversation_id, body, session, attachments
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        chat_store: ChatStore = request.app.state.chat_store
        agent: Agent = request.app.state.agent

        run_spec = _build_run_spec(
            request,
            session,
            conversation_id,
            body,
            ctx,
            authorized_attachments,
        )
        new_messages: list[dict] = await agent.run(run_spec)

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
        authorized_attachments, attachments = _attachment_inventory(
            request,
            session.user_id,
            conversation_id,
            body.attachment_ids,
        )
        try:
            ctx = _prepare_message(
                request, conversation_id, body, session, attachments
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
        chat_store: ChatStore = request.app.state.chat_store
        agent: Agent = request.app.state.agent
        run_spec = _build_run_spec(
            request,
            session,
            conversation_id,
            body,
            ctx,
            authorized_attachments,
        )
    except BaseException:
        await lease.release()
        raise

    async def event_stream() -> AsyncIterator[str]:
        yield encode_sse(
            "start",
            {
                "conversation_id": conversation_id,
                "user_message_id": ctx.user_message_id,
            },
        )

        try:
            async for agent_event in agent.run_stream(run_spec):
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
