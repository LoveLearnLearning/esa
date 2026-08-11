"""面向单附件会话的进程内混合索引。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agent.rag.fingerprints import configuration_sha256
from backend.agent.rag.indexes.reference import ReferenceIndex


@dataclass
class InMemoryAttachmentIndex(ReferenceIndex):
    """真实 dense vector + 小规模内存 BM25；生命周期由 PreparedAttachment 管理。"""

    @property
    def configuration_fingerprint(self) -> str:
        return configuration_sha256(
            {
                "backend": "mm-in-memory-attachment-index-0.1",
                "dense": "cosine",
                "bm25": {"k1": 1.2, "b": 0.75},
                "tokenizer": "unicode-cjk-bigram-0.1",
            }
        )

