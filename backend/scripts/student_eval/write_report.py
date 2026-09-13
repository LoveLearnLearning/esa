from __future__ import annotations
import argparse
import json
from .common import run_dir

def pct(x):
    return f"{x*100:.1f}%"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    out = run_dir(args.run_id)
    d = json.loads((out / "diagnosis_metrics.json").read_text(encoding="utf-8"))
    a_path = out / "ablation_metrics.json"
    a = json.loads(a_path.read_text(encoding="utf-8")) if a_path.exists() else None

    text = f"""# 认知约束虚拟学生补充验证结果摘要

> Run ID: `{args.run_id}`

## 1. 实验定位

项目已有 6 名真实目标用户完成试用。本实验不将虚拟学生计入真实用户数量，而是在真人样本规模有限的条件下，对 ESA 的学情诊断与个性化机制进行可控、可重复的补充机制验证。

## 2. 轻量化实验设计

实验基于 ESA 当前真实“数据结构”知识图谱，固定选取 6 个知识点：线性表、栈、队列、图、深度优先搜索、广度优先搜索。构造 30 个具有隐藏认知状态的虚拟学生，其中基础薄弱、中等和基础较强各 10 个。

虚拟学生采用 FAST Controlled Simulation：掌握、部分掌握、薄弱及典型误区由固定 Profile 和确定性规则控制，不启动额外本地 LLM，不让强语言模型自由决定“学生会不会”。Experiment A 使用临时 SQLite 与真实 LearningStateService / MasteryStore / KnowledgeGraphStore 完成，因此新增 GPU 推理为 0。

## 3. 学情诊断结果

- Precision：{pct(d["overall"]["precision"])}
- Recall：{pct(d["overall"]["recall"])}
- F1：{pct(d["overall"]["f1"])}
- Exact Set Match：{pct(d["overall"]["exact_set_match_rate"])}

分层 F1：

- 基础薄弱组：{pct(d["weak"]["f1"])}
- 中等组：{pct(d["medium"]["f1"])}
- 基础较强组：{pct(d["strong"]["f1"])}

这些指标比较的是预设隐藏薄弱知识点与 ESA Student Model 根据学习证据形成的 `weak` 状态，不依赖 LLM Judge。
"""
    if a:
        text += f"""
## 4. 个性化消融结果

从虚拟学生中分层抽取 {a["n"]} 个代表样本。对每个学生分别建立：

- Full ESA：具有相同诊断阶段产生的学习历史；
- No-Personalization：使用相同 ESA 模型、知识图谱、工具和问题，但账号没有历史学习证据。

采用盲化 A/B rubric 评价后：

- Full ESA 平均个性化评分：{a["full_mean"]}/10
- No-Personalization 平均评分：{a["baseline_mean"]}/10
- 平均配对差值：{a["paired_mean_difference"]:+.3f}
- Full ESA 胜 / 平 / 负：{a["full_wins"]} / {a["ties"]} / {a["baseline_wins"]}
"""
    else:
        text += """
## 4. 个性化消融结果

尚未写入 `ablation_metrics.json`。完成盲评后运行 `score_ablation.py` 和本脚本即可自动补齐。
"""

    text += """
## 5. 边界与局限性

虚拟学生行为由受控认知状态和确定性回答策略产生，不能完整模拟真实学生的情绪、动机、长期遗忘及复杂学习行为。因此本实验只用于验证系统机制的可控性、覆盖性和稳定性，不将结果外推为真实学生长期学习增益。

作品的真实用户认可度仍以 6 名真实目标用户试用问卷与实际使用记录为依据。虚拟学生结果与真人结果在报告中严格分开呈现。
"""
    (out / "06_AI补充验证_结果摘要.md").write_text(text, encoding="utf-8")
    print(out / "06_AI补充验证_结果摘要.md")

if __name__ == "__main__":
    main()
