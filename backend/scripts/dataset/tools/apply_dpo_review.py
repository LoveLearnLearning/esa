"""把人工复核结论套到 `make_dpo_pairs.py` 的产物上，输出 LLaMA-Factory 能吃的 DPO 数据。

    python3 tools/apply_dpo_review.py \
        --pairs   ~/dpo_pairs_UNREVIEWED_84232.jsonl \
        --review  data/dpo/review_84232.json \
        --out     data/dpo/dpo_84232.jsonl

🔴 为什么必须有这一步：sharegpt 下 chosen/rejected 是字符串会被**静默吞掉**
------------------------------------------------------------------------
`llamafactory/data/converter.py` 的 pairwise 分支要求两者都是 **dict**：

    elif (self.dataset_attr.ranking
          and isinstance(example[chosen], dict)
          and isinstance(example[rejected], dict)):   # ← 字符串在这里被跳过
        ...
    else:                                             # normal example
        prompt   = aligned_messages[:-1]
        response = aligned_messages[-1:]

不满足就落进 `else`，**一句警告都不打**，chosen/rejected 双双丢弃，改拿
`conversations` 当普通 SFT 训。而我们的 `conversations` 只留了一条 human ——
于是 prompt 是空的、response 是用户那句话。训练照跑，学的全是垃圾。

所以本工具做两件事，缺一不可：
  1. 套用复核结论（只留 keep）
  2. 把 chosen/rejected 转成 {"from": "gpt", "value": ...}

两道闸门（都是 fail-closed，本项目栽过太多次 fail-open）
--------------------------------------------------------
1. **偏好对里每一条都必须有裁定**。漏判的不是"默认保留"也不是"默认丢弃"，是**停**。
2. **裁定表里不许有死条目**。指向不存在的 id，说明复核的是另一批数据。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ASSISTANT_TAG = "gpt"   # llamafactory/data/parser.py: assistant_tag 默认值
ROLE_TAG = "from"
CONTENT_TAG = "value"


def main() -> int:
    ap = argparse.ArgumentParser(description="套用 DPO 偏好对的人工复核结论")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    raw = Path(args.pairs).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in raw if line.strip()]
    verdicts = json.loads(Path(args.review).read_text(encoding="utf-8"))["verdicts"]
    ids = [r["_id"] for r in rows]

    # ── 闸门 1：没有裁定的一律停 ──────────────────────────────────────
    missing = [i for i in ids if i not in verdicts]
    if missing:
        sys.exit(f"❌ 闸门1：这 {len(missing)} 条没有复核裁定，拒绝输出：\n   " +
                 "\n   ".join(missing) +
                 "\n   —— 未复核的对不能进训练数据，补进 review 文件再跑。")

    # ── 闸门 2：裁定表不许有死条目 ───────────────────────────────────
    stale = [i for i in verdicts if i not in ids]
    if stale:
        sys.exit(f"❌ 闸门2：裁定表里这些 id 在偏好对里不存在：{stale}\n"
                 "   —— 说明复核的是另一批数据，或者 pairs 文件换过了。")

    kept, dropped = [], []
    for r in rows:
        verdict, why = verdicts[r["_id"]]
        if verdict != "keep":
            dropped.append((r["_id"], why))
            continue
        convs = [t for t in r["conversations"] if t.get(ROLE_TAG) in ("human", "user")]
        if not convs:
            sys.exit(f"❌ {r['_id']} 没有用户轮，prompt 会是空的。")
        out = {k: v for k, v in r.items() if k not in ("chosen", "rejected")}
        out["conversations"] = convs
        # 🔴 这两行就是上面那段注释的全部意义所在
        out["chosen"] = {ROLE_TAG: ASSISTANT_TAG, CONTENT_TAG: r["chosen"]}
        out["rejected"] = {ROLE_TAG: ASSISTANT_TAG, CONTENT_TAG: r["rejected"]}
        kept.append(out)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept),
                        encoding="utf-8")

    print(f"✅ 闸门1/2 通过：{len(rows)} 条全部有裁定，裁定表无死条目")
    print(f"踢掉 {len(dropped)} 条：")
    for i, why in dropped:
        print(f"   {i}　{why}")
    print(f"\n→ {out_path}　{len(kept)} 对")
    print("\n📌 dataset_info.json 里必须写 \"ranking\": true —— 它默认 False，"
          "不写的话 pairwise 分支根本不会进。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
