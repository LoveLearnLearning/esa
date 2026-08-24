# backend/agent/tools/common/attachment_tools.py

"""Ownership-scoped tools for lazily parsing persisted chat attachments."""

from __future__ import annotations

from typing import Any, Mapping

from backend.agent.rag.retrieval.contracts import SearchResponse
from backend.agent.tools.context import ToolExecutionContext
from backend.agent.tools.tools import tr
from backend.core.log.logger import get_pipeline_logger, pipeline_log_context

logger = get_pipeline_logger("MM", __name__)


def _render_retrieval(response: SearchResponse) -> str:
    """渲染 `retrieval` 相关数据。"""
    parts = []
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


async def _parse_attachment(
    context: ToolExecutionContext,
    attachment_id: str,
    query: str,
    *,
    allowed_suffixes: frozenset[str],
    kind: str,
) -> dict[str, object]:
    """解析 `attachment` 相关数据。"""
    allowed = context.authorized_resources.attachment_ids
    if attachment_id not in allowed:
        raise ValueError("附件未在当前消息中授权")
    store = context.runtime_dependencies.attachment_store
    sessions = context.runtime_dependencies.multimodal_sessions
    if store is None or sessions is None:
        raise RuntimeError("附件工具依赖未配置")
    item = store.get(
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        attachment_id=attachment_id,
    )
    if item is None:
        raise ValueError("附件不存在或不属于当前用户和对话")
    if item.suffix not in allowed_suffixes:
        expected = "、".join(sorted(suffix.lstrip(".") for suffix in allowed_suffixes))
        raise ValueError(f"该工具只支持 {expected} 文件")
    normalized_query = query.strip() or "概括文件的主要内容"
    with pipeline_log_context(
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        attachment_id=attachment_id,
    ):
        logger.info(
            "lazy attachment parse started kind=%s filename=%s size_bytes=%d",
            kind,
            item.filename,
            item.size_bytes,
        )
        prepared = await sessions.prepare_attachment(
            context.conversation_id,
            attachment_id,
            item.source_path,
        )
        value = prepared.context_for(normalized_query)
        content = value if isinstance(value, str) else _render_retrieval(value)
        logger.info(
            "lazy attachment parse completed kind=%s mode=%s tokens=%d",
            kind,
            prepared.mode.value,
            prepared.token_count,
        )
    return {
        "attachment_id": attachment_id,
        "filename": item.filename,
        "kind": kind,
        "mode": prepared.mode.value,
        "token_count": prepared.token_count,
        "element_count": len(prepared.document.elements),
        "page_count": (
            prepared.document.source_page_count or prepared.document.parsed_page_count
        ),
        "content": content[:120_000],
    }


def _schema(name: str, description: str) -> dict:
    """处理 `_schema` 相关逻辑。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "系统附件清单中的附件 ID",
                    },
                    "query": {
                        "type": "string",
                        "description": "需要从文件回答的问题或需要提取的内容",
                    },
                },
                "required": ["attachment_id", "query"],
            },
        },
    }


async def parse_pdf_attachment(
    context: ToolExecutionContext, attachment_id: str, query: str
) -> dict[str, object]:
    """解析 `pdf attachment` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        attachment_id: str => 附件 ID。
        query: str => 查询文本。

    Returns:
        dict[str, object] => 处理结果。
    """
    return await _parse_attachment(
        context,
        attachment_id,
        query,
        allowed_suffixes=frozenset({".pdf"}),
        kind="pdf",
    )


async def parse_word_attachment(
    context: ToolExecutionContext, attachment_id: str, query: str
) -> dict[str, object]:
    """解析 `word attachment` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        attachment_id: str => 附件 ID。
        query: str => 查询文本。

    Returns:
        dict[str, object] => 处理结果。
    """
    return await _parse_attachment(
        context,
        attachment_id,
        query,
        allowed_suffixes=frozenset({".docx"}),
        kind="word",
    )


async def parse_presentation_attachment(
    context: ToolExecutionContext,
    attachment_id: str,
    query: str,
) -> dict[str, object]:
    """解析 `presentation attachment` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        attachment_id: str => 附件 ID。
        query: str => 查询文本。

    Returns:
        dict[str, object] => 处理结果。
    """
    return await _parse_attachment(
        context,
        attachment_id,
        query,
        allowed_suffixes=frozenset({".pptx"}),
        kind="presentation",
    )


async def parse_spreadsheet_attachment(
    context: ToolExecutionContext,
    attachment_id: str,
    query: str,
) -> dict[str, object]:
    """解析 `spreadsheet attachment` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        attachment_id: str => 附件 ID。
        query: str => 查询文本。

    Returns:
        dict[str, object] => 处理结果。
    """
    return await _parse_attachment(
        context,
        attachment_id,
        query,
        allowed_suffixes=frozenset({".xlsx"}),
        kind="spreadsheet",
    )


async def parse_image_attachment(
    context: ToolExecutionContext, attachment_id: str, query: str
) -> dict[str, object]:
    """解析 `image attachment` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        attachment_id: str => 附件 ID。
        query: str => 查询文本。

    Returns:
        dict[str, object] => 处理结果。
    """
    return await _parse_attachment(
        context,
        attachment_id,
        query,
        allowed_suffixes=frozenset(
            {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
        ),
        kind="image",
    )


async def execute_attachment_tool(
    context: ToolExecutionContext, name: str, arguments: Mapping[str, Any]
) -> dict[str, object]:
    """执行 `attachment tool` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        name: str => `name` 参数。
        arguments: Mapping[str, Any] => `arguments` 参数。

    Returns:
        dict[str, object] => 处理结果。
    """
    handlers = {
        "parse_pdf_attachment": parse_pdf_attachment,
        "parse_word_attachment": parse_word_attachment,
        "parse_presentation_attachment": parse_presentation_attachment,
        "parse_spreadsheet_attachment": parse_spreadsheet_attachment,
        "parse_image_attachment": parse_image_attachment,
    }
    handler = handlers.get(name)
    if handler is None:
        raise KeyError(name)
    return await handler(
        context,
        str(arguments.get("attachment_id", "")),
        str(arguments.get("query", "")),
    )


ATTACHMENT_TOOL_SCHEMAS = (
    _schema(
        "parse_pdf_attachment",
        "读取当前消息已授权的 PDF 附件。用户要求解释、总结、阅读、分析或检索这篇论文/这个 PDF 时必须调用",
    ),
    _schema(
        "parse_word_attachment",
        "读取当前消息已授权的 Word 附件。用户要求解释、总结、阅读或分析这个文档时必须调用",
    ),
    _schema(
        "parse_presentation_attachment",
        "读取当前消息已授权的演示文稿附件。用户要求解释、总结或分析这个演示文稿时必须调用",
    ),
    _schema(
        "parse_spreadsheet_attachment",
        "读取当前消息已授权的电子表格附件。用户要求读取、分析或总结表格时必须调用",
    ),
    _schema(
        "parse_image_attachment",
        "读取当前消息已授权的图片附件。用户要求识别、解释或分析这张图片时必须调用",
    ),
)


def register_attachment_schemas() -> None:
    """注册 `attachment schemas` 相关数据。"""
    for schema in ATTACHMENT_TOOL_SCHEMAS:

        def unavailable(**_arguments):
            """处理 `unavailable` 相关逻辑。"""
            raise RuntimeError("attachment tool requires BoundToolExecutor")

        tr.register(schema)(unavailable)
