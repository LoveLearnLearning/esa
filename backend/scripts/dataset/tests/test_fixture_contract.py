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

import json
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
# ⚠️ 2026-08-15 更新：原来这里少了 has_record / retention / evidence_confidence
# 三个字段——因为它抄的是 fixtures 那份不完整的复刻，不是后端。
# 后端是 `{**point, "reasons": ..., "weak_prerequisites": weak}`，整个 point 展开。
# **这组常量已不是权威**，权威是下面 check_against_real_captures() 对着
# data/cache/learning_real.json 的比对；留着它只是为了报错时定位更快。
RECOMMEND_ITEM = {
    "kp_id", "name", "course", "weight", "mastery_level", "has_record",
    "retention", "evidence_confidence",
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
# 同上：线上每项 8 个键，原来只写了 4 个。
WEAK_PREREQ = {"kp_id", "name", "course", "depth", "mastery_level",
               "status", "retention", "evidence_confidence"}

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

    # --- 对着真实抓取校验结构（2026-08-15 新增，这是本文件的权威部分）---
    results.extend(check_against_real_captures())

    ok = sum(results)
    print(f"\n{ok} 通过 / {len(results) - ok} 失败")
    return 0 if ok == len(results) else 1


# ==========================================================================
# 对着真实抓取校验 —— 这一节是 2026-08-15 补的，起因值得写下来
# ==========================================================================
#
# 上面那些 `*_KEYS` 常量是**手抄后端源码**的（抄的是 2026-08-10 快照）。
# 手抄的东西会过期，而过期了**没有任何东西会说话**：
#
#   2026-08-15 发现 167 条样本的 observation 结构与线上不符，其中
#   多条学情样本（旧写入载荷键不同、get_review_timing 多两个键、
#   get_weak_prerequisites 少了外层包装）**从一开始就是错的**，
#   而这个文件的 33 项契约一直全绿 —— 因为它钉的是 fixtures 自己的形状。
#
# 所以判据换成：**fixtures 的输出结构 == 真实抓取的结构**。
# 真实抓取由 tools/capture_learning_tools.py 和 capture_memory_tools.py 产出，
# 它们在临时 SQLite 上跑后端真实 service，不是复刻。
#
# 只比**结构**不比数值：后端 apply_evidence 带时间衰减，数值不是逐日可复现的；
# 数值由 fixtures 的确定性哈希提供，保证语料字节可复现。
# ==========================================================================


def _shape(value):
    """与 capture_learning_tools.shape 同一套抽象：只留键名与类型。"""
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


# 这些路径下的**键是数据不是 schema**（键名由内容决定），逐键比对没有意义。
# error_type_counts 的键是错误类型名，真实抓取里恰好是空 dict，
# 硬比会报"我们多了 conceptual/procedural"——那是假阳性。
VALUE_KEYED_PATHS = {"error_type_counts"}


def _keys_deep(shape, prefix=""):
    """把结构摊平成 `a.b.c` 形式的键集合，便于报出差在哪一层。"""
    out = set()
    if isinstance(shape, dict):
        for k, v in shape.items():
            path = f"{prefix}{k}"
            out.add(path)
            if k in VALUE_KEYED_PATHS:
                continue  # 键是数据，不往下摊
            out |= _keys_deep(v, f"{path}.")
    elif isinstance(shape, list) and shape:
        out |= _keys_deep(shape[0], f"{prefix}[].")
    return out


def _empty_paths(value, prefix=""):
    """收集"空容器"的路径 —— 空列表/空 dict 推不出元素结构，不能拿来判失败。"""
    out = set()
    if isinstance(value, dict):
        if not value:
            out.add(prefix.rstrip("."))
        for k, v in value.items():
            out |= _empty_paths(v, f"{prefix}{k}.")
    elif isinstance(value, list):
        if not value:
            out.add(f"{prefix.rstrip('.')}.[]")
        else:
            out |= _empty_paths(value[0], f"{prefix}[].")
    return out


# 每条 case 的 key 是 `工具名` 或 `工具名#分支`（分支对应 capture 里的 branch 字段）。
# 记忆侧必须逐分支比：save_core_memory 有 created / unchanged /
# confirmation_required 三种截然不同的返回，只比第一个等于没比。
CAPTURE_CASES = {
    "learning_real.json": {
        "recommend_practice": lambda: fixtures.recommend_practice("操作系统", 2),
        "get_mastery_report": lambda: fixtures.get_mastery_report("操作系统"),
        "get_mastery_level": lambda: fixtures.get_mastery_level("进程调度"),
        "get_weak_prerequisites": lambda: fixtures.get_weak_prerequisites_tool("死锁"),
        "get_review_timing": lambda: fixtures.get_review_timing("进程调度"),
        "record_learning_evidence": lambda: fixtures.record_learning_evidence(
            "进程调度", "practice", correct=True
        ),
        "get_learning_evidence_summary": fixtures.get_learning_evidence_summary,
        # ↓ 2026-08-19 补。这三条是**执行器包出来的失败观测**，不是工具返回值：
        # 后端 `_canonical_kp_id` / `weeks_to_exam` 校验抛 ValueError，被
        # `BoundToolExecutor` 接住转成 dict（capability_runtime.py:193-199），
        # 模型看见的就是这个 dict。fixtures 原来对这几种输入**照常返回成功载荷**
        # （unseen / has_record=false），等于比线上宽松 —— 拿它造样本会造出
        # 一个线上不存在的观测。
        # 「队列」在真实图谱里、但 fixtures 的确定性画像里没有它的记录 ——
        # 两边都走 has_record=false 那一支，比的才是同一件事（见 capture 脚本里的说明）。
        "get_mastery_level#no_record": lambda: fixtures.get_mastery_level("队列"),
        "get_mastery_level#unknown_kp":
            lambda: fixtures.get_mastery_level("binary tree traversal"),
        "get_mastery_level#empty_kp": lambda: fixtures.get_mastery_level(""),
        "recommend_practice#negative_weeks":
            lambda: fixtures.recommend_practice("操作系统", -2),
    },
    "memory_real.json": {
        "save_core_memory#created":
            lambda: fixtures.save_core_memory("study_time_preference", "倾向晚上学习", "preference"),
        "save_core_memory#unchanged":
            lambda: fixtures.save_core_memory(
                "response_style", "喜欢先看直观例子，再看公式推导", "preference"),
        "save_core_memory#confirmation_required":
            lambda: fixtures.save_core_memory(
                "response_style", "改成先看公式推导再看例子", "preference"),
        # 这两条是**执行器包出来的失败观测**，不是工具返回值。
        # 线上可达（normal 模式也会发生），与"会话模式阻断"是两回事。
        "save_core_memory#sensitive":
            lambda: fixtures.save_core_memory("api_cred", "我的 api_key 是 sk-abc123", "general"),
        "save_core_memory#empty_content":
            lambda: fixtures.save_core_memory("blank_one", "   ", "general"),
        "save_core_memory#key_normalized":
            lambda: fixtures.save_core_memory(
                "Preferred Code Language", "平时写 Python", "preference"),
        "propose_core_memory":
            lambda: fixtures.propose_core_memory("study_pace", "倾向每天固定两小时", "preference"),
        "get_core_memories": fixtures.get_core_memories,
        "delete_core_memory#ok":
            lambda: fixtures.delete_core_memory(fixtures.CORE_MEMORIES[0]["memory_id"]),
    },
}


def check_against_real_captures() -> list[bool]:
    """逐个工具比对 fixtures 输出结构 vs 真实抓取结构。"""
    root = Path(__file__).resolve().parents[2]
    results: list[bool] = []

    for cache_name, tools in CAPTURE_CASES.items():
        path = root / "dataset/data/cache" / cache_name
        if not path.exists():
            script = ("capture_memory_tools.py" if "memory" in cache_name
                      else "capture_learning_tools.py")
            results.append(check(
                f"{cache_name} 存在", False,
                f"缺 {path}，跑 dataset/tools/{script}",
            ))
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        real = {}
        for c in payload["calls"]:
            if c.get("mode") != "normal" or "result" not in c:
                continue
            for key in (f"{c['tool']}#{c['branch']}" if c.get("branch") else c["tool"],
                        c["tool"]):
                real.setdefault(key, c["result"])

        for tool, fn in tools.items():
            if tool not in real:
                results.append(check(
                    f"{tool} 有真实抓取样例", False,
                    f"{cache_name} 里没有 normal 模式的 {tool}，补进 capture 脚本",
                ))
                continue
            try:
                ours = fn()
            except Exception as exc:  # noqa: BLE001
                results.append(check(
                    f"{tool} 结构与线上一致", False,
                    f"fixtures 调用失败：{type(exc).__name__}: {exc}",
                ))
                continue
            # 一侧为空容器时推不出元素结构 —— 那不是不一致，是**没法比**。
            # 把这类路径排除掉再判，否则测试会喊狼来了，
            # 而一个只会误报的测试和不报警的测试一样糟。
            blind = _empty_paths(real[tool]) | _empty_paths(ours)

            def _visible(keys):
                return {
                    k for k in keys
                    if not any(k == b or k.startswith(b.rstrip("[]").rstrip(".") + ".") for b in blind)
                }

            rk = _visible(_keys_deep(_shape(real[tool])))
            ok_ = _visible(_keys_deep(_shape(ours)))
            missing = sorted(rk - ok_)
            extra = sorted(ok_ - rk)
            detail = ""
            if missing:
                detail += f"线上有我们没有：{missing[:6]}　"
            if extra:
                detail += f"我们有线上没有：{extra[:6]}"
            if blind and not (missing or extra):
                detail = f"（{len(blind)} 处因一侧为空未能比对）"
            results.append(check(
                f"{tool} 结构与线上一致", not (missing or extra), detail,
            ))

    results.extend(check_memory_behaviour(root))
    return results


def check_memory_behaviour(root: Path) -> list[bool]:
    """记忆侧那些「结构对了也可能是错的」的事实，逐条钉住。

    结构比对查不出：检索命不命中、删不存在的 id 会怎样、受限模式下工具在不在表里。
    这三件恰好是上一版错得最离谱的地方。
    """
    results: list[bool] = []
    path = root / "dataset/data/cache/memory_real.json"
    if not path.exists():
        return [check("memory_real.json 存在", False, "跑 dataset/tools/capture_memory_tools.py")]
    payload = json.loads(path.read_text(encoding="utf-8"))

    # ① 检索命中集合必须与真实抓取逐条一致。
    #    上一版的 `hits or pool[:2]` 兜底保证永远非空 —— 48 条样本因此全是虚构的。
    matrix = payload.get("search_matrix", {})
    bad = []
    for query, hits in matrix.items():
        want = [h["memory_key"] for h in hits]
        try:
            got = [m["memory_key"] for m in fixtures.search_core_memories(query)]
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{query}: {type(exc).__name__}")
            continue
        if got != want:
            bad.append(f"{query}: 线上 {want} / 我们 {got}")
    results.append(check(
        f"检索命中集合与线上一致（{len(matrix)} 个 query，"
        f"其中 {sum(1 for h in matrix.values() if not h)} 个真实落空）",
        not bad, "；".join(bad[:3])))

    # ② 没抓过的 query 必须抛错，不能就地编一个命中结果。
    try:
        fixtures.search_core_memories("这个词没有抓过_zzz")
        results.append(check("未抓过的 query 会抛错而不是编结果", False, "居然返回了"))
    except Exception:  # noqa: BLE001
        results.append(check("未抓过的 query 会抛错而不是编结果", True))

    # ③ delete 不存在的 id：线上抛 KeyError 且**没有任何一层接住**，
    #    整轮 agent run 会失败。复刻它，免得又造出"删除失败"这种线上没有的样本。
    real_missing = [c for c in payload["calls"]
                    if c["tool"] == "delete_core_memory" and c.get("branch") == "missing"]
    if real_missing and "raises" in real_missing[0]:
        want_type = real_missing[0]["raises"]["type"]
        try:
            fixtures.delete_core_memory("does-not-exist")
            results.append(check(f"delete 不存在的 id 抛 {want_type}", False, "居然正常返回了"))
        except Exception as exc:  # noqa: BLE001
            results.append(check(f"delete 不存在的 id 抛 {want_type}",
                                 type(exc).__name__ == want_type, f"实际 {type(exc).__name__}"))

    # ④ 受限模式下记忆工具**不在工具表里** —— 样本的 tool_names 必须照这个来。
    availability = payload.get("tool_availability", {})
    for mode, expect_memory in (("normal", True), ("no_write", True), ("isolated", False)):
        names = availability.get(mode, [])
        mem = [n for n in names if "core_memor" in n]
        results.append(check(
            f"{mode} 模式工具表：{len(names)} 个，记忆工具 {len(mem)} 个",
            bool(names) and (bool(mem) == expect_memory),
            f"实际 {mem}"))
    write_tools = {"save_core_memory", "propose_core_memory", "delete_core_memory"}
    results.append(check(
        "no_write 模式下写记忆工具已被移出工具表",
        not (write_tools & set(availability.get("no_write", []))),
        f"仍在表里：{sorted(write_tools & set(availability.get('no_write', [])))}"))

    # ⑤ 学情阻断载荷：键数与 reason 原文都要对上（reason 是英文，别翻译）。
    lpath = root / "dataset/data/cache/learning_real.json"
    if lpath.exists():
        lcalls = json.loads(lpath.read_text(encoding="utf-8"))["calls"]
        real_blocked = {
            (c["mode"], c["tool"]): c["result"]
            for c in lcalls
            if c["mode"] != "normal"
            and "result" in c
            and c["tool"] in fixtures.BLOCKED_BUILDERS
        }
        bad = []
        for (mode, tool), want in real_blocked.items():
            if not isinstance(want, dict) or want.get("allowed", True) and want.get("saved", True):
                continue  # 不是阻断分支（no_write 下的读工具会正常返回）
            try:
                got = fixtures.blocked_learning(tool, mode=mode)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{mode}/{tool}: {type(exc).__name__}")
                continue
            if got != want:
                bad.append(f"{mode}/{tool}: 线上 {want} / 我们 {got}")
        results.append(check(
            f"学情阻断载荷逐字与线上一致（{len(real_blocked)} 个模式×工具）",
            not bad, "；".join(bad[:3])))

    return results


if __name__ == "__main__":
    sys.exit(main())
