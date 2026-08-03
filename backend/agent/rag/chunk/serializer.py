# backend/agent/rag/chunk/serializer.py

"""

这个文件干什么：Chunk 模块的确定性、原子 JSON 读写。

直白点说就是：用固定格式和原子写入保存 Chunk JSON，读取时再检查类型和内容。

Chunk 模块的确定性、原子 JSON 读写。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .models import ChunkCollection, ChunkDocument

T = TypeVar("T", bound=BaseModel)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(model: BaseModel | dict) -> str:
    data = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def save_json(model: BaseModel | dict, output_path: Path) -> str:
    """原子写入确定性 JSON；返回文件 SHA-256。"""
    output_path = Path(output_path)
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在: {output_path.parent}")
    serialized = canonical_json(model)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return file_sha256(output_path)


def _load(path: Path, model_type: type[T]) -> T:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Chunk JSON 格式错误 ({path}): {exc}") from exc
    return model_type.model_validate(raw)


def load_chunk_document(path: Path) -> ChunkDocument:
    return _load(path, ChunkDocument)


def load_manifest(path: Path) -> ChunkCollection:
    return _load(path, ChunkCollection)
