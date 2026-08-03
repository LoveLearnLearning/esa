# backend/agent/DocIR/io/__init__.py

"""

这个文件干什么：集中导出 DocIR 文档加载、保存和 JSON Schema 生成功能。

直白点说就是：给 DocIR 的读文件、写文件和生成格式说明提供一个统一入口。
"""

from .serializer import export_json_schema, load_document, save_document

__all__ = ["export_json_schema", "load_document", "save_document"]
