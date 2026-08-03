# backend/agent/rag/indexing/__init__.py

"""

这个文件干什么：索引代次构建和可重启部署契约。

直白点说就是：把建立新索引代次和保存部署信息所需的接口集中导出。

索引代次构建和可重启部署契约。
"""

from .deployment import (
    EmbeddingBackend,
    IndexDeployment,
    load_deployment,
    save_deployment,
)
from .service import IndexBuildResult, IndexGeneration, IndexingService

__all__ = [
    "EmbeddingBackend",
    "IndexBuildResult",
    "IndexDeployment",
    "IndexGeneration",
    "IndexingService",
    "load_deployment",
    "save_deployment",
]
