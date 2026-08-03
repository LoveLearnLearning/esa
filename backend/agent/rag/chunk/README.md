# RAG 内部独立 Chunk 子模块

依赖方向固定为 `DocIR ← rag.chunk ← RAG 检索链`。本子模块读取 DocIR V0.2，生成可复用的 ChunkDocument 和 ChunkCollection；不导入 RAG 的召回、融合、重排或服务模块，也不调用模型、Qdrant 或 VLM。

默认策略：正文目标 800 字、硬上限 1200 字、相邻普通 Chunk 重叠一个完整元素；表格按连续行组切分并重复表头，数据行不重叠；无文字 Figure 不生成占位 Chunk。

模块职责：

- `models.py`：稳定 Chunk、Evidence、Document 和 Collection 契约。
- `text.py`：保留原文偏移的边界切分。
- `table.py`：HTML 表格解析、表头识别和连续行分组。
- `fragments.py`：Element 文本选择、资产与位置映射、证据生成。
- `builder.py`：章节路径、Chunk 草稿分组和最终契约组装。
- `serializer.py`：确定性、原子 JSON 读写。
- `stats.py`：Collection 统计。
- `cli.py`：批量构建和断点复用。

构建真实语料：

```bash
python -m backend.agent.rag.chunk.cli
```

输出位于 `artifacts/chunk/collections/<collection-id>/`，逐文档保存 `chunks.json`，Collection 根目录保存 `manifest.json` 和 `stats.json`。
