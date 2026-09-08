# 技术报告评测证据说明

本目录保存技术报告第 7、8 章引用的原始模型评测产物，便于随“07—其他材料”归档。

| 文件 | 内容 |
|---|---|
| `pred_nothink_ep10_95348.jsonl` | 定版 LoRA 在 440 道主考卷上的逐题原始输出 |
| `report_nothink_ep10_95348.json` | 定版 LoRA 的逐题判分与汇总 |
| `pred_base_95431.jsonl` | 同基座模型在同一主考卷上的逐题原始输出 |
| `report_base_95431.json` | 基座模型的逐题判分与汇总 |

主考卷指纹为 `d441611fb5556b53#440`。报告第 8 章使用的真实案例 ID 为：

- `calc_000_0`
- `s002_修改参数_0020`
- `record_learning_evidence_正例_practice_0012`

注意：原始 `report_*.json` 的“拒绝命中率”字段来自自动关键词判据，不是最终人工裁定口径。正式结论必须结合仓库中的 `backend/scripts/dataset/data/eval/refusal_adjudication.json` 重新评分；技术报告与三张正式图使用人工裁定后的结果。不要直接复制原始 JSON 中的拒绝率作为最终结论。
