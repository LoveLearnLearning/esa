# backend/agent/DocIR/io/serializer.py

"""

这个文件干什么：V0.2 确定性 JSON 读写与 Schema 导出。

直白点说就是：负责把 DocIR 稳定地存成 JSON、从 JSON 读回来，并生成机器可校验的 Schema。

V0.2 确定性 JSON 读写与 Schema 导出。
"""

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from ..core.document import Document


def _target_parent(path: Path) -> Path:
    parent = path.parent
    if not parent.exists():
        raise FileNotFoundError(f"DocIR 输出目录不存在: {parent}")
    if not parent.is_dir():
        raise NotADirectoryError(f"DocIR 输出目录不是目录: {parent}")
    return parent


def save_document(document: Document, output_path: Path) -> None:
    """原子保存一个已通过全局校验的 V0.2 快照。"""
    output_path = Path(output_path)
    parent = _target_parent(output_path)
    document = Document.model_validate(document.model_dump(mode="python"))
    serialized = json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=parent)
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


def load_document(input_path: Path) -> Document:
    """只加载 schema_version=0.2；V0.1 必须显式迁移。"""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"DocIR 文件不存在: {input_path}")
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"DocIR JSON 格式错误 ({input_path}): {exc}") from exc
    if data.get("schema_version") != "0.2":
        raise ValueError("load_document 只接受 DocIR 0.2；旧版本请使用显式迁移入口")
    try:
        return Document.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"DocIR 数据验证失败 ({input_path}): {exc}") from exc


def export_json_schema(output_path: Path) -> None:
    """导出 Pydantic 生成的 Draft 2020-12 兼容 JSON Schema。"""
    _target_parent(Path(output_path))
    Path(output_path).write_text(
        json.dumps(Document.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
