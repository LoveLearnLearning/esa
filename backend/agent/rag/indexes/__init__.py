# backend/agent/rag/indexes/__init__.py

"""

这个文件干什么：检索索引公共入口。

直白点说就是：把可用的索引实现和统一异常集中导出。

检索索引公共入口。
"""

from .errors import CollectionNotFound, IndexGenerationConflict, IndexUnavailable
from .qdrant import QdrantIndex
from .personal_qdrant import PersonalQdrantIndex
from .reference import ReferenceIndex, reference_tokens

__all__ = [
    "CollectionNotFound",
    "IndexGenerationConflict",
    "IndexUnavailable",
    "QdrantIndex",
    "PersonalQdrantIndex",
    "ReferenceIndex",
    "reference_tokens",
]
