# MM 附件摄取

`backend.agent.mm` 把单个用户附件转换成可直接注入或可检索的独立上下文：

```text
source → MinerU → DocIR → VLM descriptions → final DocIR → Markdown
                                                        ├─ ≤ token limit: direct
                                                        └─ > token limit: in-memory RAG
```

- 默认直注上限是 `MM_DIRECT_CONTEXT_TOKEN_LIMIT=48000`，由
  `MM_TOKENIZER_PATH` 指向的真实 tokenizer 精确计数。
- VLM 使用 OpenAI-compatible `/chat/completions`，配置为 `MM_VLM_BASE_URL`、
  `MM_VLM_MODEL` 和可选的 `MM_VLM_API_KEY`。
- 工件保存在 `MM_ARTIFACT_ROOT`（默认 `runtime/mm`），以源文件和 pipeline
  指纹隔离；索引只保存在 `PreparedAttachment` 的进程内生命周期中。
- 每个文件独立路由。模块不负责 Web 上传、会话权限或 Agent 生命周期。

```python
from pathlib import Path

from backend.agent.mm import MultimodalIngestionService

service = MultimodalIngestionService()
attachment = await service.prepare_file(Path("notes.pdf"))
context_or_response = attachment.context_for("这份资料的网络拓扑是什么？")
```

命令行：

```bash
python -m backend.agent.mm.cli ingest notes.pdf diagram.png
python -m backend.agent.mm.cli query notes.pdf --query "总结关键结论"
```

