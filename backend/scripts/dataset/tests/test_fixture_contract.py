# backend/scripts/dataset/tests/test_fixture_contract.py

"""工具返回结构契约测试。

为什么需要这个：结构校验（validate.py）能查 JSON 合不合法、参数合不合 schema，
但**查不出 observation 的结构和线上不一致**。我第一版 fixtures.py 就编了一套
`{"mastery": ..., "reason": "字符串"}`，而后端真实返回的是
`{"mastery_level": ..., "reasons": ["数组"]}` —— 220 条样本全部教模型去消费一个
线上永远不存在的结构，而所有校验都是绿的。

这个文件把结构钉死。契约来自 github.com/LoveLearnLearning/esa（2026-08-10 快照）：
  backend/agent/memories/mastery_store.py  _row_state / get_report / get_priority_ranking
  backend/agent/tools/mastery_tools.py     recommend_practice / get_mastery_report 外层包装

**后端改了这些结构，就来改这里，然后重新生成数据。**

    python3 dataset/tests/test_fixture_contract.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa import fixtures, tools_exec  # noqa: E402

# ── 契约：逐字段抄自后端源码 ──────────────────────────────────────────────

# 三个计算器的返回结构（backend/agent/tools/math_tools/）。
# 这一组是补上来的：上一版 tools_exec.py 自己重写了计算器，返回 {"value": 44}，
# 而线上是 {"expression": ..., "result": 44}；math_solver 更是根本没有 latex 字段
# —— 63 条样本消费了线上不存在的结构，而所有校验都是绿的。
CALC_KEYS = {"expression", "result"}                      # calculator.py:167-170
BITWISE_KEYS = {"expression", "result", "formats"}        # bitwise_calculator.py:165-169
BITWISE_FORMAT_KEYS = {"decimal", "binary", "octal", "hexadecimal", "bit_length", "popcount"}
SOLVER_KEYS = {"operation", "expression", "result"}       # math_solver.py:293-296

RECOMMEND_TOP = {"allowed", "user_name", "course", "count", "recommendations"}
RECOMMEND_ITEM = {
    "kp_id", "name", "course", "weight", "mastery_level",
    "practice_count", "priority", "reasons", "weak_prerequisites",
}
REPORT_TOP = {
    "allowed", "user_name", "course", "total_points",
    "avg_mastery", "weak_points", "strong_points", "stale_points",
}
# mastery_store._row_state 的返回字段
ROW_STATE = {
    "user_name", "kp_id", "has_record", "mastery_level", "retention",
    "evidence_confidence", "stability_days", "evidence_weight", "status",
    "needs_review", "practice_count", "correct_count", "last_practiced_at",
    "created_at", "updated_at", "model_version",
}
WEAK_PREREQ = {"kp_id", "name", "mastery_level", "depth"}

# student_model.py 的常量，写错了整条优先级排序都会偏
CONSTANTS = {
    "REVIEW_THRESHOLD": 0.65,
    "MIN_MASTERY": 5.0,
    "MAX_MASTERY": 98.0,
    "PRIOR_MASTERY": 50.0,
    "TOTAL_WEEKS_DEFAULT": 18,
}


def check(name: str, ok: bool, detail: str = "") -> bool:
    """检查 `check` 相关数据。

    Args:
        name: str => `name` 参数。
        ok: bool => `ok` 参数。
        detail: str => `detail` 参数。

    Returns:
        bool => 处理结果。
    """
    print(f"{'✅' if ok else '❌'} {name}" + (f"　{detail}" if detail and not ok else ""))
    return ok


def main() -> int:
    """运行当前模块的命令行入口。"""
    results = []

    for k, want in CONSTANTS.items():
        got = getattr(fixtures, k)
        results.append(check(f"常量 {k} == {want}", got == want, f"实际 {got}"))

    r = fixtures.recommend_practice("数据结构", 2)
    results.append(check("recommend_practice 顶层字段", set(r) == RECOMMEND_TOP,
                         f"多={set(r)-RECOMMEND_TOP} 少={RECOMMEND_TOP-set(r)}"))
    item = r["recommendations"][0]
    results.append(check("recommendations[] 字段", set(item) == RECOMMEND_ITEM,
                         f"多={set(item)-RECOMMEND_ITEM} 少={RECOMMEND_ITEM-set(item)}"))
    results.append(check("reasons 是数组不是字符串", isinstance(item["reasons"], list)))
    results.append(check("mastery_level 而非 mastery", "mastery_level" in item and "mastery" not in item))
    results.append(check("priority 保留 4 位小数",
                         round(item["priority"], 4) == item["priority"]))
    results.append(check("recommendations 按 priority 降序",
                         all(a["priority"] >= b["priority"]
                             for a, b in zip(r["recommendations"], r["recommendations"][1:]))))
    results.append(check("最多返回 5 条", len(r["recommendations"]) <= 5))

    wp = [w for it in r["recommendations"] for w in it["weak_prerequisites"]]
    if wp:
        results.append(check("weak_prerequisites[] 字段", set(wp[0]) == WEAK_PREREQ,
                             f"实际 {set(wp[0])}"))
        results.append(check("weak_prerequisites 全部 depth>0", all(w["depth"] > 0 for w in wp)))
        results.append(check("weak_prerequisites 全部 mastery<50",
                             all(w["mastery_level"] < 50.0 for w in wp)))

    rep = fixtures.get_mastery_report("操作系统")
    results.append(check("get_mastery_report 顶层字段", set(rep) == REPORT_TOP,
                         f"多={set(rep)-REPORT_TOP} 少={REPORT_TOP-set(rep)}"))
    if rep["weak_points"]:
        got = set(rep["weak_points"][0])
        results.append(check("weak_points[] 与 _row_state 同构", got == ROW_STATE,
                             f"多={got-ROW_STATE} 少={ROW_STATE-got}"))
    results.append(check("avg_mastery 保留 2 位", round(rep["avg_mastery"], 2) == rep["avg_mastery"]))
    results.append(check("stale_points 全部 needs_review",
                         all(p["needs_review"] for p in rep["stale_points"])))
    results.append(check("course 留空时返回 None 而非空串",
                         fixtures.get_mastery_report("")["course"] is None))

    # 优先级公式：0.35*掌握缺口 + 0.20*复习压力 + 0.20*权重 + 0.15*考试紧迫 + 0.10*前置风险
    near = fixtures.recommend_practice("数据结构", 0)["recommendations"][0]["priority"]
    far = fixtures.recommend_practice("数据结构", 18)["recommendations"][0]["priority"]
    results.append(check("考试越近优先级越高（exam_urgency 生效）", near > far, f"{near} vs {far}"))

    # 确定性：同一输入必须永远得到同一输出，否则数据不可复现
    results.append(check("确定性可复现",
                         fixtures.recommend_practice("数据结构", 2) == r))

    # ── 三个计算器：观测结构必须和线上一致 ──────────────────────────────
    c = tools_exec.execute("calculator", {"expression": "sqrt(144) + 2^5"})
    results.append(check("calculator 字段是 expression/result", set(c) == CALC_KEYS, f"实际 {set(c)}"))
    results.append(check("calculator 没有 value 字段（那是上一版编的）", "value" not in c))

    b = tools_exec.execute("bitwise_calculator", {"expression": "0xFF & 0xAA"})
    results.append(check("bitwise 字段是 expression/result/formats", set(b) == BITWISE_KEYS, f"实际 {set(b)}"))
    results.append(check("bitwise.formats 六个键", set(b["formats"]) == BITWISE_FORMAT_KEYS,
                         f"实际 {set(b['formats'])}"))
    results.append(check("bitwise 没有 bin/hex 顶层字段（那是上一版编的）",
                         "bin" not in b and "hex" not in b))

    s = tools_exec.execute("math_solver", {"operation": "diff", "expression": "x**3 + 2*x", "variable": "x"})
    results.append(check("math_solver 字段是 operation/expression/result", set(s) == SOLVER_KEYS, f"实际 {set(s)}"))
    results.append(check("math_solver 没有 latex 字段（线上不存在）", "latex" not in s))
    results.append(check("math_solver 的 result 是纯文本 sympy 串", s["result"] == "3*x**2 + 2", s["result"]))

    # ── IR 落盘不得改动工具返回值 ────────────────────────────────────────
    # 曾经的 _prune 无差别递归，把观测里的 None / [] / "" 一并剪掉：
    # calculator 失败的 result=None、recommend_practice 空结果的 recommendations=[]
    # 全部丢失，落盘的观测线上永远不会出现。这条来回跑一遍钉住它。
    import json
    import tempfile

    from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_samples

    payload = {"expression": "1/0", "result": None, "error": "除零错误",
               "recommendations": [], "note": ""}
    probe = Sample(
        id="rt1", template_id="rt", category="tool_error", schema_version="x",
        system="s", tool_names=["calculator"],
        turns=[
            Turn(role="user", content="算 1/0"),
            Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "1/0"})]),
            Turn(role="tool_result", results=[ToolResult("calculator", payload, is_error=True)]),
            Turn(role="assistant", content="分母是 0，算不了。"),
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "rt.jsonl"
        dump_samples([probe], f)
        back = load_samples(f)[0].turns[2].results[0]
        raw = json.loads(f.read_text(encoding="utf-8"))["turns"][2]["results"][0]["content"]
    results.append(check("IR 落盘不改动工具返回值（None/[]/\"\" 都要留着）",
                         back.content == payload and raw == payload, f"实际 {raw}"))
    results.append(check("IR 落盘保留 is_error 标记", back.is_error is True))

    # --- observation 序列化必须逐字匹配后端 serialize_tool_result ---
    #
    # 探针值和期望输出由 tools/capture_math_outputs.py 跑**后端真实函数**抓来。
    # 最容易漏的是返回字符串的工具：`str("北京: 26 摄氏度 晴朗")` 是裸串，
    # `json.dumps(...)` 会带一对双引号。load_skill / get_time / get_weather
    # 和全部 `[Error]: ...` 失败观测都走这条路 —— 少了引号就是模型没见过的格式，
    # 而且没有任何校验拦得住（5.10 / 5.12 就是这么过关的）。
    from esa.render import _serialize_result

    cache = Path(__file__).resolve().parents[2] / "dataset/data/cache/math_real.json"
    golden = json.loads(cache.read_text(encoding="utf-8"))
    fmt = golden.get("observation_format")
    if not fmt:
        results.append(check("observation 序列化黄金样例存在", False,
                             "math_real.json 里没有 observation_format，重跑 capture_math_outputs.py"))
    else:
        bad = []
        for case in fmt:
            got = _serialize_result(case["probe"])
            if got != case["expected"]:
                bad.append(f"后端 {case['expected']!r} / 我们 {got!r}")
        results.append(check(
            f"observation 序列化与后端逐字一致（{len(fmt)} 条探针）",
            not bad, "；".join(bad[:3])))

    ok = sum(results)
    print(f"\n{ok} 通过 / {len(results) - ok} 失败")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
