"""人工复核台账的读取与应用。

`needs_review` 由生成器按**组**写死，粒度太粗：审完一条也没法单独放行，
只能改生成器代码把整组一起放开 —— 那等于把闸门拆了。
`seeds/reviewed.yaml` 把粒度改成逐条，这个模块负责把两者合起来算出
"到底还有哪些没审"。

四个消费者，且必须用同一个函数，否则会漂移：
  - `tools/export_review_queue.py` —— 队列里只列没审的
  - `esa/evalset.py`               —— 没审的挡在训练集外
  - `esa/split.py`                 —— 绕过 evalset 直接切 IR 时的第二道拦截
  - `esa/validate.py`              —— 结尾那行「待人工复核 N 条」的 N

⚠️ 这份名单第一版写的是"两个消费者"，漏了 `split.py` —— 它自己写了
`if s.needs_review` 而不认台账，于是审完登记过的样本在那条路径上仍会被拦，
报错还指示人去"把 needs_review 关掉"（那个字段在生成器里按组写死，关不掉）。
新增消费者时把它加进这份名单，别再自己写判据。

⚠️ 同一个错第二次：2026-08-12 发现 `validate.py` 也自己写了 `if s.needs_review`。
它不拦数据，只打印"待人工复核 N 条"，所以一直没人注意 —— 但交接文档第九节
恰恰让人用这个数验复核进度，而它审多少都不动（第一次登记 53 条时仍报 56）。
**不拦数据的消费者一样会漂移，照样要进这份名单。**

设计上刻意不做的事
------------------
不提供"把 id 写进台账"的函数。登记必须是人手动改 yaml —— 这张表的全部价值
就在于"有人看过并签了名"，给它配一个自动写入的接口，第一次赶进度时就会被拿来
批量放行，然后这道闸门就名存实亡了。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .ir import Sample

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "dataset/seeds/reviewed.yaml"

REQUIRED_FIELDS = ("id", "by", "date", "note")


class ReviewLedgerError(RuntimeError):
    """台账本身有问题。一律抛出，绝不降级成警告后继续。"""


def load_ledger(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """读台账，返回 {sample_id: 该条登记}。台账不存在视为空（还没人审过）。"""
    p = Path(path) if path else DEFAULT_LEDGER
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = raw.get("reviewed") or []
    if not isinstance(entries, list):
        raise ReviewLedgerError(f"{p.name}: `reviewed` 必须是列表，实际是 {type(entries).__name__}")

    out: dict[str, dict[str, Any]] = {}
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ReviewLedgerError(f"{p.name}: 第 {i + 1} 条不是映射，应形如 {{id, by, date, note}}")
        missing = [f for f in REQUIRED_FIELDS if not str(e.get(f) or "").strip()]
        if missing:
            raise ReviewLedgerError(
                f"{p.name}: 第 {i + 1} 条（id={e.get('id')!r}）缺字段 {missing}。\n"
                "四个字段都是必填 —— 少了 by 就没人负责，少了 note 就不知道审了什么。"
            )
        sid = str(e["id"])
        if sid in out:
            raise ReviewLedgerError(f"{p.name}: id={sid!r} 登记了两次")
        out[sid] = e
    return out


def assert_no_stale(all_samples: list[Sample], ledger: dict[str, dict] | None = None) -> None:
    """台账里登记了、但整个语料里根本没有的 id ——直接抛错。

    那说明样本改名或被删了，而那条"某某某在某天审过它"的记录已经失去指向。
    静默忽略的话，下次这个 id 被别的样本复用，就会凭空继承一条它从没经历过的复核记录。

    ⚠️ `all_samples` 必须是**整个语料**，不能是训练池或任何子集。
    这里踩过一次：`evalset.build()` 原先把 train_pool 传给带存在性检查的 `pending()`，
    而 46 条待复核里有 15 条落在评测集 —— 审完登记其中任何一条，
    整条流水线就会报"这个 id 不存在"然后崩掉。存在性检查和过滤必须分开，
    因为它们要看的集合本来就不是同一个。
    """
    ledger = load_ledger() if ledger is None else ledger
    if stale := sorted(set(ledger) - {s.id for s in all_samples}):
        raise ReviewLedgerError(
            f"reviewed.yaml 里这些 id 在当前数据里不存在：{stale}\n"
            "样本改名或删除之后，台账里的对应条目必须一起清掉 —— "
            "留着它等于给一个不存在的东西背书。"
        )


def pending(samples: list[Sample], ledger: dict[str, dict] | None = None) -> list[Sample]:
    """`samples` 里还没有人审过的那些。纯过滤，不做存在性检查。

    存在性检查见 `assert_no_stale()` —— 它要看整个语料，而这里经常只拿到一个子集。
    """
    ledger = load_ledger() if ledger is None else ledger
    return [s for s in samples if s.needs_review and s.id not in ledger]
