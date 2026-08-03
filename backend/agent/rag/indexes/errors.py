# backend/agent/rag/indexes/errors.py

"""

这个文件干什么：索引后端共享异常。

直白点说就是：统一定义索引连不上、集合不存在或代次冲突时抛出的错误。

索引后端共享异常。
"""


class IndexUnavailable(RuntimeError):
    """表示索引服务连接、超时或响应解析故障。"""


class CollectionNotFound(IndexUnavailable):
    """表示指定 Qdrant Collection 尚未创建。"""


class IndexGenerationConflict(RuntimeError):
    """表示 Collection 中已有其他或过量索引代次数据。"""
