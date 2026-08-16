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
- VLM 只补充仍缺少机器可读语义的视觉元素；MinerU 已输出 HTML 的表格、
  已输出 LaTeX 的公式和已有结构化内容的图表不会重复请求辅助模型。
- 视觉补全先经过 MM 内部的确定性路由和无标签准入：普通 VLM 描述只能作为
  `VLM_DERIVED` 的不可逐字引用文本；没有独立证据的节点、边、方向和坐标等
  结构化结果会进入 `review`，不会自动写入 DocIR。
- 路由、候选、证据和 `accept/review/reject` 决策使用
  `VisualEnrichmentRequest`、`VisualEnrichmentCandidate` 和
  `VisualEnrichmentOutcome` 契约；当前阶段不引入额外视觉模型或几何依赖。
- 工件保存在 `MM_ARTIFACT_ROOT`（默认 `runtime/mm`），以源文件和 pipeline
  指纹隔离；索引只保存在 `PreparedAttachment` 的进程内生命周期中。
- 每个文件独立路由。Web 层已通过
  `POST /conversations/{conversation_id}/attachments` 接入前端，并在消息请求的
  `attachment_ids` 中选择本轮上下文；课程表导入也会优先复用这条 DocIR 管线。

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
