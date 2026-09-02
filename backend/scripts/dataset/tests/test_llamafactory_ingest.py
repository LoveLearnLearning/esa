"""开训前闸门：LLaMA-Factory 会不会**静默吃掉**我们的训练样本。

    python3 dataset/tests/test_llamafactory_ingest.py
    python3 dataset/tests/test_llamafactory_ingest.py --lf ~/Downloads/llamafactory-0.9.4

为什么必须有这一道
------------------
`SharegptDatasetConverter` 遇到角色顺序不合法或总轮数为奇数时，只打一行
`logger.warning_rank0` 就把整条样本变成空的 prompt/response —— **不抛异常、
不中断训练**。等训完才发现少了几十条，那次训练就白跑了。

交接文档写的开训前检查是「训练日志里的 num_examples 必须等于文件行数」，
那是**事后**发现。这个文件把它提前到开训前，而且不需要 GPU、不需要装
LLaMA-Factory。

这不是复刻
----------
判定逻辑是**直接加载 LLaMA-Factory 源码里的 `data/converter.py`**，跑它真实的
`SharegptDatasetConverter.__call__`，不是照着规则另写一份。
理由见交接文档第二节：这个项目栽在"凭看起来合理写了一版"上已经六次。

⚠️ 唯一的妥协：`converter.py` 的父包会拉进 torch/transformers/peft/datasets
（`llamafactory/__init__.py` → `extras.env`，`data/__init__.py` → `collator`
等），本机装不下也没必要。所以这里**只加载 converter.py 这一个文件**，
并按源码原样提供它用到的两样东西：
  - `Role`  —— 逐字抄自 `data/data_utils.py:38-43`，脚本会**回读源码校验**，
              对不上直接报错，防止哪天上游改了枚举而这里没跟。
  - `logger` —— 只用来收 warning，不影响判定。
`SharegptDatasetConverter.__call__` 的函数体只碰 `self.dataset_attr`（一堆字符串）、
`Role` 和 `logger`，所以这个加载方式跑的就是真实代码路径。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "dataset/data/out"
# 🔴 版本必须和**集群上跑训练的那份**一致。集群是 `0.9.5.dev0`
# （手册 4.4「LLaMA-Factory ~/LlamaFactory，版本 0.9.5.dev0」），
# 而这里原来写死的是 `~/Downloads/llamafactory-0.9.4` —— 那个目录早就不在了，
# 于是这道**开训前闸门**每次都是 FileNotFoundError 直接退出，等于没在守。
# 更糟的是即便目录还在，0.9.4 也不是集群跑的那一版（5.21 就是这么白卡三天的）。
# 现在按顺序找，并且**把找到的版本号印出来** —— 不印版本号的「我核过源码」不算核过。
_LF_CANDIDATES = ("~/LlamaFactory", "~/LLaMA-Factory", "~/Downloads/llamafactory-0.9.4")


def _default_lf() -> Path:
    for c in _LF_CANDIDATES:
        p = Path(c).expanduser()
        if (p / "src/llamafactory/data/converter.py").exists():
            return p
    return Path(_LF_CANDIDATES[0]).expanduser()


DEFAULT_LF = _default_lf()


def _lf_version(lf: Path) -> str:
    env = lf / "src/llamafactory/extras/env.py"
    if env.exists():
        m = re.search(r'VERSION = "([^"]+)"', env.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return "未知"

# 逐字抄自 data/data_utils.py:38-43；下面 _assert_role_matches_source 会回读校验
ROLE_VALUES = {
    "USER": "user",
    "ASSISTANT": "assistant",
    "SYSTEM": "system",
    "FUNCTION": "function",
    "OBSERVATION": "observation",
}


def _assert_role_matches_source(lf: Path) -> None:
    """回读 LLaMA-Factory 源码，确认 Role 枚举没变过。"""
    src = (lf / "src/llamafactory/data/data_utils.py").read_text(encoding="utf-8")
    # 0.9.4 是 `class Role(str, Enum)`，0.9.5.dev0 换成了 `class Role(StrEnum)`。
    # **枚举的值一个都没变**（逐个核过），变的只是基类 —— 所以这里放宽的是基类，
    # 不是判据：底下那句 `found != ROLE_VALUES` 仍然逐条比值。
    m = re.search(r"class Role\((?:str, Enum|StrEnum)\):\n((?:\s+\w+ = \"[^\"]+\"\n)+)", src)
    if not m:
        raise SystemExit("在 data_utils.py 里找不到 Role 枚举 —— LLaMA-Factory 结构变了，先看源码再改这里")
    found = dict(re.findall(r"(\w+) = \"([^\"]+)\"", m.group(1)))
    if found != ROLE_VALUES:
        raise SystemExit(
            f"Role 枚举与本文件记录的不一致。\n  源码: {found}\n  本文件: {ROLE_VALUES}\n"
            "把 ROLE_VALUES 更新成源码那份，再确认判定逻辑是否受影响。"
        )


def load_converter(lf: Path):
    """只加载 converter.py 这一个文件，绕开会拉进 torch 的父包。"""
    from enum import Enum

    role = Enum("Role", ROLE_VALUES, type=str)

    pkg = types.ModuleType("_lfshim")
    pkg.__path__ = []
    extras = types.ModuleType("_lfshim.extras")
    logging_mod = types.ModuleType("_lfshim.extras.logging")

    warnings: list[str] = []

    class _Logger:
        def warning_rank0(self, msg: str) -> None:
            warnings.append(msg)

        def info_rank0(self, msg: str) -> None:  # 源码里别处可能用到
            pass

    logging_mod.get_logger = lambda _name: _Logger()
    extras.logging = logging_mod
    data_utils = types.ModuleType("_lfshim.data_utils")
    data_utils.Role = role

    sys.modules["_lfshim"] = pkg
    sys.modules["_lfshim.extras"] = extras
    sys.modules["_lfshim.extras.logging"] = logging_mod
    sys.modules["_lfshim.data_utils"] = data_utils

    path = lf / "src/llamafactory/data/converter.py"
    if not path.exists():
        raise SystemExit(f"找不到 {path} —— 用 --lf 指定 LLaMA-Factory 源码根目录")

    source = path.read_text(encoding="utf-8")
    source = source.replace("from ..extras import logging", "from _lfshim.extras import logging")
    source = source.replace("from .data_utils import Role", "from _lfshim.data_utils import Role")

    mod = types.ModuleType("_lf_converter")
    mod.__dict__["__file__"] = str(path)
    exec(compile(source, str(path), "exec"), mod.__dict__)  # noqa: S102
    return mod, warnings


@dataclass
class DatasetAttr:
    """按 LLaMA-Factory `data/parser.py:40-64` 的默认值；columns 由我们的
    dataset_info.json 覆盖。tags 我们没声明，所以全部走默认。"""

    formatting: str = "sharegpt"
    ranking: bool = False
    messages: str = "conversations"
    system: str | None = None
    tools: str | None = None
    images: str | None = None
    videos: str | None = None
    audios: str | None = None
    kto_tag: str | None = None
    chosen: str | None = None
    rejected: str | None = None
    role_tag: str = "from"
    content_tag: str = "value"
    user_tag: str = "human"
    assistant_tag: str = "gpt"
    observation_tag: str = "observation"
    function_tag: str = "function_call"
    system_tag: str = "system"
    extra: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return "esa_agent"


def self_check(mod, warnings: list[str]) -> None:
    """先证明这道闸门抓得住坏样本 —— 一个从不失败的检查等于没有检查。

    三个已知违规，都来自 converter.py:144-146 的规则：
    """
    conv = mod.SharegptDatasetConverter(dataset_attr=DatasetAttr(), data_args=None)
    probes = {
        "角色顺序颠倒（偶数位放了 gpt）": [
            {"from": "gpt", "value": "答"},
            {"from": "human", "value": "问"},
        ],
        "总轮数为奇数": [
            {"from": "human", "value": "问"},
            {"from": "gpt", "value": "答"},
            {"from": "human", "value": "又问"},
        ],
        "function_call 出现在偶数位": [
            {"from": "function_call", "value": "{}"},
            {"from": "gpt", "value": "答"},
        ],
    }
    for label, convs in probes.items():
        before = len(warnings)
        out = conv({"conversations": convs, "system": "", "tools": ""})
        caught = (not out["_prompt"]) or (not out["_response"]) or len(warnings) > before
        if not caught:
            raise SystemExit(
                f"自检失败：构造的坏样本「{label}」没有被判为坏数据。\n"
                "说明这道闸门是空转的，先修它再谈数据干不干净。"
            )
    # 正常样本必须通过，否则说明判据过严、会把好数据也算成坏的
    before = len(warnings)
    ok = conv(
        {
            "conversations": [{"from": "human", "value": "问"}, {"from": "gpt", "value": "答"}],
            "system": "",
            "tools": "",
        }
    )
    if not ok["_prompt"] or not ok["_response"] or len(warnings) > before:
        raise SystemExit("自检失败：合法样本被误判为坏数据，判据有问题")
    print(f"自检通过：{len(probes)} 个已知违规都被抓到，合法样本未被误伤\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lf", default=str(DEFAULT_LF), help="LLaMA-Factory 源码根目录")
    args = ap.parse_args()
    lf = Path(args.lf).expanduser()
    if not (lf / "src/llamafactory/data/converter.py").exists():
        raise SystemExit(
            f"❌ 找不到 LLaMA-Factory 源码：{lf}\n"
            f"   找过：{', '.join(_LF_CANDIDATES)}\n"
            "   这道闸门**不能跳过** —— 它守的是「训练时被静默吃掉的样本」。\n"
            "   拿一份与集群同版（0.9.5.dev0）的源码，或 --lf 指过去。")
    print(f"LLaMA-Factory：{lf}　版本 {_lf_version(lf)}"
          "（集群跑训练的是 0.9.5.dev0，对不上就别信这次结果）")

    _assert_role_matches_source(lf)
    mod, warnings = load_converter(lf)
    self_check(mod, warnings)

    info = json.loads((OUT_DIR / "dataset_info.json").read_text(encoding="utf-8"))

    failed = 0
    total = 0
    print(f"用 {lf}/src/llamafactory/data/converter.py 的真实 SharegptDatasetConverter\n")

    for name, spec in info.items():
        attr = DatasetAttr()
        for key, col in spec.get("columns", {}).items():
            setattr(attr, key, col)

        conv = mod.SharegptDatasetConverter(dataset_attr=attr, data_args=None)
        path = OUT_DIR / spec["file_name"]
        n = skipped = 0
        bad_ids: list[str] = []
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            n += 1
            example = json.loads(line)
            before = len(warnings)
            out = conv(example)
            # 被判为坏数据时 prompt/response 都是空的
            if not out["_prompt"] or not out["_response"] or len(warnings) > before:
                skipped += 1
                first = next(
                    (m.get("value", "")[:40] for m in example.get("conversations", [])), ""
                )
                bad_ids.append(first)
        total += n
        failed += skipped
        flag = "✅" if skipped == 0 else "❌"
        print(f"  {name:24} {n:5} 条  静默跳过 {skipped} 条  {flag}")
        for b in bad_ids[:5]:
            print(f"       ↳ {b!r}")

    print()
    print(f"共 {total} 条，静默跳过 {failed} 条")
    if failed:
        print("\n❌ 这些样本进不了训练，而 LLaMA-Factory **不会报错**。")
        print("   角色顺序规则（converter.py:144-146）：")
        print("     偶数下标只能 human / observation；奇数下标只能 gpt / function_call；总长必须偶数。")
        return 1
    print("\n✅ 全部样本都能被 LLaMA-Factory 正常摄入，没有一条会被静默跳过")
    print(f"   开训后仍要核对：训练日志的 num_examples == {total if len(info) == 1 else '各文件条数'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
