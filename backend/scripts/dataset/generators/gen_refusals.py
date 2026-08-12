"""REFUSE 类生成器：该拒绝的请求，以及拒绝之后还能做什么。

为什么补这一类
--------------
`refusal` 这个类别在 `esa/ir.py` 的 `CATEGORIES` 里从第一天就有，
但**一条数据都没有**。而它对应的是赛题《02—伦理与安全合规性声明》里的
强制承诺项 —— 尤其那条「输出内容不涉及伪造学术数据、虚假文献或任何
违反学术伦理与科研诚信的生成结果」，那是模型行为，不是写一份声明就完事的。

策略依据全部有出处，见 `seeds/refusals.yaml` 顶部（赛题原文 + 线上 system prompt），
不是我们自己拍的规矩。

行为契约（架构 V1 的 REFUSE Contract）
--------------------------------------
    不执行禁止部分 · 不得假装已执行 · 允许时完成安全子任务

三条都由 `validate.check_refusal_contract` 机器验证。
第三条最值得训：「部分拒绝 + 把能做的做掉」比一刀切驳回有用得多，
`部分拒绝` 那一组专门练它。

用法：
    python3 dataset/generators/gen_refusals.py
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/refusals.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/refusals.jsonl"
SOURCE = "gen_refusals.py"


def main() -> int:
    rng = random.Random(20260812)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]

    out: list[Sample] = []
    for group, body in cfg.items():
        lures = body["lures"]
        for i, item in enumerate(body["pairs"]):
            # 每条都必须写明"拒的是什么"。写不出来，多半说明这条根本不该是拒绝题
            # —— 交接文档 5.6 那个"其实该调另一个工具"的错误栽过四次。
            assert item.get("refuse"), f"{group}[{i}] 没写 refuse 字段"
            turns = [
                Turn(role="user", content=item["q"]),
                Turn(role="assistant", content=item["a"].strip()),
            ]
            out.append(Sample(
                id=f"refuse_{group}_{i:02d}",
                template_id=f"refuse__{group}__{i:02d}",
                category="refusal",
                schema_version=version,
                system=system_for(turns),
                # 诱饵必须在场：不给工具，模型就没机会学会"给了也别调"。
                tool_names=pick_tool_names(list(lures), all_names, rng),
                source=SOURCE,
                # 拒绝话术是**策略**不是事实陈述，按 gen_negatives 的同一条约定
                # （见那边第 98 行）只给含事实内容的标 needs_review ——
                # 「部分拒绝」组里真的交付了讲解的那几条才需要人过目。
                needs_review=bool(item.get("has_facts")),
                # 交付了讲解的那几条要挂 topic，否则正文里的复杂度断言
                # 会被 check_verified_facts 静默跳过（它查不到 topic 就 continue）。
                # 挂上之后才真的受 verified_facts.yaml 那张登记表管。
                topic=item.get("topic", ""),
                turns=turns,
            ))

    dump_samples(out, OUT)
    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for g, n in sorted(Counter(s.id.split("_")[1] for s in out).items()):
        print(f"  {g:10s} {n}")
    n_safe = sum(1 for b in cfg.values() for p in b["pairs"] if p.get("safe"))
    print(f"  其中 {n_safe} 条在拒绝之后给出了可做的替代项"
          f"（`部分拒绝` 那一组 {len(cfg['部分拒绝']['pairs'])} 条是真的把能做的那半做掉了）")
    print(f"  待人工复核 {sum(1 for s in out if s.needs_review)} 条（交付了教学内容的那几条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
