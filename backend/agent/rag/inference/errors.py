# backend/agent/rag/inference/errors.py

"""

这个文件干什么：推理后端共享异常。

直白点说就是：统一表示本地模型服务不可用或返回内容不合法。

推理后端共享异常。
"""


class InferenceUnavailable(RuntimeError):
    """本地模型服务不可达、依赖缺失或响应无效。"""
