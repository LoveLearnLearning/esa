# backend/scripts/dataset/esa/fixtures.py

"""学情类工具的测试数据库 —— 严格复刻后端实现。

⚠️ 这个文件的每一个公式、字段名、取整位数都必须和后端一致，否则模型会学会消费一个
线上永远不会出现的结构。**改动前先核对源码。**

复刻自 github.com/LoveLearnLearning/esa（2026-08-10 快照）：
  backend/agent/memories/mastery_store.py    _row_state / get_report / get_priority_ranking
  backend/agent/learning/student_model.py    retention / evidence_confidence / status
  backend/agent/tools/mastery_tools.py       recommend_practice / get_mastery_report 的外层包装
  backend/core/utils/models.py               UserRecord.TOTAL_WEEKS_DEFAULT

初版是我自己编的公式（0.45*掌握度 + 0.25*权重 + 0.20*紧急度 + 0.10*前置），
字段名用的是 mastery / reason(字符串)，与真实的 mastery_level / reasons(数组) 完全对不上，
而且整个漏掉了 review_pressure 这一项。已按真实实现重写。

学生画像仍由 kp_id 确定性生成（同一 kp_id 永远得到同一数值），保证同一知识点在所有
样本里数值一致 —— 但**结构**现在与生产完全一致。等知识图谱负责人提供真实后端的批量导出后，
把数值换成真实的即可，结构不用再动。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from math import exp, log
from pathlib import Path
from typing import Any

import yaml

from .tools_exec import ToolError

ROOT = Path(__file__).resolve().parents[2]
from .paths import DATASET_DIR, repo_root  # noqa: E402

# 知识图谱可能在两个位置，取决于这份代码待在哪个仓库里：
#   1. 合进 ESA 后端仓库时  backend/agent/memories/data/knowledge_graph/
#   2. 独立数据集仓库时     仓库根目录
# 两处内容逐字节一致（2026-08-11 核对过）。**优先用后端那份** ——
# 合进后端仓库之后不该再留一份副本：两个事实来源正是这个项目反复栽跟头的地方
# （根目录那份 16 工具的 tool_schemas.json 就是现成的教训）。
# 知识图谱是**后端自己的**东西，不在 dataset/ 里，所以要从外层仓库根往下找。
#
# ⚠️ 这里以前写的是 `ROOT / "backend" / ...`，而 ROOT 是"本文件往上两级"。
# 数据集待在仓库根下时那恰好等于仓库根；一旦搬进 `backend/scripts/dataset/`，
# 它就变成了 `backend/scripts`，于是去找 `backend/scripts/backend/agent/...`——不存在。
# 组长要求的正是搬进 backend/scripts/，所以改成真的去找仓库根（认 backend/ 或 .git）。
KG_DIRS = [
    repo_root() / "backend" / "agent" / "memories" / "data" / "knowledge_graph",
    repo_root(),      # 独立发布仓库：知识图谱直接躺在根上
    DATASET_DIR.parent,  # 兜底：数据集的上一级
]


def kg_files() -> list[Path]:
    """定位知识图谱。找不到就抛错，不要静默退化成空图谱。"""
    for d in KG_DIRS:
        if (d / "core_courses.yaml").exists():
            return [d / "core_courses.yaml", d / "elective_courses.yaml"]
    raise ToolError(
        "找不到知识图谱 core_courses.yaml。找过：" + "、".join(str(d) for d in KG_DIRS)
    )

# --- backend/agent/learning/student_model.py 的常量 ---
MIN_MASTERY = 5.0
MAX_MASTERY = 98.0
PRIOR_MASTERY = 50.0
INITIAL_STABILITY_DAYS = 4.0
MIN_STABILITY_DAYS = 1.5
REVIEW_THRESHOLD = 0.65

# --- backend/core/utils/models.py ---
TOTAL_WEEKS_DEFAULT = 18

# 生成学生画像用的固定"当前时间"。必须固定，否则同一样本在不同日期重跑会得到不同的
# retention，数据就不可复现了（赛题明确要求可复现）。
NOW = datetime(2026, 8, 10, 12, 0, 0)


def _det_unit(*parts: str) -> float:
    """处理 `_det_unit` 相关逻辑。"""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") / 2**32


def _det_hex(seed: str, length: int) -> str:
    """确定性的十六进制 id。

    后端的 evidence id 是随机 uuid4().hex，每次都不一样；我们这边必须
    **字节可复现**（否则每次重跑数据都变、diff 没法用），所以用哈希代替。
    这正是「capture 钉结构、fixtures 供取值」那条分工的具体体现。
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


# --------------------------------------------------------------------------
# student_model.py 的三个纯函数
# --------------------------------------------------------------------------


def evidence_confidence(evidence_weight: float) -> float:
    """处理 `evidence_confidence` 相关逻辑。"""
    return 1.0 - exp(-max(0.0, evidence_weight) / 3.5)


def retention(*, last_practiced_at: str, stability_days: float, now: datetime | None = None) -> float:
    """处理 `retention` 相关逻辑。

    Args:
        last_practiced_at: str => `last_practiced_at` 参数。
        stability_days: float => `stability_days` 参数。
        now: datetime | None => `now` 参数。

    Returns:
        float => 处理结果。
    """
    current = now or NOW
    last = datetime.fromisoformat(last_practiced_at)
    days = max(0.0, (current - last).total_seconds() / 86400.0)
    return 2.0 ** (-days / max(0.01, stability_days))


def status(mastery: float | None, confidence: float) -> str:
    """处理 `status` 相关逻辑。

    Args:
        mastery: float | None => `mastery` 参数。
        confidence: float => `confidence` 参数。

    Returns:
        str => 处理结果。
    """
    if mastery is None or confidence <= 0.0:
        return "unseen"
    if mastery < 40.0:
        return "weak"
    if mastery < 70.0:
        return "learning"
    if mastery < 85.0:
        return "good"
    return "mastered"


def days_until_threshold(*, stability_days: float, threshold: float | None = None) -> float:
    """处理 `days_until_threshold` 相关逻辑。

    Args:
        stability_days: float => `stability_days` 参数。
        threshold: float | None => `threshold` 参数。

    Returns:
        float => 处理结果。
    """
    t = min(max(REVIEW_THRESHOLD if threshold is None else threshold, 0.01), 0.99)
    return -stability_days * log(t) / log(2.0)


# --------------------------------------------------------------------------
# 知识图谱（知识图谱负责人构建，本仓库根目录）
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_kg() -> dict[str, Any]:
    """返回 {points: {kp_id: {...}}, by_course: {course: [kp_id]}, prereq: {kp: [前置]}}"""
    points: dict[str, dict] = {}
    by_course: dict[str, list[str]] = {}
    prereq: dict[str, list[str]] = {}
    for f in kg_files():
        for c in yaml.safe_load(f.read_text(encoding="utf-8"))["courses"]:
            course = c["course"]
            by_course[course] = [p["id"] for p in c["points"]]
            for p in c["points"]:
                points[p["id"]] = {"id": p["id"], "name": p["name"], "course": course, "weight": p["weight"]}
            # 边格式 [后继, 前置]
            for a, b in (c.get("prerequisites") or []):
                prereq.setdefault(a, []).append(b)
    return {"points": points, "by_course": by_course, "prereq": prereq}


def known_courses() -> list[str]:
    """处理 `known_courses` 相关逻辑。"""
    return sorted(load_kg()["by_course"])


# --------------------------------------------------------------------------
# 确定性学生画像 → _row_state 形状
# --------------------------------------------------------------------------


@lru_cache(maxsize=4)
def load_states(user_name: str = "stu_demo") -> dict[str, dict]:
    """产出与 mastery_store._row_state 完全同构的记录。

    真实库里 evidence_weight=0 的行不会被 list_for_user 返回，所以这里也让约 15%
    的知识点"无记录"，好让模型见到 mastery_level=None 的真实情况。
    """
    kg = load_kg()
    out: dict[str, dict] = {}
    for kp_id in kg["points"]:
        if _det_unit(user_name, kp_id, "seen") < 0.15:
            continue  # 无学习证据，list_for_user 不会返回
        mastery = MIN_MASTERY + _det_unit(user_name, kp_id, "m") * (MAX_MASTERY - MIN_MASTERY)
        stability = MIN_STABILITY_DAYS + _det_unit(user_name, kp_id, "s") * 12.0
        weight_ev = 0.5 + _det_unit(user_name, kp_id, "w") * 9.5
        days_ago = _det_unit(user_name, kp_id, "d") * 30.0
        last = (NOW - timedelta(days=days_ago)).isoformat(sep=" ", timespec="seconds")
        conf = evidence_confidence(weight_ev)
        ret = retention(last_practiced_at=last, stability_days=stability)
        practice = int(1 + _det_unit(user_name, kp_id, "p") * 12)
        out[kp_id] = {
            "user_name": user_name,
            "kp_id": kp_id,
            "has_record": conf > 0.0,
            "mastery_level": round(mastery, 2),
            "retention": round(ret, 3),
            "evidence_confidence": round(conf, 3),
            "stability_days": round(stability, 2),
            "evidence_weight": round(weight_ev, 4),
            "status": status(mastery, conf),
            "needs_review": conf >= 0.20 and ret < REVIEW_THRESHOLD,
            "practice_count": practice,
            "correct_count": int(practice * (0.3 + mastery / 200.0)),
            "last_practiced_at": last,
            "created_at": (NOW - timedelta(days=days_ago + 30)).isoformat(sep=" ", timespec="seconds"),
            "updated_at": last,
            "model_version": 1,
        }
    return out


def get_weak_prerequisites(user_name: str, kp_id: str, mastery_threshold: float = 50.0,
                           max_depth: int = 5) -> list[dict]:
    """复刻 EsaMasteryStore.get_weak_prerequisites：只保留 depth>0 且掌握度低于阈值的前置。"""
    kg, states = load_kg(), load_states(user_name)
    out, seen, frontier, depth = [], {kp_id}, [kp_id], 0
    while frontier and depth < max_depth:
        depth += 1
        nxt = []
        for node in frontier:
            for pre in kg["prereq"].get(node, []):
                if pre in seen:
                    continue
                seen.add(pre)
                nxt.append(pre)
                st = states.get(pre)
                if st is not None and float(st["mastery_level"]) < mastery_threshold:
                    # 线上每项有 8 个键（见 data/cache/learning_real.json）：
                    # 原来只写了 4 个，course / status / retention /
                    # evidence_confidence 三处缺失让样本里的观测比线上窄。
                    out.append({
                        "kp_id": pre,
                        "name": kg["points"][pre]["name"],
                        "course": kg["points"][pre].get("course", ""),
                        "depth": depth,
                        "mastery_level": st["mastery_level"],
                        "status": st.get("status", "learning"),
                        "retention": st.get("retention"),
                        "evidence_confidence": st.get("evidence_confidence", 0.0),
                    })
        frontier = nxt
    return out


# --------------------------------------------------------------------------
# 工具实现（外层包装复刻 mastery_tools.py）
# --------------------------------------------------------------------------


def _build_reasons(point: dict, weak_prereqs: list[dict], weeks_to_exam: int, total_weeks: int) -> list[str]:
    """逐字复刻 mastery_tools._build_reasons —— 措辞也一样，模型要学的就是消费这些字符串。"""
    reasons: list[str] = []
    raw = point.get("mastery_level")
    mastery = None if raw is None else float(raw)
    weight = float(point.get("weight", 0.0))
    if mastery is None:
        reasons.append("尚无学习证据")
    elif mastery < 50.0:
        reasons.append(f"掌握度低(mastery={mastery:.1f})")
    if weight >= 0.7:
        reasons.append(f"考试权重高(weight={weight:.2f})")
    if total_weeks > 0 and weeks_to_exam <= total_weeks / 4:
        reasons.append(f"距期末仅 {weeks_to_exam} 周")
    if weak_prereqs:
        reasons.append(f"前置薄弱({len(weak_prereqs)} 个前置掌握度<50)")
    if not reasons:
        reasons.append("综合优先级排序推荐")
    return reasons


def _priority_ranking(user_name: str, course: str, weeks_to_exam: int, total_weeks: int) -> list[dict]:
    """处理 `_priority_ranking` 相关逻辑。"""
    kg, states = load_kg(), load_states(user_name)
    ids = kg["by_course"].get(course.strip())
    if not ids:
        return []
    exam_urgency = max(0.0, 1.0 - weeks_to_exam / total_weeks) if total_weeks > 0 else 0.0
    results = []
    for kp_id in ids:
        point = kg["points"][kp_id]
        st = states.get(kp_id)
        if st is None:
            mastery_need, review_pressure = 0.45, 0.0
            mastery_level = retention_v = None
            practice_count, confidence = 0, 0.0
        else:
            mastery_level = float(st["mastery_level"])
            mastery_need = 1.0 - mastery_level / 100.0
            retention_v = float(st["retention"])
            review_pressure = max(0.0, (REVIEW_THRESHOLD - retention_v) / REVIEW_THRESHOLD)
            practice_count = int(st["practice_count"])
            confidence = float(st["evidence_confidence"])
        weak = get_weak_prerequisites(user_name, kp_id)
        prerequisite_risk = min(1.0, len(weak) / 3.0)
        priority = (
            0.35 * mastery_need
            + 0.20 * review_pressure
            + 0.20 * float(point["weight"])
            + 0.15 * exam_urgency
            + 0.10 * prerequisite_risk
        )
        results.append({
            "kp_id": point["id"], "name": point["name"], "course": point["course"],
            "weight": point["weight"], "mastery_level": mastery_level, "retention": retention_v,
            "evidence_confidence": confidence, "practice_count": practice_count,
            "has_record": st is not None, "priority": round(priority, 4),
        })
    results.sort(key=lambda i: i["priority"], reverse=True)
    return results


def recommend_practice(course: str, weeks_to_exam: int, user_name: str = "stu_demo",
                       total_weeks: int = TOTAL_WEEKS_DEFAULT) -> dict[str, Any]:
    """处理 `recommend_practice` 相关逻辑。

    Args:
        course: str => `course` 参数。
        weeks_to_exam: int => `weeks_to_exam` 参数。
        user_name: str => `user_name` 参数。
        total_weeks: int => `total_weeks` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    # 后端在算之前先卡这一条（learning/runtime.py:121）。用户说「考试已经过了」
    # 时模型照做就会传负数 —— 属于「失败源于用户给的输入」，线上真会发生。
    if int(weeks_to_exam) < 0:
        return _exec_error("recommend_practice", "weeks_to_exam must be non-negative")
    ranking = _priority_ranking(user_name, course, weeks_to_exam, total_weeks)
    if not ranking:
        return {"allowed": True, "user_name": user_name, "course": course, "count": 0,
                "recommendations": [], "note": f"未找到课程 {course!r} 的知识点，请确认课程名"}
    recs = []
    for point in ranking[:5]:
        weak = get_weak_prerequisites(user_name, point["kp_id"])
        # 后端是 `{**point, "reasons": ..., "weak_prerequisites": weak}`
        # （learning/runtime.py 的 recommend_practice 分支）——**整个 point 展开**。
        # 原来这里手挑了 7 个字段，把 has_record / retention / evidence_confidence
        # 丢了，于是样本里的观测比线上少三个字段。照后端来，别再手挑。
        recs.append({
            **point,
            "reasons": _build_reasons(point, weak, weeks_to_exam, total_weeks),
            "weak_prerequisites": weak,
        })
    return {"allowed": True, "user_name": user_name, "course": course,
            "count": len(recs), "recommendations": recs}


def get_mastery_report(course: str = "", user_name: str = "stu_demo") -> dict[str, Any]:
    """课程名不存在时**返回空报告**，不抛错。

    ⚠️ 这里原来写的是 `raise ToolError("未找到课程 X，当前支持：…")` —— 那句话后端
    根本不存在。真实链路是 `mastery_store.get_report`（mastery_store.py:369-405）
    调 `kg_store.get_course_points`（knowledge_graph.py:266-286，一条普通 SQL），
    查不到就返回空列表，于是报告是 total_points=0 / avg_mastery=0.0 的空壳。
    和 `recommend_practice` 不一样：那边有 `note` 字段提示课程名可能写错，这边没有。
    """
    kg, states = load_kg(), load_states(user_name)
    course_arg = course.strip() if course else None
    if course_arg:
        ids = kg["by_course"].get(course_arg) or []
        points = [s for k, s in states.items() if k in set(ids)]
    else:
        points = list(states.values())
    weak = sorted(points, key=lambda i: i["mastery_level"])[:5]
    strong = sorted(points, key=lambda i: i["mastery_level"], reverse=True)[:5]
    stale = sorted([i for i in points if i["needs_review"]], key=lambda i: i["retention"])[:5]
    return {
        "allowed": True, "user_name": user_name, "course": course_arg,
        "total_points": len(points),
        "avg_mastery": round(sum(float(i["mastery_level"]) for i in points) / len(points), 2) if points else 0.0,
        "weak_points": weak, "strong_points": strong, "stale_points": stale,
    }


def _kp_error(tool: str, kp_id: Any) -> dict[str, Any] | None:
    """复刻 `learning/runtime.py:_canonical_kp_id`（:29-38）**经执行器之后**的样子。

    后端那个函数抛的是 `ValueError`，但 `BoundToolExecutor.execute` 把
    `(ValueError, RuntimeError)` 整个接住转成 dict（capability_runtime.py:193-199），
    **从不抛给 agent loop** —— 所以模型看见的是下面这个 dict，不是异常。
    2026-08-19 用真实 `CapabilityRuntime.compile().bind().execute()` 逐条跑过，
    结构由 `data/cache/learning_real.json` 钉住。

    ⚠️ 这里原来抛的是我们自编的中文 `ToolError("未知知识点 …")` —— 后端没有这句话。
    没出事只是因为当时没有样本传过非法 kp_id；而基线里 L3 的参数错误 **4/4**
    正是模型把 kp_id 写成了英文（`binary_tree_traversal`），线上必然走这一支。

    解析规则也逐条核过（`knowledge_graph.resolve_kp_id`）：去首尾空白后**精确匹配**，
    不做大小写折叠、不做别名扩展 —— 实测 `'cache'` 解析不到而 `'Cache'` 可以。
    """
    value = str(kp_id or "").strip()
    if not value:
        return _exec_error(tool, "kp_id must not be empty")
    if value not in load_kg()["points"]:
        return _exec_error(tool, f"unknown knowledge point {value!r}")
    return None


def get_mastery_level(kp_id: str, user_name: str = "stu_demo") -> dict[str, Any]:
    """获取 `mastery level` 相关数据。

    Args:
        kp_id: str => kp ID。
        user_name: str => `user_name` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    err = _kp_error("get_mastery_level", kp_id)
    if err is not None:
        return err
    st = load_states(user_name).get(kp_id)
    if st is None:
        return {"allowed": True, "user_name": user_name, "kp_id": kp_id, "mastery_level": None,
                "status": "unseen", "retention": None, "evidence_confidence": 0.0,
                "practice_count": 0, "correct_count": 0, "has_record": False}
    return {"allowed": True, **st}


def _apply_evidence_payload(
    *, kp_id: str, user_name: str, correct: bool, before: float, after: float,
    prev: dict[str, Any] | None, activity_type: str, evidence_reliability: float,
    hint_level: int = 0, attempts: int = 1, independent: Any = None,
    self_confidence: Any = None, recall_score: Any = None,
    explanation_score: Any = None, transfer_score: Any = None,
    error_type: Any = None, misconception: Any = None,
) -> dict[str, Any]:
    """`record_learning_evidence` 的规范返回体。

    ⚠️ 结构逐字对齐 `data/cache/learning_real.json` 里 `apply_evidence` 的真实返回：
    `{saved, evidence{16 字段}, state{20 字段}}`。

    原来这里返回的是 `{allowed, user_name, kp_id, correct, mastery_before,
    mastery_after, practice_count}` —— **七个键没有一个是线上有的**。
    生成器照着 `mastery_before → mastery_after` 渲染回答，等于教模型引用
    根本不存在的字段。这是 5.1（`mastery` vs `mastery_level`）的重演，
    只是这次没人发现：33 项契约钉的是本文件自己的形状，不是后端的。
    """
    practice_count = (prev["practice_count"] + 1) if prev else 1
    correct_count = (prev.get("correct_count", 0) if prev else 0) + (1 if correct else 0)
    stability = float(prev["stability_days"]) if prev else 1.0
    ev_id = _det_hex(f"{user_name}|{kp_id}|{practice_count}", 32)
    ts = NOW.isoformat(timespec="seconds")
    return {
        "saved": True,
        # 2026-08-19：后端加了幂等（`learning/runtime.py` 的 `_idempotency_key`），
        # 同一请求的完全相同重试会返回 duplicate=True 而不是重复计数。
        # 我们造的都是首次写入，所以恒 False —— 但**键必须在**，
        # 否则模型见到的字段集和线上对不上（`test_fixture_contract` 抓到的就是这个）。
        "duplicate": False,
        "evidence": {
            "duplicate": False,
            "id": ev_id,
            "user_name": user_name,
            "kp_id": kp_id,
            "activity_type": activity_type,
            "correct": correct,
            "self_confidence": self_confidence,
            "evidence_reliability": evidence_reliability,
            "hint_level": hint_level,
            "attempts": attempts,
            "independent": independent,
            "recall_score": recall_score,
            "explanation_score": explanation_score,
            "transfer_score": transfer_score,
            "error_type": error_type,
            "misconception": misconception,
            "created_at": ts,
        },
        "state": {
            "user_name": user_name,
            "kp_id": kp_id,
            "has_record": True,
            "mastery_level": round(after, 2),
            "retention": round(float(prev["retention"]) if prev else 1.0, 4),
            "evidence_confidence": round(min(1.0, 0.2 * practice_count), 4),
            "stability_days": round(stability, 2),
            "evidence_weight": round(min(1.0, 0.25 * practice_count), 4),
            "status": "learning" if after < 80 else "mastered",
            "needs_review": False,
            "practice_count": practice_count,
            "correct_count": correct_count,
            "last_practiced_at": ts,
            "created_at": (prev.get("created_at") if prev else ts) or ts,
            "updated_at": ts,
            "model_version": 1,
            "old_mastery": round(before, 2),
            "mastery_delta": round(after - before, 2),
            "signal_performance": 1.0 if correct else 0.0,
            "evidence_quality": round(evidence_reliability, 4),
        },
    }


# --------------------------------------------------------------------------
# 后续新增的 5 个工具（仓库 2026-08-10 快照）
# --------------------------------------------------------------------------


def get_weak_prerequisites_tool(kp_id: str, mastery_threshold: float = 50.0, max_depth: int = 5,
                                user_name: str = "stu_demo") -> dict[str, Any]:
    """外层包装见 mastery_tools.get_weak_prerequisites。"""
    err = _kp_error("get_weak_prerequisites", kp_id)
    if err is not None:
        return err
    items = get_weak_prerequisites(user_name, kp_id, mastery_threshold, max_depth)
    # ⚠️ 外层只有三个键。原来这里多写了 user_name / kp_id，线上没有——
    # 由 data/cache/learning_real.json 的真实抓取钉住，见 test_fixture_contract。
    return {"allowed": True, "count": len(items), "weak_prerequisites": items}


def get_review_timing(kp_id: str, threshold: float = 0.7, user_name: str = "stu_demo") -> dict[str, Any]:
    """复刻 mastery_store.get_review_timing + 工具层包装。"""
    err = _kp_error("get_review_timing", kp_id)
    if err is not None:
        return err
    st = load_states(user_name).get(kp_id)
    # ⚠️ 线上没有 user_name / kp_id 这两个键（learning/runtime.py 的
    # get_review_timing 分支只是 {"allowed": True, **mastery.get_review_timing(...)}）。
    # 原来多写了，于是样本教模型引用不存在的字段。
    base = {"allowed": True}
    if st is None:
        return {**base, "has_record": False, "needs_review": False, "current_retention": None,
                "days_until_review": None, "recommended_date": None, "stability_days": None,
                "practice_count": 0}
    total_days = days_until_threshold(stability_days=float(st["stability_days"]), threshold=threshold)
    last = datetime.fromisoformat(st["last_practiced_at"])
    elapsed = max(0.0, (NOW - last).total_seconds() / 86400.0)
    remaining = max(0, int(total_days - elapsed))
    return {
        **base,
        "has_record": True,
        "needs_review": float(st["retention"]) < threshold,
        "current_retention": st["retention"],
        "days_until_review": remaining,
        "recommended_date": (NOW + timedelta(days=remaining)).date().isoformat(),
        "stability_days": st["stability_days"],
        "practice_count": st["practice_count"],
    }


ACTIVITY_TYPES = ["practice", "homework", "retrieval", "hint", "teach_back", "transfer", "review"]
ERROR_TYPES = ["conceptual", "procedural", "strategic", "representation", "prerequisite", "careless", "unknown"]


def record_learning_evidence(kp_id: str, activity_type: str, user_name: str = "stu_demo",
                             **kw) -> dict[str, Any]:
    """复刻 learning_state_service.record_event：返回 {saved, evidence, state}。

    归一化规则抄自 evidence_store.record：hint_level 夹到 [0,5]、attempts 至少 1、
    evidence_reliability 夹到 [0,1]、error_type 转小写。
    """
    err = _kp_error("record_learning_evidence", kp_id)
    if err is not None:
        return err
    if activity_type not in ACTIVITY_TYPES:
        raise ToolError(f"activity_type 必须是 {ACTIVITY_TYPES} 之一，收到 {activity_type!r}")
    err = (kw.get("error_type") or "").strip().lower() or None
    if err is not None and err not in ERROR_TYPES:
        raise ToolError(f"error_type 必须是 {ERROR_TYPES} 之一，收到 {err!r}")

    reliability = max(
        0.0,
        min(1.0, float(kw.get("evidence_reliability", 1.0))),
    )
    hint_level = max(0, min(5, int(kw.get("hint_level", 0))))
    attempts = max(1, int(kw.get("attempts", 1)))
    st = load_states(user_name).get(kp_id)
    before = float(st["mastery_level"]) if st else PRIOR_MASTERY
    correct = kw.get("correct")
    if correct is True:
        after = min(
            MAX_MASTERY,
            before + (MAX_MASTERY - before) * 0.25 * reliability,
        )
    elif correct is False:
        after = max(
            MIN_MASTERY,
            before - (before - MIN_MASTERY) * 0.30 * reliability,
        )
    else:
        after = before
    return _apply_evidence_payload(
        kp_id=kp_id,
        user_name=user_name,
        correct=correct,
        before=before,
        after=after,
        prev=st,
        activity_type=activity_type,
        evidence_reliability=reliability,
        hint_level=hint_level,
        attempts=attempts,
        independent=kw.get("independent"),
        self_confidence=kw.get("self_confidence"),
        recall_score=kw.get("recall_score"),
        explanation_score=kw.get("explanation_score"),
        transfer_score=kw.get("transfer_score"),
        error_type=err,
        misconception=kw.get("misconception"),
    )


def get_learning_evidence_summary(kp_id: str = "", limit: int = 50,
                                  user_name: str = "stu_demo") -> dict[str, Any]:
    """复刻 evidence_store.get_summary。空证据时所有均值字段是 None 而不是 0。"""
    kid = kp_id.strip() or None
    base = {"allowed": True, "user_name": user_name, "kp_id": kid}
    kg = load_kg()
    if kid and kid not in kg["points"]:
        return _exec_error("get_learning_evidence_summary", f"unknown knowledge point {kid!r}")

    # 确定性地造若干条证据
    n = 0 if (kid and _det_unit(user_name, kid, "ev") < 0.2) else int(3 + _det_unit(user_name, kid or "*", "n") * 20)
    n = min(n, limit)
    if n == 0:
        return {**base, "evidence_count": 0, "correct_rate": None, "avg_self_confidence": None,
                "avg_hint_level": None, "independent_rate": None, "avg_recall_score": None,
                "avg_explanation_score": None, "avg_transfer_score": None,
                "error_type_counts": {}, "recent_misconceptions": []}

    seed = kid or "*"
    r = lambda tag: round(_det_unit(user_name, seed, tag), 3)  # noqa: E731
    errs = {}
    for i, e in enumerate(ERROR_TYPES[:4]):
        c = int(_det_unit(user_name, seed, f"e{i}") * 4)
        if c:
            errs[e] = c
    return {
        **base, "evidence_count": n,
        "correct_rate": r("cr"), "avg_self_confidence": r("sc"),
        "avg_hint_level": round(_det_unit(user_name, seed, "hl") * 3, 3),
        "independent_rate": r("ind"), "avg_recall_score": r("rec"),
        "avg_explanation_score": r("exp"), "avg_transfer_score": r("tr"),
        "error_type_counts": errs,
        "recent_misconceptions": (
            ["把最坏情况当成平均情况", "递归边界少写一层"] if _det_unit(user_name, seed, "mis") > 0.5 else []
        ),
    }


# ==========================================================================
# CoreMemory —— 全部对着 data/cache/memory_real.json 复刻
#
# 2026-08-15 重写。上一版是这个文件里最后一块**凭想象写的**代码，
# 每一个函数的返回结构都和线上对不上：
#
#   函数                      上一版（错）                       线上真实
#   save_core_memory      {saved, memory_key, content, …}   {status, memory{15 字段}}
#                         恒"存成功"                          三分支：created / unchanged /
#                                                            **confirmation_required**
#   get_core_memories     {allowed, count, memories} dict    **list**，每项 15 字段
#   search_core_memories  dict，compact 四字段                **list**，每项 17 字段
#                         **搜不到时兜底返回前两条**             搜不到就是空
#   delete_core_memory    参数 memory_key，返回三个键          参数 **memory_id**，
#                         不存在返回 deleted:false            返回 {deleted: bool}，
#                                                            不存在**抛 KeyError**
#
# 那个兜底（`hits or pool[:2]`）是 48 条虚构样本的根源 —— 它保证检索永远非空，
# 于是"工具没返回东西时该怎么办"这件事，整个数据集一条都没教。
#
# 抓取脚本：tools/capture_memory_tools.py（跑真实 BoundToolExecutor）。
# ⚠️ 返回的是**执行器那一层**的值，也就是模型真正看得见的东西：
# 成功时就是工具返回值原样，失败时是 execute() 包出来的
# `{"ok": false, "error": ..., "tool": ..., "detail": ...}`
# （capability_runtime.py:179-199）。
# ==========================================================================

MEMORY_CACHE = ROOT / "dataset/data/cache/memory_real.json"

MEMORY_CATEGORIES = ["profile", "preference", "learning", "project", "constraint", "general"]

# 初始记忆库。必须与 capture_memory_tools.SEED_MEMORIES 逐字一致 ——
# 检索命中与否完全由字面决定，两边一有出入，search_matrix 就对不上号。
CORE_MEMORY_SEED = [
    ("learning_goal", "这学期把数据结构和算法吃透，准备考研", "learning"),
    ("response_style", "喜欢先看直观例子，再看公式推导", "preference"),
    ("major_info", "软件工程专业大三", "profile"),
    ("weak_topics", "图论相关的知识点普遍薄弱", "learning"),
    ("exam_schedule", "期末考试从第 16 周开始", "constraint"),
]

# 每条记忆的落库时间。线上是真实时间戳，我们要字节可复现，所以固定。
_MEMORY_CREATED_AT = {
    "learning_goal": "2026-07-28T10:12:00+00:00",
    "response_style": "2026-07-30T21:03:00+00:00",
    "major_info": "2026-06-15T09:00:00+00:00",
    "weak_topics": "2026-08-02T16:40:00+00:00",
    "exam_schedule": "2026-07-20T08:30:00+00:00",
}

# core_memory_service._KEY_RE（core_memory_service.py:21）
_MEMORY_KEY_RE = re.compile(r"[^a-z0-9_一-鿿]+")

# core_memory_policy._SENSITIVE（core_memory_policy.py:10-13）。
# 逐字复刻：训练数据里必须教模型「存不了凭据」这件事真实的说法。
_SENSITIVE_RE = re.compile(
    r"(?i)(password|passwd|验证码|session\s*id|api[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|cookie|private[_ -]?key|银行卡|信用卡)"
)


@lru_cache(maxsize=1)
def _memory_cache() -> dict[str, Any]:
    if not MEMORY_CACHE.exists():
        raise ToolError(
            f"找不到 {MEMORY_CACHE}。先跑 python3 dataset/tools/capture_memory_tools.py 抓真实观测。"
        )
    return json.loads(MEMORY_CACHE.read_text(encoding="utf-8"))


def _memory_key(value: str) -> str:
    """复刻 core_memory_service._key（:24-28）。

    模型传进去的 key 和库里存的可能不是一回事（"Preferred Code Language"
    会变成 "preferred_code_language"），所以回答里引用 key 必须用返回值里的那个。
    """
    normalized = _MEMORY_KEY_RE.sub("_", value.strip().casefold()).strip("_")
    if not normalized:
        raise ToolError("memory_key cannot be empty")
    return normalized[:64]


def _memory_record(memory_key: str, content: str, category: str,
                   revision: int = 1) -> dict[str, Any]:
    """CoreMemoryRecord.to_dict() 的 15 个字段，顺序照抓取。"""
    ts = _MEMORY_CREATED_AT.get(memory_key) or "2026-08-10T12:00:00+00:00"
    return {
        "memory_id": _det_hex(f"memory|{memory_key}", 32),
        "user_id": "stu_demo",
        "memory_key": memory_key,
        "content": content,
        "category": category,
        "scope_type": "global",
        "workspace_type": None,
        "status": "active",
        "source_type": "explicit_user",
        "revision": revision,
        "confirmed_at": ts,
        "review_after": None,
        "expires_at": None,
        "created_at": ts,
        "updated_at": ts,
    }


CORE_MEMORIES = [_memory_record(k, c, cat) for k, c, cat in CORE_MEMORY_SEED]
_BY_KEY = {m["memory_key"]: m for m in CORE_MEMORIES}
_BY_ID = {m["memory_id"]: m for m in CORE_MEMORIES}


def _denied(tool: str, detail: str) -> dict[str, Any]:
    """MemoryPolicyDenied 被 BoundToolExecutor 接住后的样子（capability_runtime.py:179-185）。

    ⚠️ 线上**不会**把这个异常抛给 agent loop，模型看到的就是这个 dict。
    """
    return {"ok": False, "error": "memory_policy_denied", "tool": tool, "detail": detail}


def _exec_error(tool: str, detail: str) -> dict[str, Any]:
    """ValueError / RuntimeError 被接住后的样子（capability_runtime.py:193-199）。"""
    return {"ok": False, "error": "tool_execution_error", "tool": tool, "detail": detail}


def tool_not_available(tool: str) -> dict[str, Any]:
    """工具不在本轮工具表里时的观测（capability_runtime.py:67-72）。

    受限会话下的记忆工具走的就是这条：`CapabilityRuntime.compile()` 在
    isolated 去掉全部 5 个记忆工具、no_write 去掉 3 个写工具
    （capability_runtime.py:245-250），模型的工具表里根本没有它们。
    """
    return {"ok": False, "error": "tool_not_available", "tool": tool}


def memory_tools_available(mode: str = "normal") -> list[str]:
    """某会话模式下模型能看见的工具名 —— 直接读抓取，不自己推。"""
    availability = _memory_cache().get("tool_availability", {})
    if mode not in availability:
        raise ToolError(
            f"memory_real.json 里没有 {mode!r} 模式的工具表，重跑 capture_memory_tools.py"
        )
    return list(availability[mode])


def memory_store(*keys: str) -> dict[str, dict[str, Any]]:
    """按需拼一个"当前记忆库"，用来指定某条样本的起始状态。

    走哪个分支完全取决于库里有没有这个 key、内容一不一样，所以
    「库里现在有什么」是**场景的一部分**，得由种子说了算，不能全局写死一份。
    `memory_store()` 空库 → 一定 created；`memory_store("response_style")` → 该 key 已存在。
    """
    missing = [k for k in keys if k not in _BY_KEY]
    if missing:
        raise ToolError(f"CORE_MEMORY_SEED 里没有 {missing}，先把它加进种子并重抓")
    return {k: _BY_KEY[k] for k in keys}


def save_core_memory(memory_key: str, content: str, category: str = "general",
                     scope_type: str = "global",
                     known: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """复刻 save_explicit（core_memory_service.py:196-234）经执行器后的观测。

    三个分支缺一不可，尤其第三个：**同一个 key 换内容不会直接覆盖**，
    而是产出一个待用户确认的 candidate。上一版恒返回"存成功了"，
    等于教模型在需要确认的时候谎报已保存。

    `known` 指定这条样本的起始记忆库，默认用完整的 CORE_MEMORIES。
    """
    if _SENSITIVE_RE.search(" ".join(content.split()).strip()):
        return _denied("save_core_memory", "sensitive credentials cannot be stored")
    normalized = " ".join(content.split()).strip()
    if not normalized:
        return _exec_error("save_core_memory", "memory content cannot be empty")
    if len(normalized) > 4000:
        return _exec_error("save_core_memory", "memory content is too long")
    if scope_type not in {"global", "workspace"}:
        return _denied("save_core_memory", "invalid memory scope")

    key = _memory_key(memory_key)
    existing = (_BY_KEY if known is None else known).get(key)
    if existing is None:
        return {"status": "created", "memory": _memory_record(key, normalized, category)}
    if _same_text(existing["content"], normalized) and existing["category"] == category:
        return {"status": "unchanged", "memory": dict(existing)}
    return {
        "status": "confirmation_required",
        "candidate": _memory_candidate(
            key, normalized, category,
            memory_id=existing["memory_id"], expected_revision=existing["revision"],
        ),
    }


def propose_core_memory(memory_key: str, content: str, category: str = "general",
                        scope_type: str = "global") -> dict[str, Any]:
    """复刻 propose_inferred（memory_tools.py:40-50）。恒返回待确认候选，不直接写入。"""
    if _SENSITIVE_RE.search(" ".join(content.split()).strip()):
        return _denied("propose_core_memory", "sensitive credentials cannot be stored")
    normalized = " ".join(content.split()).strip()
    if not normalized:
        return _exec_error("propose_core_memory", "memory content cannot be empty")
    key = _memory_key(memory_key)
    existing = _BY_KEY.get(key)
    return {
        "status": "confirmation_required",
        "candidate": _memory_candidate(
            key, normalized, category,
            memory_id=existing["memory_id"] if existing else None,
            expected_revision=existing["revision"] if existing else None,
        ),
    }


def _same_text(left: str, right: str) -> bool:
    """core_memory_service._same（:31-32）"""
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


def _memory_candidate(memory_key: str, content: str, category: str, *,
                      memory_id: str | None, expected_revision: int | None) -> dict[str, Any]:
    """MemoryCandidate.to_dict() 的 14 个字段。"""
    return {
        "candidate_id": _det_hex(f"candidate|{memory_key}|{content}", 32),
        "memory_id": memory_id,
        "memory_key": memory_key,
        "proposed_content": content,
        "category": category,
        "scope_type": "global",
        "workspace_type": None,
        "candidate_type": "replace" if memory_id else "create",
        "status": "pending",
        "expected_revision": expected_revision,
        "resulting_memory_id": None,
        # 线上是 now + 30 天（core_memory_service.py:229）。NOW 固定，所以这里也固定。
        "created_at": NOW.isoformat() + "+00:00",
        "decided_at": None,
        "expires_at": (NOW + timedelta(days=30)).isoformat() + "+00:00",
    }


def delete_core_memory(memory_id: str) -> dict[str, Any]:
    """复刻 forget（core_memory_service.py:329-…）经执行器后的观测。

    ⚠️ 参数是 **memory_id** 不是 memory_key —— 后端 2026-08-13 改的，
    而 id 只能来自 `search_core_memories` / `get_core_memories` 的返回值。
    也就是说「删掉我的学习目标」是个**两步**动作，模型不能一步删。

    ⚠️ id 不存在时线上**抛 KeyError**，而 `BoundToolExecutor.execute` 只接住
    MemoryPolicyDenied / PermissionError / ValueError / RuntimeError
    —— KeyError 会一路抛穿到 agent loop，整轮 run 直接失败。
    这是后端的 bug（已记入 docs/后端问题反馈.md），这里如实复刻：
    生成器碰到它会当场炸，而不是产出一条线上不存在的"删除失败"样本。
    """
    if memory_id not in _BY_ID:
        raise KeyError(memory_id)
    return {"deleted": True}


def get_core_memories() -> list[dict[str, Any]]:
    """复刻 list_visible（core_memory_service.py:110-114）。

    返回的是 **list**，不是 `{"count": n, "memories": [...]}`。
    要数数量就 `len(...)`，线上没有 count 字段。
    """
    return [dict(m) for m in CORE_MEMORIES]


def search_core_memories(query: str, category: str = "", limit: int = 5) -> list[dict[str, Any]]:
    """复刻 CoreMemoryRetrieval.rank 经执行器后的观测：**list**，每项 17 字段。

    命中判定不在这里算 —— 它来自 `data/cache/memory_real.json` 的 `search_matrix`，
    那是拿真实后端跑出来的。理由：后端检索是纯词法的
    （字符二元组重叠 + 短语 + key 精确匹配，core_memory_retrieval.py:42-75），
    在这里重写一遍必然慢慢漂移，而**漂移了没有任何东西会说话**。
    查不到就抛错，绝不退回本地实现猜一个 —— 这和三个计算器查表是同一条规矩。
    """
    matrix = _memory_cache().get("search_matrix", {})
    if query not in matrix:
        raise ToolError(
            f"memory_real.json 的 search_matrix 里没有 query={query!r}。\n"
            f"先把它写进 seeds/new_tools.yaml 的 search_core_memories 正例（query 字段），"
            f"再跑 dataset/tools/capture_memory_tools.py 重抓，不要就地编一个命中结果。"
        )
    out = []
    for hit in matrix[query][:limit]:
        record = _BY_KEY.get(hit["memory_key"])
        if record is None:
            raise ToolError(
                f"search_matrix 命中了 {hit['memory_key']!r}，但 CORE_MEMORY_SEED 里没有这条。"
                f"两边必须逐字一致，改了一边就要重抓。"
            )
        if category and record["category"] != category:
            continue
        out.append({**record, "score": hit["score"],
                    "estimated_tokens": hit["estimated_tokens"]})
    return out


# --------------------------------------------------------------------------
# 会话模式阻断（isolated / no_write）
#
# ⚠️ 2026-08-15 重写。上一版把**学情和记忆当成同一回事**，两边都写成
# 「工具正常返回、载荷里 allowed=False + 一句中文 reason」。跑真实
# BoundToolExecutor 之后发现这两件事的机制完全不同：
#
# 学情工具 —— 阻断确实是正常返回的载荷，但只有 2~3 个键，reason 是**英文**：
#     isolated + 读        {"allowed": false, "action": <名>, "reason": "isolated mode"}
#     非 normal + 写       {"saved": false, "reason": "conversation mode forbids writes"}
#   （tools/learning/runtime.py:25-30）。上一版多带了 user_name/course/count/
#   recommendations 一堆字段，reason 还是我们自己写的中文句子 ——
#   种子里的回答正文逐字引用了那句中文，也就是引用了一句线上不存在的话。
#
# 记忆工具 —— **根本没有阻断载荷这回事**。`CapabilityRuntime.compile()`
#   在编能力视图时就按模式把工具移出工具表（capability_runtime.py:245-250）：
#   isolated 去掉全部 5 个，no_write 去掉 3 个写工具。模型的工具表里没有它们，
#   所以正确行为是**压根不调**，而不是"调了被拒"。
#   真要硬调，得到的是 `{"ok": false, "error": "tool_not_available", ...}`。
#
# 判据全部来自 data/cache/memory_real.json 和 learning_real.json 的真实抓取。
# system prompt 里那句「isolated 会话不得通过 Tool 绕过隔离边界读取长期状态」
# （core/message/system.py），落地方式是**工具表里没有它** + 模型不去调。
# --------------------------------------------------------------------------

# tools/learning/runtime.py:25-30 的两句原文。是英文，不要翻译成中文写进观测。
LEARNING_READ_BLOCKED = "isolated mode"
LEARNING_WRITE_BLOCKED = "conversation mode forbids writes"

# 写工具：非 normal 模式一律走这一支。
LEARNING_WRITE_TOOLS = {"record_learning_evidence"}


def blocked_learning_read(action: str) -> dict[str, Any]:
    """isolated 会话里的学情**读**工具（runtime.py:25-26）。就三个键。"""
    return {"allowed": False, "action": action, "reason": LEARNING_READ_BLOCKED}


def blocked_learning_write() -> dict[str, Any]:
    """非 normal 会话里的学情**写**工具（runtime.py:27-30）。就两个键，且不含工具名。"""
    return {"saved": False, "reason": LEARNING_WRITE_BLOCKED}


def blocked_learning(tool: str, mode: str = "isolated") -> dict[str, Any]:
    """按会话模式给出学情工具的真实阻断观测。

    分支顺序照抄后端（`learning/runtime.py:108-114`）：
    **isolated 先判、对所有工具一视同仁**，然后才是「非 normal 且是写工具」。

    分支应持续与后端学习运行时保持一致。
    """
    if mode == "isolated":
        return blocked_learning_read(tool)
    if mode != "normal" and tool in LEARNING_WRITE_TOOLS:
        return blocked_learning_write()
    raise ToolError(f"{tool} 在 {mode} 模式下不会被阻断，别造这条样本")


BLOCKED_BUILDERS = {
    "recommend_practice": lambda **kw: blocked_learning("recommend_practice", **kw),
    "get_mastery_report": lambda **kw: blocked_learning("get_mastery_report", **kw),
    "get_mastery_level": lambda **kw: blocked_learning("get_mastery_level", **kw),
    "get_weak_prerequisites": lambda **kw: blocked_learning("get_weak_prerequisites", **kw),
    "get_review_timing": lambda **kw: blocked_learning("get_review_timing", **kw),
    "get_learning_evidence_summary":
        lambda **kw: blocked_learning("get_learning_evidence_summary", **kw),
    "record_learning_evidence": lambda **kw: blocked_learning("record_learning_evidence", **kw),
}


# --------------------------------------------------------------------------
# 外部工具
# --------------------------------------------------------------------------

ARXIV_CACHE = ROOT / "dataset/data/cache/arxiv_real.json"


@lru_cache(maxsize=1)
def _arxiv_cache() -> dict:
    """处理 `_arxiv_cache` 相关逻辑。"""
    if not ARXIV_CACHE.exists():
        return {}
    return json.loads(ARXIV_CACHE.read_text(encoding="utf-8"))


def arxiv_search(query: str, search_field: str = "all", max_results: int = 5,
                 sort_by: str = "relevance", sort_order: str = "descending") -> dict[str, Any]:
    """返回**真实**的 arXiv 检索结果，从 data/cache/arxiv_real.json 查表。

    绝不编造论文。赛题《02—伦理与安全合规性声明》要求承诺「输出内容不涉及伪造学术数据、
    虚假文献」—— 训练数据里编论文，等于教模型编引用。缓存由
    scripts/fetch_arxiv.py 调 arXiv 公开 API 生成，命中不了就抛错而不是造一个。
    """
    cache = _arxiv_cache()
    key = f"{search_field}|{query}"
    if key not in cache:
        raise ToolError(f"arxiv 缓存里没有 {key!r}，请先跑 scripts/fetch_arxiv.py 抓真实结果，不要编造")
    hit = cache[key]
    return {**hit, "results": hit["results"][:max_results],
            "result_count": min(hit["result_count"], max_results)}


def get_time() -> str:
    """复刻 tools.get_time。

    ⚠️ 后端实现是 datetime.now(timezone.utc).strftime("%D-%H:%M:%S")，有两个问题：
       1. %D 展开成 %m/%d/%y —— 美式日期 + 两位年份，"08/10/26" 有歧义
       2. 返回 UTC 而学生在东八区，"今天几号"会在午夜前后差一天
    这里如实复刻现状（训练数据必须匹配线上），问题已记入待办反馈给后端。
    """
    # NOW 是东八区的墙上时间，减 8 小时得到后端实际返回的 UTC；%D 即 %m/%d/%y
    return (NOW - timedelta(hours=8)).strftime("%m/%d/%y-%H:%M:%S")


def get_weather(city: str) -> str:
    """复刻 tools.get_weather —— 后端目前是硬编码桩，恒返回同一句。

    这不是我编的：backend/agent/tools/tools.py 里就是 f"{city}: 26 摄氏度 晴朗"。
    所以这个工具的样本只能训"何时该调"，训不了"如何消费真实天气"。
    """
    return f"{city}: 26 摄氏度 晴朗"


# web_search 的真实失败观测。
#
# ⚠️ 2026-08-15 重写。后端 `1b64473` 把 web_search 从本地 SearXNG **整个换成了
# You.com MCP 适配器**，原来那 5 条 SearXNG 文案（"搜索请求超时"、
# "SearXNG 返回 HTTP 502" 等）**在后端已经一条都不存在**。
# 我们有 5 条样本逐字引用它们，一夜之间全变成了线上永不出现的文案。
#
# ⚠️ 形状也变了。原来是 `tool_register.call` 包出来的字符串 `"[Error]: …"`；
# 现在 `capability_runtime.py` 给 web_search 开了专用分支
# （`if name == "web_search": return await execute_web_search(...)`），
# RuntimeError 在 :165 被接住，观测变成 **dict**：
#     {"ok": false, "error": "tool_execution_error", "tool": "web_search",
#      "detail": "You.com MCP search service is not configured"}
# 实测确认（跑真实 BoundToolExecutor，无 MCP manager 时）。
#
# 这一条只登记**我们能真的跑出来**的那个。另外两条
# （`You.com MCP search schema does not declare a query field`、
#  `搜索关键词不能为空`）要先接上 MCP 才可达，接上之前不造样本 ——
# 造了就是在猜线上什么时候会走到那里。
WEB_SEARCH_NOT_CONFIGURED = "You.com MCP search service is not configured"


def web_search_failed(detail: str = WEB_SEARCH_NOT_CONFIGURED) -> dict[str, Any]:
    """web_search 失败时模型看见的观测（执行器包装后的形状）。"""
    return _exec_error("web_search", detail)


FIXTURE_FUNCTIONS = {
    "arxiv_search": arxiv_search,
    "get_time": get_time,
    "get_weather": get_weather,
    "recommend_practice": recommend_practice,
    "get_mastery_report": get_mastery_report,
    "get_mastery_level": get_mastery_level,
    "get_weak_prerequisites": get_weak_prerequisites_tool,
    "get_review_timing": get_review_timing,
    "record_learning_evidence": record_learning_evidence,
    "get_learning_evidence_summary": get_learning_evidence_summary,
    "search_core_memories": search_core_memories,
    "get_core_memories": get_core_memories,
    "save_core_memory": save_core_memory,
    "propose_core_memory": propose_core_memory,
    "delete_core_memory": delete_core_memory,
}
