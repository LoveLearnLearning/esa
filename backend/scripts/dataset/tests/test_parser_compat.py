"""后端 parser 兼容性验证 —— 不需要 GPU、不需要下权重就能跑。

    python3 dataset/tests/test_parser_compat.py

两件事：

**一、复刻保真**（新增，2026-08-11）
`esa/backend_parser.py` 是后端解析器的本地复刻。逐条比对
`data/cache/parser_golden.json` 里**后端真实 parse_output 跑出来的结果**，
对不上就说明复刻脱节了 —— 这次就发生了一回：后端加了"按 schema 恢复参数类型"，
我们这边还是旧版，`<parameter=lower>0</parameter>` 在后端是字符串 `"0"`、
在我们这里是整数 `0`，**没有任何东西会报错**，只有评测分数悄悄和线上对不上。

⚠️ 这个文件原本自己藏了**第三份** parse_output 复刻（抄自 会议事程.md），
和 `backend_parser.py`、后端本体三份各自演化。现在统一从 `backend_parser` 导入：
一份复刻已经够难维护了，三份必然对不齐。

**二、格式不兼容的实证**（原有结论，仍然成立）
LLaMA-Factory 的 qwen 系模板产出 JSON（`data/tool_utils.py:423-428`），
后端 parse_output 只认 XML，遇到 JSON **静默返回空 ParsedOutput** ——
无异常、无日志，前端拿到完全空白的回复。见交接文档 6.1。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.backend_parser import parse_output_current, parse_output_dual  # noqa: E402
from esa.ir import load_samples, load_schemas, schemas_by_name  # noqa: E402
from esa.render import assistant_wire_segments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "dataset/data/cache/parser_golden.json"


def as_dict(parsed) -> dict:
    return {
        "reasoning": parsed.reasoning,
        "content": parsed.content,
        "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in parsed.tool_calls],
    }


def check_golden(schemas) -> tuple[int, int]:
    """逐条比对：我们的复刻必须和后端真实 parse_output 输出完全一致。"""
    if not GOLDEN.exists():
        print(f"⚠️  找不到 {GOLDEN.relative_to(ROOT)}，跳过复刻保真检查。")
        print("    重抓：python3 dataset/tools/capture_parser_golden.py")
        return 0, 0

    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    meta = data["_meta"]
    print("=" * 74)
    print("一、复刻保真：esa/backend_parser.py vs 后端真实 parse_output")
    print(f"   黄金样例来源 {meta['source_repo']}   抓取于 {meta['captured_at']}")
    for rel, h in meta["source_sha256"].items():
        print(f"   {h}  {rel}")

    passed = failed = 0
    for case in data["cases"]:
        got = as_dict(parse_output_current(case["input"], schemas))
        want = case["expected"]
        # 后端 ParsedOutput.reasoning/content 默认是 None，我们的 dataclass 默认是 ""。
        # 这是本地 dataclass 的表示差异，不是解析行为差异，比对时按空值等价处理。
        if (got["tool_calls"] == want["tool_calls"]
                and (got["reasoning"] or "") == (want["reasoning"] or "")
                and (got["content"] or "") == (want["content"] or "")):
            passed += 1
            continue
        failed += 1
        if failed <= 5:
            print(f"\n   ❌ 输入: {case['input'][:110]!r}")
            print(f"      后端: {json.dumps(want, ensure_ascii=False)[:220]}")
            print(f"      我们: {json.dumps(got, ensure_ascii=False)[:220]}")

    print(f"\n   {passed} 条一致 / {failed} 条不一致（共 {passed + failed} 条）")
    if failed:
        print("   → 后端改了解析器。重抓黄金样例，再按差异改 esa/backend_parser.py。")
    else:
        print("   ✅ 复刻与后端逐条一致")
    return passed, failed


def check_format_incompat(schemas, by_name) -> int:
    """原有结论：qwen JSON 格式喂给后端解析器会静默失败。"""
    samples = load_samples(ROOT / "dataset/data/ir/calculators.jsonl")
    sample = next(s for s in samples if s.category == "single_tool_call")
    expected_name = sample.called_tool_names()[0]
    expected_args = sample.turns[1].calls[0].arguments

    print("\n" + "=" * 74)
    print("二、格式兼容性实证")
    print(f"   样本 {sample.id}   期望解析出: {expected_name}({expected_args})")

    failures = 0
    for fmt in ("qwen", "xml"):
        wire = assistant_wire_segments(sample, by_name, tool_format=fmt)[0]
        print(f"\n   模型实际输出（tool_format={fmt}）:")
        print("     " + wire.strip().replace("\n", "\n     "))
        for label, fn in (("当前 parse_output", parse_output_current),
                          ("修复版 parse_output", parse_output_dual)):
            got = fn(wire, schemas)
            ok = len(got.tool_calls) == 1 and got.tool_calls[0].name == expected_name
            detail = (f"{got.tool_calls[0].name}({got.tool_calls[0].arguments})"
                      if got.tool_calls else f"tool_calls=[] content={got.content[:30]!r}")
            print(f"     {'✅' if ok else '❌'} {label:20s} → {detail}")
            if not ok and label.startswith("修复版"):
                failures += 1
            if not ok and fmt == "qwen" and label.startswith("当前"):
                print("        ↑ 这就是问题：无异常、无日志，前端拿到完全空白的回复")

    print("\n   结论：LLaMA-Factory 的 qwen 系模板产出 JSON（data/tool_utils.py:423-428），")
    print("        后端只认 XML，遇到 JSON 静默返回空 ParsedOutput。")
    print("        建议方案 A：给 LLaMA-Factory 写自定义 tool_format 复刻后端 XML")
    print("        （后端 tests/test_parser.py 有专门覆盖，XML 是刻意设计不是疏忽）。")
    return failures


def main() -> int:
    schemas, _ = load_schemas(ROOT / "dataset/schemas/tool_schemas.json")
    by_name = schemas_by_name(schemas)

    _, golden_failed = check_golden(schemas)
    fmt_failed = check_format_incompat(schemas, by_name)

    print("=" * 74)
    return 1 if (golden_failed or fmt_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
