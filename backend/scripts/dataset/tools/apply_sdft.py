"""把 SDFT 的改写产物灌进改写表 —— 🖥️ **本机跑**（`dataset/` 是唯一事实来源）。

    # 先看会灌什么，不写盘
    python3 dataset/tools/apply_sdft.py --pilot ~/Desktop/sdft/pilot_full.jsonl

    # 确认之后才写
    python3 dataset/tools/apply_sdft.py --pilot ... --apply

    # 🔴 `esa.evalset` 之后必跑：改写过的样本不许出现在考卷里
    python3 dataset/tools/apply_sdft.py --verify

为什么不直接写 `data/ir/`
------------------------
IR 是生成器的产物，下一次重生成就抹掉了 —— 而重生成是每次跟上游都要做的。
落点是 `data/rewrites/`，由 `esa/ir.dump_samples()` 在渲染时查表替换。
完整理由见 `esa/rewrites.py` 的抬头。

为什么闸门要**重跑一遍**，不信产物里存的那份
--------------------------------------------
`pilot.jsonl` 里的 `gate` 字段是**集群上那一版**脚本算的。同一个判据在两处
各算一遍，就是在等它们分叉（5.54 / 5.50）。这里一律拿本机当前的
`sdft_pilot.gate()` 重算，**存的那份只用来对照**，对不上就报出来 ——
那正好说明集群上的脚本和本机不是同一版。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sdft_pilot  # noqa: E402
from esa.rewrites import REWRITES_DIR, load_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
IR_DIR = ROOT / "dataset/data/ir"
EVAL = ROOT / "dataset/data/eval/eval.jsonl"
SUPP = ROOT / "dataset/data/eval/eval_supp.jsonl"

# 硬判据：不过就不许进表。`刚才刚刚` 不在里面 —— 它是线索不是判据（5.67）。
HARD = ("字段名", "相对时间", "忠实度", "非空", "没跑题")


def ir_by_id() -> dict[str, dict]:
    out = {}
    for f in sorted(IR_DIR.glob("*.jsonl")):
        for line in f.open(encoding="utf-8"):
            line = line.strip()
            if line:
                s = json.loads(line)
                out[s["id"]] = s
    if not out:
        raise SystemExit("❌ data/ir 里一条样本都没读到 —— 先验扫描本身（5.22）")
    return out


def load_pilots(paths: list[Path]) -> list[dict]:
    recs, seen = [], set()
    for p in paths:
        if not p.exists():
            raise SystemExit(f"❌ {p} 不在")
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["id"] in seen:
                raise SystemExit(
                    f"❌ {r['id']} 在多份产物里都出现了。\n"
                    "   多半是几轮试点混着传进来了，而不同轮用的是**不同版提示词** ——\n"
                    "   取哪一份说不清，先挑出你要的那一份再跑。")
            seen.add(r["id"])
            recs.append(r)
    if not recs:
        raise SystemExit("❌ 一条改写都没读到（5.22）")
    return recs


def cmd_verify() -> int:
    """改写过的样本有没有跑进考卷。**必须在 `esa.evalset` 之后跑。**

    `dump_samples` 那道钩子查不了这件事 —— 落盘的时候切分还没发生。
    """
    table = load_table()
    if not table:
        print("改写表是空的，没什么可查的。")
        return 0
    bad = []
    for path in (EVAL, SUPP):
        if not path.exists():
            continue
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            gid = json.loads(line)["gold"].get("id", "")
            # 考卷里一条样本会拆成 `<id>` 和 `<id>#respond` 两道题
            if gid.split("#")[0] in table:
                bad.append((path.name, gid))
    print(f"改写表 {len(table)} 段；考卷 {EVAL.name} + {SUPP.name} 已查。")
    if not bad:
        print("✅ 没有一段改写跑进考卷")
        return 0
    print(f"🔴 {len(bad)} 道考题的样本被改写过 —— 重生成把它们从训练池挪进考卷了：")
    for f, gid in bad[:20]:
        print(f"     {f}  {gid}")
    print("\n   考卷里的参考回答**不能**是我们自己改写出来的：\n"
          "   要么把这些 id 从改写表里删掉，要么这一轮别用改写表。")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot", type=Path, nargs="*", default=[],
                    help="sdft_pilot.py 的产物，可给多份")
    ap.add_argument("--out", type=Path, default=REWRITES_DIR / "sdft.jsonl")
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认只看不写）")
    ap.add_argument("--verify", action="store_true",
                    help="查改写过的样本有没有跑进考卷（在 esa.evalset 之后跑）")
    ap.add_argument("--exclude-id", action="append", default=[],
                    metavar="样本id=理由",
                    help="按样本 id 排除，**必须带理由**。典型来源：灌表之后跑 "
                         "`esa.validate`，它的 grounding 闸门会挑出「改写把工具返回的"
                         "字面引用丢了」的那些 —— 把它们喂回这里再灌一次")
    ap.add_argument("--exclude-template", action="append", default=[],
                    metavar="模板前缀=理由",
                    help="按 template_id 前缀整组排除，**必须带理由**。"
                         "机械闸门盖不住的语义错只能这么处理（5.67）")
    args = ap.parse_args()

    if args.verify:
        return cmd_verify()
    if not args.pilot:
        ap.error("要么 --pilot <产物>，要么 --verify")

    excl, excl_id = {}, {}
    for flag, spec_list, into in (("--exclude-template", args.exclude_template, excl),
                                  ("--exclude-id", args.exclude_id, excl_id)):
        for spec in spec_list:
            if "=" not in spec:
                ap.error(f"{flag} 要写成 键=理由，收到 {spec!r} —— "
                         "静默排除和没排除一样糟，理由必须留下")
            k, v = spec.split("=", 1)
            into[k.strip()] = v.strip()

    ir, recs = ir_by_id(), load_pilots(args.pilot)
    keep, drop = [], []
    fam_len: dict[str, list[tuple[int, int]]] = defaultdict(list)
    moment, gate_mismatch = [], []

    for r in recs:
        if r["id"] in excl_id:
            drop.append((r["id"], f"人工排除：{excl_id[r['id']]}"))
            continue
        hit = next((k for k in excl if r["template_id"].startswith(k)), None)
        if hit:
            drop.append((r["id"], f"人工排除（{hit}）：{excl[hit]}"))
            continue
        s = ir.get(r["id"])
        if s is None:
            drop.append((r["id"], "这个 id 在当前 IR 里不存在（数据换版了）"))
            continue
        cur = s["turns"][-1]["content"]
        # 回传口径有两种：`ref` 是原文全文，`ref_sha16` 是它的哈希。
        # 🔴 后者是为了**粘得回来**：238 段的完整产物约 250 KB，而集群
        # `scp` 不通、同步只能靠粘贴（手册 3350）。哈希把每条省下几十个汉字，
        # 而它作为「这段改写是对着哪句原文做的」这个守卫**一样硬**。
        if "ref" in r:
            stale = cur != r["ref"]
        elif "ref_sha16" in r:
            stale = hashlib.sha256(cur.encode("utf-8")).hexdigest()[:16] != r["ref_sha16"]
        else:
            drop.append((r["id"], "既没有 ref 也没有 ref_sha16 —— 无法确认它对应哪句原文"))
            continue
        if stale:
            drop.append((r["id"], "原文已变 —— 改写对应的是旧那一版（5.59）"))
            continue
        # 🔴 拿本机当前的判据重算，不信产物里存的那份（5.54）
        g = sdft_pilot.gate(sdft_pilot.build(s), r["rewritten"])
        bad = [k for k in HARD if not g[k].startswith(("✅", "跳过"))]
        if bad:
            drop.append((r["id"], "、".join(f"{k}{g[k]}" for k in bad)))
            continue
        if r.get("gate") and {k: v for k, v in r["gate"].items() if k in HARD} != \
                {k: v for k, v in g.items() if k in HARD}:
            gate_mismatch.append(r["id"])
        if g["刚才刚刚"] != "—":
            moment.append((r["id"], r["template_id"]))
        # 表里一律存**全文** `ref` —— 它是 dump_samples 那道钩子的守卫，
        # 而那里没有 IR 可查（它正在生成 IR）。回传时省的是带宽，不是守卫。
        keep.append({"id": r["id"], "template_id": r["template_id"],
                     "ref": cur, "rewritten": r["rewritten"],
                     "source": args.pilot[0].stem})
        fam_len[r["template_id"].split("__")[0]].append(
            (len(cur), len(r["rewritten"])))

    # 🔴 不幂等：上一次 --apply 之后重跑过生成器的话，IR 里已经是**改写后**的文本，
    # 于是 ref 守卫会把每一条都判成「原文已变」。守卫没错，错的是顺序。
    # 与其让人对着 238 条「原文已变」怀疑数据坏了，不如当场说清楚该怎么办。
    stale_n = sum(1 for _, why in drop if why.startswith("原文已变"))
    if stale_n > len(recs) * 0.5 and (REWRITES_DIR / "sdft.jsonl").exists():
        print(f"🔴 {stale_n}/{len(recs)} 段判成「原文已变」，而改写表已经存在 ——\n"
              "   多半是上一次 --apply 之后重跑过生成器，IR 里已经是改写后的文本了。\n"
              "   这个工具**不幂等**。要重灌就先让 IR 回到原样：\n"
              "     rm dataset/data/rewrites/sdft.jsonl\n"
              "     for g in …; do python3 dataset/generators/gen_$g.py; done\n"
              "   然后再跑这条命令。\n")
    print(f"读入 {len(recs)} 段　→　可用 {len(keep)}　丢弃 {len(drop)}\n")
    print(f"{'族':<28}{'段数':>5}{'原中位':>8}{'改后中位':>10}")
    for fam, pairs in sorted(fam_len.items()):
        a = sorted(x for x, _ in pairs)
        b = sorted(y for _, y in pairs)
        print(f"{fam:<28}{len(pairs):>5}{a[len(a)//2]:>8}{b[len(b)//2]:>10}")

    if drop:
        print(f"\n🔴 丢弃 {len(drop)} 段（**不是失败，是闸门在干活**）：")
        for i, (qid, why) in enumerate(drop[:15]):
            print(f"     {qid}  {why}")
        if len(drop) > 15:
            print(f"     …… 另 {len(drop) - 15} 段")
    if gate_mismatch:
        print(f"\n⚠️ {len(gate_mismatch)} 段的闸门结果与产物里存的不一致 —— "
              "集群上那版 sdft_pilot.py 和本机不是同一版（5.50）。"
              "以本机重算的为准，但值得去核一下版本。")
    if moment:
        print(f"\n👀 {len(moment)} 段用了「刚才 / 刚刚」—— **线索不是判据**："
              "用户原话里报了刚做的动作就有依据，没报就是凭空的，机械分不开（5.67）。"
              "\n   入库前对着用户原话看一遍：")
        for qid, tpl in moment[:10]:
            print(f"     {qid}　{tpl}")

    if not args.apply:
        print(f"\n（只看不写。确认之后加 --apply 写进 {args.out}）")
        return 0
    if not keep:
        raise SystemExit("❌ 一段都没通过，不写空表")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in keep)
                        + "\n", encoding="utf-8")
    print(f"\n→ {args.out}（{len(keep)} 段）")
    print("下一步（顺序不能反）：\n"
          "  1. 十个生成器重跑一遍（改写在 dump_samples 里生效）\n"
          "  2. PYTHONPATH=dataset python3 -m esa.validate dataset/data/ir/*.jsonl\n"
          "  3. PYTHONPATH=dataset python3 -m esa.evalset\n"
          "  4. python3 dataset/tools/apply_sdft.py --verify   ← 改写不许进考卷\n"
          "  5. 🔴 核 eval.jsonl 的 sha256：改写只动末轮正文、不动样本数和模板数，\n"
          "     **它应当逐字节不变**。变了就说明动了不该动的，而且 base 得重评（5.42）")
    print(f"\n族分布：{dict(Counter(r['template_id'].split('__')[0] for r in keep))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
