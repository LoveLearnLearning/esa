# backend/scripts/dataset/tests/test_esa_tool_format.py

"""验证 `tools/llamafactory_esa_tool_format.py` 真的能被后端 parse_output 读懂。

    python3 dataset/tests/test_esa_tool_format.py

不需要装 LLaMA-Factory（核心逻辑是纯函数），也不需要 GPU 或权重。

为什么要有这个文件
------------------
P0-1 的失败是**静默**的：后端 `parse_output` 找不到 `<function=` 就 `continue`，
返回空 `ParsedOutput` —— 前端空白，无异常无日志。所以一个"看起来对"的
自定义 tool_format 完全可能上线之后才发现读不出来，而那时已经训完了。

三道检查：
  1. 与 `esa/render.py:_wire_tool_call_xml` **逐字节一致** ——
     那份是评测和 parser 兼容测试用的参考实现。两边一漂，
     等于评测在测 A、训练产出 B，而两边各自都是绿的。
  2. 渲染 → 后端 parse_output → 参数与原样本**完全相同**（全量 369 次工具调用）。
     用的是 `esa/backend_parser.py:parse_output_current`，它由
     `data/cache/parser_golden.json`（后端真实输出）逐条钉着。
  3. `extract_tool_calls` 是 `format_tool_calls` 的**逆函数**。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from esa.backend_parser import parse_output_current  # noqa: E402
from esa.ir import load_samples, load_schemas, schemas_by_name  # noqa: E402
from esa.render import _wire_tool_call_xml  # noqa: E402
from llamafactory_esa_tool_format import (  # noqa: E402
    extract_tool_calls,
    format_tool_calls,
)

ROOT = Path(__file__).resolve().parents[2]
IR_DIR = ROOT / "dataset/data/ir"

passed = 0
failed = 0


def check(cond: bool, label: str) -> None:
    """检查 `check` 相关数据。

    Args:
        cond: bool => `cond` 参数。
        label: str => `label` 参数。
    """
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"❌ {label}")


def main() -> int:
    """运行当前模块的命令行入口。"""
    schemas, _ = load_schemas(ROOT / "dataset/schemas/tool_schemas.json")
    by_name = schemas_by_name(schemas)
    samples = [s for p in sorted(IR_DIR.glob("*.jsonl")) for s in load_samples(p)]

    n_calls = 0
    n_turns = 0
    for s in samples:
        for turn in s.turns:
            if turn.role != "tool_call":
                continue
            n_turns += 1
            n_calls += len(turn.calls)

            pairs = [(c.name, c.arguments) for c in turn.calls]
            rendered = format_tool_calls(pairs)

            # 1. 与参考实现逐字节一致
            check(
                rendered == _wire_tool_call_xml(turn),
                f"{s.id}: 渲染与 render.py:_wire_tool_call_xml 不一致\n"
                f"    本模块: {rendered!r}\n"
                f"    参考:   {_wire_tool_call_xml(turn)!r}",
            )

            # 2. 过后端 parser，参数必须完全还原
            tool_schemas = [by_name[c.name] for c in turn.calls if c.name in by_name]
            parsed = parse_output_current(rendered, tool_schemas=tool_schemas)
            got = [(tc.name, tc.arguments) for tc in parsed.tool_calls]
            check(
                got == pairs,
                f"{s.id}: 后端 parse_output 读回的参数与原样本不同\n"
                f"    原始: {pairs}\n"
                f"    读回: {got}",
            )

            # 3. 抽取器是渲染器的逆函数
            back = extract_tool_calls(rendered)
            check(
                back is not None and [n for n, _ in back] == [n for n, _ in pairs],
                f"{s.id}: extract_tool_calls 没能还原函数名",
            )

    # 4. 没有工具调用时不能瞎报
    check(extract_tool_calls("就是一句普通回答，没有任何工具调用。") is None, "纯文本被误判为工具调用")
    check(extract_tool_calls("") is None, "空串被误判为工具调用")

    # 5. 类型往返：字符串原样、其余走 JSON
    probes = [
        ("calculator", {"expression": "sqrt(144) + 2^5"}),
        ("recommend_practice", {"course": "数据结构", "weeks_to_exam": 3}),
        ("get_mastery_report", {}),
        ("x", {"flag": True, "nothing": None, "arr": [1, 2], "obj": {"a": 1}}),
        ("y", {"multiline": "第一行\n第二行"}),
    ]
    for name, args in probes:
        back = extract_tool_calls(format_tool_calls([(name, args)]))
        if not args:
            # 无参数：仍应识别出这次调用，参数为空 dict
            check(back == [(name, {})], f"无参数调用往返失败: {name}")
            continue
        check(back == [(name, args)], f"类型往返失败: {name} {args} → {back}")

    print()
    print(f"覆盖 {n_turns} 个工具调用轮次 / {n_calls} 次调用（全量 IR）")
    print(f"{passed} 通过 / {failed} 失败")
    if failed:
        return 1
    print("✅ 自定义 tool_format 的输出后端能逐条读回，且与参考实现逐字节一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
