"""Authenticated, read-only access to public knowledge-base source files."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from backend.agent.DocIR.io import load_document
from backend.core.utils.config import RAG_PUBLIC_DOCIR_ROOT
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session


router = APIRouter(prefix="/knowledge-base/public", tags=["public knowledge base"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _resolve_source(document_id: str) -> tuple[Path, str, str]:
    root = RAG_PUBLIC_DOCIR_ROOT.resolve()
    if not root.is_dir():
        raise HTTPException(503, "公共知识库原文目录未配置")
    for metadata_path in root.glob("*/document.json"):
        try:
            document = load_document(metadata_path)
        except (OSError, ValueError):
            continue
        if document.document_id != document_id:
            continue
        asset = next(
            (
                item
                for item in document.assets
                if item.asset_id == document.source.original_asset_id
            ),
            None,
        )
        if asset is None:
            break
        candidate = (metadata_path.parent / asset.path).resolve(strict=False)
        try:
            candidate.relative_to(metadata_path.parent.resolve())
        except ValueError as exc:
            raise HTTPException(500, "公共知识库原文路径无效") from exc
        if not candidate.is_file():
            raise HTTPException(404, "公共知识库原文文件不存在")
        return candidate, document.source.media_type, document.source.filename
    raise HTTPException(404, "公共知识库文档不存在")


@router.get("/documents/{document_id}/content")
def get_public_knowledge_base_document(
    document_id: str,
    request: Request,
    _session: CurrentSession,
) -> FileResponse:
    path, media_type, filename = _resolve_source(document_id)
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=300"},
    )
