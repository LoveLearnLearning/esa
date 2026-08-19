# backend/scripts/dataset/tests/test_review_ledger.py

"""复核台账的负向测试。

`seeds/reviewed.yaml` 决定哪些样本可以进训练集，是一道闸门。闸门的失效方式
只有一种值得担心：**该拦的没拦，而且不报错**。所以这里每条都成对写：
「该报的报」+「不该报的不报」——只写前者会得到一个永远在报错的假检查。

用法：
    python3 dataset/tests/test_review_ledger.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, Turn  # noqa: E402
from esa.review import ReviewLedgerError, assert_no_stale, load_ledger, pending  # noqa: E402

OK = {"id": "s1", "by": "张三", "date": "2026-08-12", "note": "逐步核对了平均情况递推式"}


def sample(sid: str, needs_review: bool = True) -> Sample:
    """处理 `sample` 相关逻辑。

    Args:
        sid: str => `sid` 参数。
        needs_review: bool => `needs_review` 参数。

    Returns:
        Sample => 处理结果。
    """
    return Sample(
        id=sid, template_id=f"t__{sid}", category="hard_negative", schema_version="x",
        system="s", tool_names=[], needs_review=needs_review,
        turns=[Turn(role="user", content="问"), Turn(role="assistant", content="答")],
    )


def write(entries) -> Path:
    """写入 `write` 相关数据。"""
    fd, p = tempfile.mkstemp(suffix=".yaml")
    Path(p).write_text(yaml.safe_dump({"reviewed": entries}, allow_unicode=True), encoding="utf-8")
    return Path(p)


def raises(fn) -> bool:
    """处理 `raises` 相关逻辑。"""
    try:
        fn()
    except ReviewLedgerError:
        return True
    return False


def cases() -> list[tuple[str, bool]]:
    """处理 `cases` 相关逻辑。"""
    out = []
    samples = [sample("s1"), sample("s2"), sample("s3", needs_review=False)]

    # 1) 空台账 = 谁都没审过，needs_review 的全部挡下
    out.append(("空台账时 needs_review 的样本全部待审",
                [s.id for s in pending(samples, {})] == ["s1", "s2"]))
    out.append(("needs_review=False 的样本本来就不在队列里",
                "s3" not in [s.id for s in pending(samples, {})]))

    # 2) 登记之后逐条放行 —— 不能连带放行同组其他条
    led = load_ledger(write([OK]))
    out.append(("登记 s1 之后只放行 s1", [s.id for s in pending(samples, led)] == ["s2"]))

    # 3) 四个字段缺一不可。少了 by 就没人负责，少了 note 就不知道审了什么。
    for miss in ("by", "date", "note"):
        bad = {k: v for k, v in OK.items() if k != miss}
        out.append((f"缺 {miss} 必须报错", raises(lambda b=bad: load_ledger(write([b])))))
    out.append(("字段写成空串也必须报错",
                raises(lambda: load_ledger(write([{**OK, "by": "   "}])))))
    out.append(("四个字段齐全不应报错", not raises(lambda: load_ledger(write([OK])))))

    # 4) 残留条目必须炸。样本改名之后留着旧登记，等于给一个不存在的东西背书；
    #    更糟的是这个 id 将来被别的样本复用，会凭空继承一条复核记录。
    out.append(("登记了不存在的 id 必须报错",
                raises(lambda: assert_no_stale(samples, load_ledger(write([{**OK, "id": "没这条"}]))))))
    out.append(("语料里存在的 id 不应误报",
                not raises(lambda: assert_no_stale(samples, led))))

    # 4b) 回归：存在性检查只能对**整个语料**做，不能对训练池做。
    #     46 条待复核里有 15 条落在评测集里；审完登记其中任何一条，
    #     若拿 train_pool 去查存在性，就会误报"这个 id 不存在"，整条流水线崩掉。
    #     所以 pending() 是纯过滤、不查存在性，查存在性的是 assert_no_stale()。
    train_pool_only = [s for s in samples if s.id != "s1"]  # 假装 s1 被划进了评测集
    out.append(("已登记的样本落在评测集时，对训练池过滤不该报错",
                not raises(lambda: pending(train_pool_only, led))))
    out.append(("同一份台账对全语料查存在性仍然通过",
                not raises(lambda: assert_no_stale(samples, led))))

    # 5) 结构性错误
    out.append(("同一个 id 登记两次必须报错",
                raises(lambda: load_ledger(write([OK, {**OK, "by": "李四"}])))))
    out.append(("条目不是映射必须报错", raises(lambda: load_ledger(write(["s1"])))))
    out.append(("台账文件不存在时视为空台账（还没人审）", load_ledger(Path("/nonexistent.yaml")) == {}))

    # 6) 每一个消费者都必须走 review.pending()，不能自己写 `if s.needs_review`。
    #    split.py 第一版就是自己写的，于是审完登记过的样本在那条路径上仍被拦下 ——
    #    而那条路径（直接切 data/ir/*.jsonl）恰恰是这道拦截唯一会被触发的地方，
    #    正常入口下 evalset 已经把待复核的剔掉了，所以端到端跑多少遍都发现不了。
    #    这条用例查的是源码本身：绕过 review 自己判 needs_review 就算失败。
    src_dir = Path(__file__).resolve().parents[1] / "esa"
    consumers = {"split.py", "evalset.py"}
    for name in sorted(consumers):
        text = (src_dir / name).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        self_judged = "s.needs_review" in code and "review.pending" not in code
        out.append((f"{name} 必须用 review.pending() 判待复核，不能自己判", not self_judged))
    return out


def main() -> int:
    """运行当前模块的命令行入口。"""
    passed = failed = 0
    for name, ok in cases():
        print(f"{'✅' if ok else '❌'} {name}")
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"\n{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
