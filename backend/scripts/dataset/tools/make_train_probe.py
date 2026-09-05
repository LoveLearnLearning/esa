"""把**训练侧**的不调用类样本渲染成评测格式，用来找「模型自己会犯的错」。

    python3 dataset/tools/make_train_probe.py \
        --train-ir <80269 那一版的 train_ir.jsonl> \
        --schemas  <同一版的 tool_schemas.json> \
        --out data/eval/eval_probe.jsonl

这是干什么用的
--------------
DPO 需要「模型实际给出的错误答案」当 `rejected`。而**评测集的失败不能用** ——
拿考卷上的题去训练，一是改善没有意义，二是会毁掉〇之零 里那条
「训练集 ∩ 主评测集模板 = 0」的防过拟合论据（那是我们四条论据里第二硬的一条）。

所以换个来源：**让模型在训练侧的题上失败给我们看**。这些题不在考卷上，
拿它们做 DPO 训练数据，评测集全程不被碰。

⚠️ **必须用被优化的那个模型同期的数据**（`--train-ir` / `--schemas` 都要）。
80269 见到的是 23 个工具那一版；拿现在本机这版（26 个）渲染，
等于在一个它没见过的工具表下量它的行为，是另一个混淆。

三道闸门（都在下面实现）
------------------------
1. **与主评测集、补充集的模板交集必须为 0** —— 这正是本文件存在的理由，
   所以要当场验，不能"按说应该是 0"。
2. **`needs_review` 的样本一律排除** —— 它们的参考答案没人审过，
   而这些答案会成为 DPO 的 `chosen`。拿没审过的答案当优化目标，
   就是把没人看过的台词钉成"正确"。
3. **渲染出来的工具名必须都在 schema 里** —— 跨版本渲染时这条会先炸，
   而不是产出一份工具表对不上的题。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.evalset import to_questions  # noqa: E402
from esa.ir import load_samples, load_schemas, schemas_by_name  # noqa: E402
from esa.split import group_split  # noqa: E402

NO_CALL = ("hard_negative", "clarify", "refusal")


def template_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out.add(rec.get("gold", {}).get("template_id", ""))
    return out


def pick_capped(samples: list, cap: int) -> list:
    """每个类别最多取 `cap` 条，**按模板轮转**取。

    为什么不是"按 id 排序取前 N"
    ----------------------------
    id 通常带模板前缀，排序取前 N 会把名次靠前的那一两个模板取满，
    后面的模板一条都取不到 —— 于是这一类的分数由一两个模板决定。
    本项目已经量过这个后果：FPR 分母的最大模板占比曾高达 **94.6%**（5.27）。

    轮转取样让每个模板都先拿到一条，再拿第二条，模板覆盖最大化。

    确定性：模板按 id 排序、模板内样本按 id 排序，全程不依赖 set 迭代顺序
    （评测集就因为迭代 set 出过"内容一样、字节不同"，见 test_eval_scoring 那条用例）。
    """
    from collections import defaultdict  # noqa: PLC0415

    by_cat: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for s in samples:
        by_cat[s.category][s.template_id].append(s)

    out = []
    for cat in sorted(by_cat):
        tpls = [sorted(by_cat[cat][t], key=lambda x: x.id)
                for t in sorted(by_cat[cat])]
        taken, i = [], 0
        while len(taken) < cap:
            row = [g[i] for g in tpls if len(g) > i]
            if not row:
                break                      # 所有模板都取完了，不足 cap 也就到此为止
            taken.extend(row[: cap - len(taken)])
            i += 1
        out.extend(taken)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染训练侧探针集（找模型自己会犯的错）")
    ap.add_argument("--train-ir", required=True)
    ap.add_argument("--schemas", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--categories", default=",".join(NO_CALL),
                    help=f"逗号分隔，默认 {','.join(NO_CALL)}")
    ap.add_argument("--eval", help="主评测集，用于交集闸门")
    ap.add_argument("--supp", help="补充集，用于交集闸门")
    ap.add_argument("--split-seed", type=int, default=20260804,
                    help="必须与当初 esa.split 用的 seed 相同，否则 trained_on 是错的")
    ap.add_argument("--max-per-category", type=int,
                    help="每个类别最多取多少条。不给就全取。"
                         "取法是**按模板轮转**（见 pick_capped），确定性、可复现。")
    args = ap.parse_args()

    cats = {c.strip() for c in args.categories.split(",") if c.strip()}
    schemas, _ = load_schemas(args.schemas)
    by_name = schemas_by_name(schemas)
    known = set(by_name)
    print(f"schema：{len(known)} 个工具　← 必须是被优化的那个模型见过的那一版")

    samples = load_samples(args.train_ir)
    print(f"train_ir：{len(samples)} 条")

    picked, held = [], 0
    for s in samples:
        if s.category not in cats:
            continue
        if getattr(s, "needs_review", False):        # 闸门 2
            held += 1
            continue
        picked.append(s)
    print(f"入选：{len(picked)} 条（类别 {sorted(cats)}），"
          f"因 needs_review 排除 {held} 条")

    if args.max_per_category:
        before = len(picked)
        picked = pick_capped(picked, args.max_per_category)
        print(f"按每类上限 {args.max_per_category} 轮转取样：{before} → {len(picked)} 条")

    records = to_questions(picked, by_name, layer={}, fixed_layer="TRAIN_PROBE")

    # ── 每道题标上「这个模板当初训练过没有」──────────────────────────
    # 🔴 为什么非要分开：`esa.split` 把 train_ir 再切成 train 90% / val 5% / test 5%，
    # 所以探针集里混着两种题，而它们说的是**完全不同**的两件事：
    #
    #   trained_on=True  的失败 = **拟合不了**。样本就在训练集里，模型还是答错 ——
    #                              再补同族样本大概率无效（④-2 补 9 条没扳动就是这个形状），
    #                              该换的是目标函数（DPO 能压低错答案，SFT 只能抬高对答案）。
    #   trained_on=False 的失败 = **泛化不到**。这类补数据是有用的。
    #
    # 不分开的话，两种失败在报表里长得一模一样，而它们指向相反的下一步。
    #
    # ⚠️ 这里自己复现切分，而不是去读 `data/out/` —— 训练记录里不带 id
    # （`to_sharegpt` 只输出 conversations/system/tools），对不上账。
    # 同一份 train_ir + 同一个 seed 必然得到同一个切分，前提是 seed 没写错，
    # 所以下面把 seed 和三个桶的大小都印出来供人核对。
    buckets = group_split(samples, seed=args.split_seed)
    trained_tpls = {s.template_id for s in buckets["train"]}
    print(f"复现切分（seed={args.split_seed}）："
          + "、".join(f"{k} {len(v)} 条" for k, v in buckets.items()))
    for r in records:
        r["gold"]["trained_on"] = r["gold"]["template_id"] in trained_tpls

    # ── 闸门 1：与两套评测集零交集 ────────────────────────────────────
    probe_tids = {r["gold"]["template_id"] for r in records}
    for label, path in (("主评测集", args.eval), ("补充集", args.supp)):
        if not path:
            print(f"⚠️ 没给 --{'eval' if label == '主评测集' else 'supp'}，"
                  f"跳过与{label}的交集检查 —— 这道闸门正是本文件存在的理由，别跳。")
            continue
        overlap = probe_tids & template_ids(Path(path))
        if overlap:
            sys.exit(
                f"❌ 闸门1：探针集与{label}有 {len(overlap)} 个模板重合，拒绝落盘。\n"
                f"   {sorted(overlap)[:10]}\n"
                "   —— 用它训练就等于在考卷上训练，〇之零 那条防过拟合论据会作废。"
            )
        print(f"✅ 闸门1：与{label}模板交集 0")

    # ── 闸门 3：工具名都在 schema 里 ─────────────────────────────────
    bad = set()
    for r in records:
        for t in json.loads(r["tools"]):
            name = (t.get("function", t))["name"]
            if name not in known:
                bad.add(name)
    if bad:
        sys.exit(
            f"❌ 闸门3：渲染出的工具不在这份 schema 里：{sorted(bad)}\n"
            "   —— 多半是 --train-ir 和 --schemas 不是同一版。"
        )
    print(f"✅ 闸门3：{len(records)} 道题的工具名都在 schema 里")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    out.write_text(body, encoding="utf-8")

    # 🔴 旁边落一份来源元信息。这份探针集是从**某一版**训练数据渲染的，
    # 而文件名里看不出是哪一版 —— 本项目已经因为「产物看不出来源」栽过多次
    # （5.25 的 meta 与数据脱节、5.40 的目录被整体替换）。
    # 谁的 adapter 就得配谁那一版的探针集，这份 meta 就是那张对账单。
    import hashlib  # noqa: PLC0415
    meta = {
        "note": "训练侧探针集，**不是评测集**；数字不得写进任何报告。",
        # 🔴 探针集**绑定某一版模型**，而文件名里看不出这一点。
        # 拿 A 版的探针集去探 B 版模型，量的是另一个东西，且不会有任何报错。
        "_warning": (
            f"本探针集由 {Path(args.train_ir).name} + {Path(args.schemas).name}"
            f"（{len(known)} 个工具）渲染，**只能用于探这一版同期的模型**。"
            "换模型必须用那个模型同期的数据重新渲染。"
        ),
        "generated_by": "dataset/tools/make_train_probe.py",
        "fingerprint": f"{hashlib.sha256(body.encode()).hexdigest()[:16]}#{len(records)}",
        # ⚠️ 只记**文件名 + 哈希**，不记路径 —— 发布目录的泄漏扫描会查本机绝对路径，
        # 而这份 meta 是要跟着数据集一起发出去的。哈希才是对账用的东西，路径不是。
        "source_train_ir": Path(args.train_ir).name,
        "source_train_ir_sha256_16": hashlib.sha256(
            Path(args.train_ir).read_bytes()).hexdigest()[:16],
        "source_schemas": Path(args.schemas).name,
        "source_schemas_sha256_16": hashlib.sha256(
            Path(args.schemas).read_bytes()).hexdigest()[:16],
        "source_schemas_tools": len(known),
        "categories": sorted(cats),
        "excluded_needs_review": held,
        "questions": len(records),
        "templates": len(probe_tids),
        # 训练过 / 留出，两种失败指向相反的下一步，元信息里必须分开记
        "trained_on": sum(1 for r in records if r["gold"]["trained_on"]),
        "held_out": sum(1 for r in records if not r["gold"]["trained_on"]),
        "split_seed": args.split_seed,
        # 2026-09-03 补：这个参数会改变题目集合，而它原本一个字都没进 meta。
        # 指纹变了能看出「不是同一份」，但看不出「为什么不是」——
        # 而这份 meta 自称是对账单，那就得能对上账。
        "max_per_category": args.max_per_category,
    }
    meta_path = out.parent / (out.stem + "_meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(f"元信息 → {meta_path}")

    by_action: dict[str, int] = {}
    for r in records:
        by_action[r["gold"]["expected_action"]] = by_action.get(
            r["gold"]["expected_action"], 0) + 1
    n_trained = sum(1 for r in records if r["gold"]["trained_on"])
    print(f"\n→ {out}　{len(records)} 道题 / {len(probe_tids)} 个模板")
    print(f"   其中训练过 {n_trained} 道、留出 {len(records) - n_trained} 道"
          f"　← 两种失败指向相反的下一步，别混着读")
    for k, n in sorted(by_action.items()):
        print(f"   {k:24s}{n:4d}")
    print("\n下一步：用被优化的那个模型对这份跑一次推理（`--suite probe`），"
          "再用 make_dpo_pairs.py 从失败里挑偏好对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
