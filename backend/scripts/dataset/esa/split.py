# backend/scripts/dataset/esa/split.py

"""按 template_id 整组切分，并渲染成 LLaMA-Factory 要的 ShareGPT jsonl。

必须整组切分：同一个模板产出的 `计算 sqrt(16)` / `sqrt(25)` / `sqrt(36)` 如果被随机
拆到 train 和 test，测试集就直接泄漏了，评测数字会好看得没有意义。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from .ir import Sample, load_samples, load_schemas, schemas_by_name
from .paths import in_dataset
from .render import to_sharegpt
from . import review


def group_split(
    samples: list[Sample],
    ratios: tuple[float, float, float] = (0.9, 0.05, 0.05),
    seed: int = 20260804,
) -> dict[str, list[Sample]]:
    """按 template_id 整组切分，并**按 category 分层**。

    只按 template 切会出问题：模板数少而每组样本多时，validation 很可能整个只落到
    一两个模板上，等于只测了一种行为。分层保证每个 category 在三个集合里都有代表，
    同时仍然不拆开任何一个 template（否则测试集直接泄漏）。
    """
    groups: dict[str, list[Sample]] = defaultdict(list)
    for s in samples:
        groups[s.template_id].append(s)

    by_cat: dict[str, list[str]] = defaultdict(list)
    for tpl, items in groups.items():
        by_cat[items[0].category].append(tpl)

    rng = random.Random(seed)
    out: dict[str, list[Sample]] = {"train": [], "validation": [], "test": []}

    for cat in sorted(by_cat):
        keys = sorted(by_cat[cat])
        rng.shuffle(keys)
        cat_total = sum(len(groups[k]) for k in keys)
        want_train = cat_total * ratios[0]
        want_val = cat_total * ratios[1]

        n = 0
        for k in keys:
            if n < want_train:
                bucket = "train"
            elif n < want_train + want_val:
                bucket = "validation"
            else:
                bucket = "test"
            out[bucket].extend(groups[k])
            n += len(groups[k])

    return out


def split_warnings(split: dict[str, list[Sample]]) -> list[str]:
    """切分质量告警：某个类别在 val/test 里缺席就说明评测覆盖不全。"""
    cats = {s.category for s in split["train"]} | {s.category for s in split["validation"]} | {
        s.category for s in split["test"]
    }
    out = []
    for bucket in ("validation", "test"):
        present = {s.category for s in split[bucket]}
        for missing in sorted(cats - present):
            out.append(f"{bucket} 里没有 {missing} 类样本，该行为无法被评测到")
    return out


def assert_no_leak(split: dict[str, list[Sample]]) -> None:
    """处理 `assert_no_leak` 相关逻辑。"""
    tpl = {k: {s.template_id for s in v} for k, v in split.items()}
    for a in tpl:
        for b in tpl:
            if a < b and (shared := tpl[a] & tpl[b]):
                raise AssertionError(f"{a} 与 {b} 共享 template_id，存在泄漏: {sorted(shared)[:5]}")


DATASET_INFO_KEYS = {"train": "esa_agent_train", "validation": "esa_agent_validation", "test": "esa_agent_test"}


def write_outputs(split: dict[str, list[Sample]], by_name, out_dir: Path) -> dict:
    """写入 `outputs` 相关数据。

    Args:
        split: dict[str, list[Sample]] => `split` 参数。
        by_name: object => `by_name` 参数。
        out_dir: Path => `out_dir` 参数。

    Returns:
        dict => 处理结果。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    info = {}
    for bucket, samples in split.items():
        fname = f"{DATASET_INFO_KEYS[bucket]}.jsonl"
        with (out_dir / fname).open("w", encoding="utf-8") as fh:
            for s in samples:
                fh.write(json.dumps(to_sharegpt(s, by_name), ensure_ascii=False) + "\n")
        # columns 必须显式声明 system，否则顶层 system 字段会被静默丢弃
        # （src/llamafactory/data/parser.py:81-84）
        info[DATASET_INFO_KEYS[bucket]] = {
            "file_name": fname,
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "system": "system", "tools": "tools"},
        }
    (out_dir / "dataset_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return info


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    ap = argparse.ArgumentParser(description="切分并渲染训练数据")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--schemas", default=str(in_dataset("schemas/tool_schemas.json")))
    ap.add_argument("--out", default=str(in_dataset("data/out")))
    ap.add_argument("--seed", type=int, default=20260804)
    args = ap.parse_args(argv)

    schemas, _ = load_schemas(args.schemas)
    by_name = schemas_by_name(schemas)

    samples: list[Sample] = []
    for f in args.files:
        samples.extend(load_samples(f))

    # 未复核样本本该在 evalset.build() 里就被挡住（组长 2026-08-11 要求）。
    # 这里再拦一道，是因为 split.py 也能直接吃 data/ir/*.jsonl ——
    # 那条路径绕过了 evalset，绕过去就没有任何东西拦得住，而且不会报错。
    #
    # ⚠️ 判据必须走 review.pending()，不能自己写 `if s.needs_review`。
    # 后者不认 seeds/reviewed.yaml，于是审完并正式登记过的样本在这里仍会被拦，
    # 而报错还会让人去"把 needs_review 关掉"—— 那个字段在生成器里按组写死，关不掉。
    # 这道拦截是 fail closed（挡多不挡少），所以坏数据进不来，
    # 但它会把一个已经做完的动作判成没做完，且给出一条做不到的指示。
    #
    # 这里**不调** assert_no_stale()：split 拿到的经常是子集
    # （正常入口就是 evalset 产出的 train_ir.jsonl），而台账登记的样本
    # 有一部分落在评测集里，对子集查存在性会误报"这个 id 不存在"。
    unreviewed = review.pending(samples)
    if unreviewed:
        raise SystemExit(
            f"输入里有 {len(unreviewed)} 条未经人工复核的样本，不能进训练集："
            f"{[s.id for s in unreviewed[:5]]}…\n"
            "正确入口是先跑 `python3 -m esa.evalset`，再切它产出的 "
            "dataset/data/eval/train_ir.jsonl。\n"
            "清单见 dataset/docs/待人工复核.md。审完**逐条**登记进 "
            "dataset/seeds/reviewed.yaml（要签名字），登记过的就不再拦。"
        )

    split = group_split(samples, seed=args.seed)
    assert_no_leak(split)
    write_outputs(split, by_name, Path(args.out))

    from collections import Counter

    for bucket, items in split.items():
        cats = Counter(s.category for s in items)
        detail = " ".join(f"{c}={n}" for c, n in sorted(cats.items()))
        print(f"{bucket:11s} {len(items):5d} 条 / {len({s.template_id for s in items}):3d} 个模板  {detail}")

    warnings = split_warnings(split)
    if warnings:
        print()
        for w in warnings:
            print(f"⚠️  {w}")
    print(f"\n已写入 {args.out}/ （含 dataset_info.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
