"""改写表：把「末轮回答的改写」与「生成器」解耦。

为什么要单独一层
----------------
`data/ir/*.jsonl` 是**生成器的产物**。把 SDFT 的改写直接写进去，
下一次重生成就抹掉了 —— 而重生成是每次跟上游都要做的事（本项目 8 月做了三轮）。
那样每跟一次上游，就要重付一次改写的机时和人工复核。

而改写也**不能塞回种子**：种子里那些回答是带参数的模板
（`{kp}` / `{mastery}` / `{count}`），238 段各不相同的散文塞不回去；
硬要模板化就等于把多样性又压回常量，那正是 5.61 在骂的事。

于是分成两层：

    data/rewrites/*.jsonl   id → {ref, rewritten}     ← 一等数据，重生成不碰
    esa/ir.dump_samples()   渲染落盘前查一次表         ← 十个生成器共用的唯一出口

🔴 **`ref` 必须逐字节对上才替换。** 数据换了版（工具增删、提示词改写、
话术重排）之后，同一个 id 的原文很可能已经不是当初被改写的那一句 ——
那时**跳过并喊出来**，而不是把一段对不上号的散文安到别的样本头上。
这条是 5.59 的形状：产物和数据是配对的，`git pull` / 重生成会静默拆散它们。

⚠️ 一条没被覆盖的：如果重生成把某个原本在训练池的样本挪进了考卷，
这里照样会替换它。**那道闸门在 `tools/apply_sdft.py --verify`**
（跑在 `esa.evalset` 之后，查改写过的 id 有没有出现在 eval / eval_supp 里）。
放在这里查不了 —— 落盘时切分还没发生。
"""

from __future__ import annotations

import json

from esa.paths import in_dataset

REWRITES_DIR = in_dataset("data", "rewrites")


def load_table() -> dict[str, dict]:
    """`data/rewrites/*.jsonl` → {id: {ref, rewritten, source}}。

    没有这个目录就返回空表 —— 改写是可选的一层，不装它整条流水线照跑。
    """
    if not REWRITES_DIR.is_dir():
        return {}
    table: dict[str, dict] = {}
    for f in sorted(REWRITES_DIR.glob("*.jsonl")):
        for line_no, line in enumerate(f.open(encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            for k in ("id", "ref", "rewritten"):
                if not r.get(k):
                    raise SystemExit(f"❌ {f.name}:{line_no} 缺 {k}")
            if r["id"] in table:
                raise SystemExit(
                    f"❌ {f.name}:{line_no} id 重复：{r['id']}\n"
                    "   同一条样本被改写了两次，取哪一份说不清 —— 先合并再用。")
            r.setdefault("source", f.stem)
            table[r["id"]] = r
    return table


def apply_to(samples: list, table: dict[str, dict] | None = None) -> dict[str, int]:
    """就地替换末轮 assistant 的正文。返回计数，**调用方必须把它印出来**。

    `samples` 是 `esa.ir.Sample` 列表（只要有 `.id` 和 `.turns` 就行）。
    """
    if table is None:
        table = load_table()
    n = {"applied": 0, "stale": 0}
    if not table:
        return n
    for s in samples:
        r = table.get(getattr(s, "id", None))
        if not r:
            continue
        turns = s.turns
        if not turns or turns[-1].role != "assistant":
            continue
        if turns[-1].content != r["ref"]:
            # 数据换版了，这条改写已经不对应这个样本 —— 跳过，别硬安上去。
            n["stale"] += 1
            continue
        turns[-1].content = r["rewritten"]
        n["applied"] += 1
    return n
