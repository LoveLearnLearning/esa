# backend/scripts/dataset/esa/enumerate_states.py

"""State 枚举：全排列 → 自动剪枝 → 推导 expected_action → 导出给人剪枝。

原来的做法是人去想「还有哪些状态组合」，这在 State 空间是
required_param × context × revision × tool_result × gate 的乘积时撑不住 ——
表里的 ST009 / ST010 就是卡住的现场（两行文字重复、无 state_name、无动作、预算 0）。

换成：程序生成全排列，自动剪掉结构上不可能的，剩下的用 00 页那棵决策树推导标签，
人只负责剪掉「不现实」的和补 argument_rule。剪枝比发明容易得多，也更完整。

用法：
    PYTHONPATH=dataset python3 -m esa.enumerate_states --verify-against-sheet
    PYTHONPATH=dataset python3 -m esa.enumerate_states --scenario S002 --out states_S002.csv
"""

from __future__ import annotations

import argparse
import csv
import itertools
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .design_table import DesignTable, DEFAULT_XLSX
from .paths import in_dataset

# 各轴取值。与 00_说明与字典 的字典区保持一致；
# required_param_state / optional_param_state 目前字典区没收录，先在这里定义并回写建议。
REQUIRED_PARAM_STATES = ["全部齐全", "缺1个", "缺多个", "无required参数"]
CONTEXT_STATES = ["无相关上下文", "参数全部在当前轮", "部分参数在历史轮", "全部参数在历史轮", "历史信息与当前轮冲突"]
USER_REVISION_STATES = ["未修改", "修改参数", "撤销参数"]
TOOL_RESULT_STATES = ["未调用", "成功", "空结果", "工具报错"]
GATE_STATES = ["不适用", "已满足", "未满足"]


@dataclass(frozen=True)
class StateAxes:
    """封装 `StateAxes` 的状态与行为。"""
    required_param_state: str
    context_state: str
    user_revision_state: str
    tool_result_state: str
    gate_state: str
    needs_tool: bool = True


# --------------------------------------------------------------------------
# 决策树：直接实现 00_说明与字典 里那张图
# --------------------------------------------------------------------------


def derive_action(s: StateAxes) -> str:
    """从状态各轴推导 expected_action。

    对表里已填的 11 条 State 复现率 100%（见 --verify-against-sheet）。
    """
    # gate 是最外层闸门：未满足就不能做这件事，只能解释
    if s.gate_state == "未满足":
        return "DIRECT_ANSWER"

    # 工具已经执行过，接下来是处理结果
    if s.tool_result_state == "成功":
        return "RESPOND_TOOL_RESULT"
    if s.tool_result_state in ("空结果", "工具报错"):
        return "RECOVER_TOOL_ERROR"

    # 压根不需要工具
    if not s.needs_tool:
        return "DIRECT_ANSWER"

    # 需要工具且尚未调用：把历史上下文算进来后，参数够不够？
    if s.required_param_state in ("无required参数", "全部齐全"):
        return "CALL_TOOL"
    if s.context_state == "全部参数在历史轮":
        return "CALL_TOOL"
    return "ASK_USER"


# --------------------------------------------------------------------------
# 结构剪枝：这些组合在语义上自相矛盾，不该拿去给人看
# --------------------------------------------------------------------------


def structural_reason(s: StateAxes) -> str | None:
    """返回不合法的原因；合法则返回 None。"""
    if s.required_param_state == "无required参数" and s.context_state in (
        "部分参数在历史轮",
        "全部参数在历史轮",
        "历史信息与当前轮冲突",
    ):
        return "没有 required 参数，谈不上参数来自历史轮"

    if s.required_param_state == "全部齐全" and s.context_state == "无相关上下文":
        # 参数齐全说明至少当前轮给了，"无相关上下文"是矛盾的
        return "参数已齐全，context_state 不应是「无相关上下文」"

    if s.context_state == "无相关上下文" and s.user_revision_state != "未修改":
        return "没有上下文就谈不上修改/撤销先前的参数"

    if s.user_revision_state in ("修改参数", "撤销参数") and s.context_state == "参数全部在当前轮":
        return "修改/撤销是针对历史轮参数的动作"

    if s.required_param_state in ("缺1个", "缺多个") and s.context_state == "参数全部在当前轮":
        return "参数全在当前轮就不会缺"

    if s.tool_result_state in ("成功", "空结果", "工具报错") and s.required_param_state in ("缺1个", "缺多个"):
        return "参数都缺，工具不可能已经执行出结果"

    if s.gate_state == "未满足" and s.tool_result_state != "未调用":
        return "gate 未满足时工具不应该已经被调用"

    if not s.needs_tool and s.tool_result_state != "未调用":
        return "不需要工具却有工具结果"

    if not s.needs_tool and s.gate_state != "不适用":
        return "不需要工具时 gate 不适用"

    return None


# 每种动作下，真正会改变 gold behavior 的轴。
#
# 这是把表里 affects_gold_answer 那条原则用在 State 层：工具已经报错之后，
# 参数当初是从当前轮还是历史轮来的，已经不影响模型该做什么了 —— 这些状态是
# 行为等价的，合并成一条，不要让人去逐个审 24 个重复项。
RELEVANT_AXES = {
    "RESPOND_TOOL_RESULT": ("tool_result_state",),
    "RECOVER_TOOL_ERROR": ("tool_result_state",),
    "DIRECT_ANSWER": ("gate_state", "needs_tool"),
    "ASK_USER": ("required_param_state", "context_state", "user_revision_state"),
    "CALL_TOOL": ("required_param_state", "context_state", "user_revision_state"),
}


def _signature(s: StateAxes, action: str) -> tuple:
    """处理 `_signature` 相关逻辑。"""
    return (action,) + tuple(getattr(s, ax) for ax in RELEVANT_AXES[action])


def required_param_axis(n_required: int) -> list[str]:
    """必填参数个数决定了 required_param_state 轴上哪些取值有意义。

    只有一个必填参数的工具不可能「缺多个」；没有必填参数的工具只有一种状态。
    不做这层限制会产生大量根本不可能出现的状态让人白审。
    """
    if n_required == 0:
        return ["无required参数"]
    if n_required == 1:
        return ["全部齐全", "缺1个"]
    return ["全部齐全", "缺1个", "缺多个"]


def enumerate_for_scenario(
    needs_tool_values: tuple[bool, ...] = (True,),
    gated: bool = False,
    collapse: bool = True,
    n_required: int | None = None,
) -> list[tuple[StateAxes, str]]:
    """产出 (合法状态, 推导动作) 列表。

    gated=True 时才把 已满足/未满足 纳入 gate 轴，否则只有「不适用」。
    collapse=True 时合并行为等价的状态，只保留每个签名的第一个代表。
    n_required 给定时按该工具的必填参数个数收窄 required_param_state 轴。
    """
    gates = GATE_STATES if gated else ["不适用"]
    req = required_param_axis(n_required) if n_required is not None else REQUIRED_PARAM_STATES
    out, seen = [], set()
    for combo in itertools.product(
        req, CONTEXT_STATES, USER_REVISION_STATES, TOOL_RESULT_STATES, gates, needs_tool_values
    ):
        s = StateAxes(*combo)
        if structural_reason(s) is not None:
            continue
        action = derive_action(s)
        if collapse:
            sig = _signature(s, action)
            if sig in seen:
                continue
            seen.add(sig)
        out.append((s, action))
    return out


# --------------------------------------------------------------------------
# 回归测试：推导结果必须复现表里已填的人工标注
# --------------------------------------------------------------------------


def verify_against_sheet(dt: DesignTable) -> tuple[int, int, list[str]]:
    """验证 `against sheet` 相关数据。

    Args:
        dt: DesignTable => `dt` 参数。

    Returns:
        tuple[int, int, list[str]] => 处理结果。
    """
    ok = bad = 0
    msgs = []
    for s in dt.states:
        want = str(s.get("expected_action") or "")
        if not want:
            continue
        gate = str(s.get("gate_state") or "") or (
            # gate 两列目前还没填；用 case_type 反推已知的两条，填完表后这段可以删掉
            "未满足" if str(s.get("case_type") or "") == "Hard Negative" and str(s.get("primary_rule_id")) == "R009"
            else "已满足" if str(s.get("primary_rule_id")) == "R009"
            else "不适用"
        )
        axes = StateAxes(
            required_param_state=str(s.get("required_param_state") or ""),
            context_state=str(s.get("context_state") or ""),
            user_revision_state=str(s.get("user_revision_state") or "未修改"),
            tool_result_state=str(s.get("tool_result_state") or "未调用"),
            gate_state=gate,
        )
        got = derive_action(axes)
        if got == want:
            ok += 1
        else:
            bad += 1
            msgs.append(f"  ❌ {s['state_id']}: 表里={want}  推导={got}  ({axes})")
    return ok, bad, msgs


def required_param_count(dt: DesignTable, scenario_id: str) -> int | None:
    """查该 Scenario 主工具的必填参数个数。多工具或查不到时返回 None（不收窄轴）。"""
    scen = next((s for s in dt.scenarios if str(s.get("scenario_id")) == scenario_id), None)
    if not scen:
        return None
    tools = [t.strip() for t in re.split(r"[/,、]", str(scen.get("related_tool") or "")) if t.strip()]
    if len(tools) != 1:
        return None
    return sum(
        1
        for p in dt.parameters
        if str(p.get("tool_name")) == tools[0] and str(p.get("required_type")) == "required"
    )


FIELDS = [
    "state_id", "scenario_id", "primary_rule_id", "state_name",
    "required_param_state", "missing_parameters", "context_state",
    "user_revision_state", "tool_result_state", "gate_condition", "gate_state",
    "expected_action", "expected_tool", "argument_rule", "ask_for",
    "gold_behavior", "case_type", "generation_budget", "keep",
]


def export_csv(rows: list[tuple[StateAxes, str]], scenario_id: str, path: Path) -> None:
    """导出给人剪枝：只需要填 keep 列和 argument_rule / gold_behavior。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for i, (s, action) in enumerate(rows, 1):
            w.writerow({
                "state_id": f"{scenario_id}_A{i:03d}",
                "scenario_id": scenario_id,
                "required_param_state": s.required_param_state,
                "context_state": s.context_state,
                "user_revision_state": s.user_revision_state,
                "tool_result_state": s.tool_result_state,
                "gate_state": s.gate_state,
                "expected_action": action,
                "keep": "",  # 人填：是 / 否
            })


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    ap = argparse.ArgumentParser(description="State 枚举与决策树验证")
    ap.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    ap.add_argument("--verify-against-sheet", action="store_true")
    ap.add_argument("--scenario", help="为该 scenario_id 导出候选状态 CSV")
    ap.add_argument("--gated", action="store_true", help="该场景涉及 gate（记忆修改 / record_answer 等）")
    ap.add_argument("--allow-no-tool", action="store_true", help="纳入「不需要工具」分支")
    ap.add_argument("--out", default=str(in_dataset("data/states_candidates.csv")))
    args = ap.parse_args(argv)

    if args.verify_against_sheet:
        dt = DesignTable.load(args.xlsx)
        ok, bad, msgs = verify_against_sheet(dt)
        print(f"决策树复现表内人工标注：{ok}/{ok + bad}")
        for m in msgs:
            print(m)
        if bad:
            return 1
        print("✅ derive_action() 与表格完全一致，可以用来自动填 expected_action")

    if args.scenario:
        dt = DesignTable.load(args.xlsx)
        n_req = required_param_count(dt, args.scenario)
        nt = (True, False) if args.allow_no_tool else (True,)
        kw = dict(needs_tool_values=nt, gated=args.gated, n_required=n_req)
        structural = enumerate_for_scenario(**kw, collapse=False)
        rows = enumerate_for_scenario(**kw, collapse=True)
        req_axis = required_param_axis(n_req) if n_req is not None else REQUIRED_PARAM_STATES
        total = len(req_axis) * len(CONTEXT_STATES) * len(USER_REVISION_STATES) * len(TOOL_RESULT_STATES) * (
            len(GATE_STATES) if args.gated else 1
        ) * len(nt)
        export_csv(rows, args.scenario, Path(args.out))

        from collections import Counter

        dist = Counter(a for _, a in rows)
        if n_req is not None:
            print(f"\n{args.scenario} 的工具有 {n_req} 个必填参数 → required_param_state 轴收窄为 {req_axis}")
        print(f"{args.scenario}: 全排列 {total} → 结构剪枝 {len(structural)} → 合并行为等价 {len(rows)}")
        for a, n in dist.most_common():
            print(f"  {a:22s} {n}")
        print(f"\n已导出 → {args.out}")
        print("人工只需做两件事：填 keep 列（是/否），以及给保留的状态补 argument_rule / gold_behavior")

    return 0


if __name__ == "__main__":
    sys.exit(main())
