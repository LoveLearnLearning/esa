# backend/agent/rag/fingerprints.py

"""

这个文件干什么：为 RAG 配置生成稳定指纹。

直白点说就是：把配置内容算成稳定哈希，方便判断两次运行用的是不是同一套设置。

为 RAG 配置生成稳定指纹。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Protocol


class Fingerprinted(Protocol):
    """能够声明稳定配置指纹的后端。"""

    @property
    def configuration_fingerprint(self) -> str:
        """返回会影响后端输出或索引结构的配置指纹。"""

        ...


def configuration_sha256(payload: object) -> str:
    """对 JSON 可序列化配置计算稳定 SHA-256。"""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def backend_fingerprint(backend: object, fallback: Mapping[str, object]) -> str:
    """优先读取后端显式指纹，否则使用调用方给出的稳定配置。"""

    fingerprint = getattr(backend, "configuration_fingerprint", None)
    if isinstance(fingerprint, str) and fingerprint:
        return fingerprint
    return configuration_sha256(dict(fallback))
