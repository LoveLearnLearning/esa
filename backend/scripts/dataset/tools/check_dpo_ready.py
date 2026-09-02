"""开跑前验一遍 DPO 数据的格式。**这道检查是为了拦一个不会报错的错误。**

    python3 tools/check_dpo_ready.py \
        --data data/dpo/dpo_84232.jsonl \
        --info data/dpo/dataset_info.json --key esa_dpo

为什么必须在开跑前验
--------------------
`llamafactory/data/processor/pairwise.py:74-78`：

    if len(examples["_prompt"][i]) % 2 != 1 or len(examples["_response"][i]) < 2:
        logger.warning_rank0("Dropped invalid example: ...")
        continue        # ← 丢一条，接着跑

而 `_response` 会不会只有 1 条，取决于 `converter.py` 的 pairwise 分支进没进；
那个分支要求 chosen/rejected 都是 **dict**，是字符串就跳过、落进 `else` 当普通样本。
两处叠起来的效果是：**格式写错时全部样本被逐条丢掉，训练在空数据上跑完、rc=0。**

所以这里用纯标准库验，不 import llamafactory —— 检查本身不能依赖被检查的那个框架，
也不该依赖它的版本（集群和本机版本不一定一致）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_COLUMNS = ("messages", "chosen", "rejected", "system", "tools")


def main() -> int:
    ap = argparse.ArgumentParser(description="DPO 数据开跑前的格式闸门")
    ap.add_argument("--data", required=True)
    ap.add_argument("--info", required=True)
    ap.add_argument("--key", required=True, help="dataset_info.json 里的数据集名")
    args = ap.parse_args()

    raw = Path(args.data).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in raw if line.strip()]
    if not rows:
        sys.exit(f"❌ {args.data} 是空的")

    def rid(r: dict, i: int) -> str:
        return r.get("_id", f"第{i + 1}行")

    bad_shape = [rid(r, i) for i, r in enumerate(rows)
                 if not (isinstance(r.get("chosen"), dict)
                         and isinstance(r.get("rejected"), dict))]
    if bad_shape:
        sys.exit("❌ 这些条的 chosen/rejected 不是 dict，会被 pairwise.py 逐条静默丢弃：\n"
                 f"   {bad_shape[:5]}\n"
                 "   正确形状：{\"from\": \"gpt\", \"value\": \"…\"}（用 apply_dpo_review.py 生成）")

    bad_tag = [rid(r, i) for i, r in enumerate(rows)
               if r["chosen"].get("from") != "gpt" or r["rejected"].get("from") != "gpt"]
    if bad_tag:
        sys.exit(f"❌ 这些条的 from 不是 gpt，converter 会报 Invalid role tag：{bad_tag[:5]}")

    empty = [rid(r, i) for i, r in enumerate(rows)
             if not str(r["chosen"].get("value", "")).strip()
             or not str(r["rejected"].get("value", "")).strip()]
    if empty:
        sys.exit(f"❌ 这些条的 chosen 或 rejected 是空的：{empty[:5]}")

    # `_prompt` 的长度必须是奇数（pairwise.py 的另一半条件），
    # 而 `_prompt` 就是 conversations —— 只留一条 human 时长度 1，合法。
    bad_conv = [rid(r, i) for i, r in enumerate(rows)
                if not r.get("conversations") or len(r["conversations"]) % 2 != 1]
    if bad_conv:
        sys.exit("❌ 这些条的 conversations 为空或轮数是偶数，会被 pairwise.py 丢弃：\n"
                 f"   {bad_conv[:5]}")

    info = json.loads(Path(args.info).read_text(encoding="utf-8"))
    if args.key not in info:
        sys.exit(f"❌ dataset_info.json 里没有 {args.key}，可选：{[k for k in info if not k.startswith('_')]}")
    spec = info[args.key]
    if spec.get("ranking") is not True:
        sys.exit("❌ ranking 不是 true。它默认 False，不写则 pairwise 分支根本不会进，\n"
                 "   chosen/rejected 被静默丢弃，改拿 conversations 当普通 SFT 训。")
    if spec.get("formatting") != "sharegpt":
        sys.exit(f"❌ formatting 是 {spec.get('formatting')!r}，本数据是 sharegpt 格式")
    cols = spec.get("columns", {})
    missing = [c for c in REQUIRED_COLUMNS if cols.get(c) is None]
    if missing:
        sys.exit(f"❌ columns 里缺 {missing}。\n"
                 "   ⚠️ system / tools 官方示例里没有，但不显式声明会被静默丢弃\n"
                 "   （parser.py:81-84），模型训练时看不见工具表。")
    if Path(spec["file_name"]).name != Path(args.data).name:
        sys.exit(f"❌ dataset_info 指向 {spec['file_name']}，而验的是 {Path(args.data).name}")

    print(f"✅ 闸门3：{len(rows)} 对格式合法（chosen/rejected 均为 dict、from=gpt、非空）")
    print(f"   ranking=true、formatting=sharegpt、columns 含 {list(REQUIRED_COLUMNS)}")
    print(f"   dataset_info 指向的正是 {Path(args.data).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
