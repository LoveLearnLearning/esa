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
                    out.append({"kp_id": pre, "name": kg["points"][pre]["name"],
                                "mastery_level": st["mastery_level"], "depth": depth})
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
    ranking = _priority_ranking(user_name, course, weeks_to_exam, total_weeks)
    if not ranking:
        return {"allowed": True, "user_name": user_name, "course": course, "count": 0,
                "recommendations": [], "note": f"未找到课程 {course!r} 的知识点，请确认课程名"}
    recs = []
    for point in ranking[:5]:
        weak = get_weak_prerequisites(user_name, point["kp_id"])
        recs.append({
            "kp_id": point["kp_id"], "name": point["name"], "course": point["course"],
            "weight": point["weight"], "mastery_level": point["mastery_level"],
            "practice_count": point["practice_count"], "priority": point["priority"],
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


def get_mastery_level(kp_id: str, user_name: str = "stu_demo") -> dict[str, Any]:
    """获取 `mastery level` 相关数据。

    Args:
        kp_id: str => kp ID。
        user_name: str => `user_name` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    st = load_states(user_name).get(kp_id)
    if st is None:
        return {"allowed": True, "user_name": user_name, "kp_id": kp_id, "mastery_level": None,
                "status": "unseen", "retention": None, "evidence_confidence": 0.0,
                "practice_count": 0, "correct_count": 0, "has_record": False}
    return {"allowed": True, **st}


def record_answer(kp_id: str, correct: bool, confidence: float = 1.0,
                  user_name: str = "stu_demo") -> dict[str, Any]:
    """处理 `record_answer` 相关逻辑。

    Args:
        kp_id: str => kp ID。
        correct: bool => `correct` 参数。
        confidence: float => `confidence` 参数。
        user_name: str => `user_name` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    if kp_id not in load_kg()["points"]:
        raise ToolError(f"未知知识点 {kp_id!r}")
    if not 0.0 <= confidence <= 1.0:
        raise ToolError(f"confidence 必须在 0.0-1.0 之间，收到 {confidence}")
    st = load_states(user_name).get(kp_id)
    before = float(st["mastery_level"]) if st else PRIOR_MASTERY
    if correct:
        after = min(MAX_MASTERY, before + (MAX_MASTERY - before) * 0.25 * confidence)
    else:
        after = max(MIN_MASTERY, before - (before - MIN_MASTERY) * 0.30 * confidence)
    return {"allowed": True, "user_name": user_name, "kp_id": kp_id, "correct": correct,
            "mastery_before": round(before, 2), "mastery_after": round(after, 2),
            "practice_count": (st["practice_count"] + 1) if st else 1}


# --------------------------------------------------------------------------
# 后续新增的 5 个工具（仓库 2026-08-10 快照）
# --------------------------------------------------------------------------


def get_weak_prerequisites_tool(kp_id: str, mastery_threshold: float = 50.0, max_depth: int = 5,
                                user_name: str = "stu_demo") -> dict[str, Any]:
    """外层包装见 mastery_tools.get_weak_prerequisites。"""
    if kp_id not in load_kg()["points"]:
        raise ToolError(f"未知知识点 {kp_id!r}")
    items = get_weak_prerequisites(user_name, kp_id, mastery_threshold, max_depth)
    return {"allowed": True, "user_name": user_name, "kp_id": kp_id,
            "count": len(items), "weak_prerequisites": items}


def get_review_timing(kp_id: str, threshold: float = 0.7, user_name: str = "stu_demo") -> dict[str, Any]:
    """复刻 mastery_store.get_review_timing + 工具层包装。"""
    if kp_id not in load_kg()["points"]:
        raise ToolError(f"未知知识点 {kp_id!r}")
    st = load_states(user_name).get(kp_id)
    base = {"allowed": True, "user_name": user_name, "kp_id": kp_id}
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
    if kp_id not in load_kg()["points"]:
        raise ToolError(f"未知知识点 {kp_id!r}")
    if activity_type not in ACTIVITY_TYPES:
        raise ToolError(f"activity_type 必须是 {ACTIVITY_TYPES} 之一，收到 {activity_type!r}")
    err = (kw.get("error_type") or "").strip().lower() or None
    if err is not None and err not in ERROR_TYPES:
        raise ToolError(f"error_type 必须是 {ERROR_TYPES} 之一，收到 {err!r}")

    evidence = {
        "user_name": user_name, "kp_id": kp_id, "activity_type": activity_type,
        "correct": kw.get("correct"),
        "self_confidence": kw.get("self_confidence"),
        "evidence_reliability": max(0.0, min(1.0, float(kw.get("evidence_reliability", 1.0)))),
        "hint_level": max(0, min(5, int(kw.get("hint_level", 0)))),
        "attempts": max(1, int(kw.get("attempts", 1))),
        "independent": kw.get("independent"),
        "recall_score": kw.get("recall_score"),
        "explanation_score": kw.get("explanation_score"),
        "transfer_score": kw.get("transfer_score"),
        "error_type": err,
        "misconception": kw.get("misconception"),
        "created_at": NOW.isoformat(sep=" ", timespec="seconds"),
    }
    st = load_states(user_name).get(kp_id)
    before = float(st["mastery_level"]) if st else PRIOR_MASTERY
    correct = kw.get("correct")
    rel = evidence["evidence_reliability"]
    if correct is True:
        after = min(MAX_MASTERY, before + (MAX_MASTERY - before) * 0.25 * rel)
    elif correct is False:
        after = max(MIN_MASTERY, before - (before - MIN_MASTERY) * 0.30 * rel)
    else:
        after = before
    state = dict(st) if st else {"user_name": user_name, "kp_id": kp_id, "practice_count": 0}
    state["mastery_level"] = round(after, 2)
    state["practice_count"] = state.get("practice_count", 0) + 1
    return {"saved": True, "evidence": evidence, "state": state}


def get_learning_evidence_summary(kp_id: str = "", limit: int = 50,
                                  user_name: str = "stu_demo") -> dict[str, Any]:
    """复刻 evidence_store.get_summary。空证据时所有均值字段是 None 而不是 0。"""
    kid = kp_id.strip() or None
    base = {"allowed": True, "user_name": user_name, "kp_id": kid}
    kg = load_kg()
    if kid and kid not in kg["points"]:
        raise ToolError(f"未知知识点 {kid!r}")

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


CORE_MEMORIES = [
    {"memory_key": "learning_goal", "content": "这学期把数据结构和算法吃透，准备考研",
     "category": "learning", "updated_at": "2026-07-28 10:12:00"},
    {"memory_key": "response_style", "content": "喜欢先看直观例子，再看公式推导",
     "category": "preference", "updated_at": "2026-07-30 21:03:00"},
    {"memory_key": "major_info", "content": "软件工程专业大三",
     "category": "profile", "updated_at": "2026-06-15 09:00:00"},
    {"memory_key": "weak_topics", "content": "图论相关的知识点普遍薄弱",
     "category": "learning", "updated_at": "2026-08-02 16:40:00"},
    {"memory_key": "exam_schedule", "content": "期末考试从第 16 周开始",
     "category": "constraint", "updated_at": "2026-07-20 08:30:00"},
]


MEMORY_CATEGORIES = ["profile", "preference", "learning", "project", "constraint", "general"]


def save_core_memory(memory_key: str, content: str, category: str = "general") -> dict[str, Any]:
    """复刻 memory_tools.save_core_memory。空 key/content 返回 saved=False 而不是抛错。"""
    if not memory_key or not content:
        return {"saved": False, "memory_key": memory_key, "content": content,
                "category": category, "reason": "memory_key/content 不能为空"}
    if category not in MEMORY_CATEGORIES:
        raise ToolError(f"category 必须是 {MEMORY_CATEGORIES} 之一，收到 {category!r}")
    return {"saved": True, "memory_key": memory_key, "content": content,
            "category": category, "profile_projection": None}


def delete_core_memory(memory_key: str) -> dict[str, Any]:
    """复刻 memory_tools.delete_core_memory。不存在的 key 返回 deleted=False，不抛错。"""
    exists = any(m["memory_key"] == memory_key for m in CORE_MEMORIES)
    return {"deleted": exists, "memory_key": memory_key, "profile_projection": None}


def get_core_memories() -> dict[str, Any]:
    """复刻 memory_tools.get_core_memories：返回全部记忆，不做 compact 裁剪。

    注意与 search_core_memories 的差别：这个返回完整记录，那个只返回四字段的
    compact 形式。两者的返回结构不同，正是要教模型区分的地方之一。
    """
    return {"allowed": True, "count": len(CORE_MEMORIES), "memories": list(CORE_MEMORIES)}


def search_core_memories(query: str, category: str = "", limit: int = 5) -> dict[str, Any]:
    """复刻 memory_tools.search_core_memories：只返回 compact 四字段。"""
    pool = [m for m in CORE_MEMORIES if not category or m["category"] == category]
    hits = [m for m in pool if any(t and t in m["content"] + m["memory_key"] for t in query)] or pool[:2]
    compact = [{k: m[k] for k in ("memory_key", "content", "category", "updated_at")} for m in hits[:limit]]
    return {"allowed": True, "query": query, "count": len(compact), "memories": compact}


# --------------------------------------------------------------------------
# 会话模式阻断（isolated / no_write）
#
# 这些**不是异常**：工具正常返回，只是载荷里 allowed/saved/deleted 是 False，
# 外加一句 reason。所以观测里既不会出现 `[Error]:`，也不会有 error 键 ——
# 这是这个 Agent 里第三种失败表示，模型必须能分辨。
#
# 逐字复刻自后端，**键的顺序也要一致**（线上观测是 str(dict)，顺序会出现在文本里）：
#   backend/agent/tools/mastery_tools.py:67-72   _read_blocked_payload
#   backend/agent/tools/mastery_tools.py:141-153 recommend_practice 阻断分支
#   backend/agent/tools/mastery_tools.py:231-243 get_mastery_report 阻断分支
#   backend/agent/tools/mastery_tools.py:466-472 record_answer 阻断分支
#   backend/agent/tools/memory_tools.py:156-163  save_core_memory 阻断分支
#   backend/agent/tools/memory_tools.py:238-245  search_core_memories 阻断分支
#   backend/agent/tools/memory_tools.py:290-296  get_core_memories 阻断分支
#   backend/agent/tools/memory_tools.py:330-335  delete_core_memory 阻断分支
#
# system prompt 里那句「isolated 会话不得通过 Tool 绕过隔离边界读取长期状态」
# （core/message/system.py），只有这批样本能落地。
# --------------------------------------------------------------------------

STATE_READ_BLOCKED = "当前会话为 isolated 模式，禁止读取长期学习状态"
MEMORY_READ_BLOCKED = "当前会话为 isolated 模式，禁止读取长期记忆"
MEMORY_WRITE_BLOCKED = "当前会话为 no_write/isolated 模式，禁止写入记忆"
MEMORY_DELETE_BLOCKED = "当前会话为 no_write/isolated 模式，禁止删除长期记忆"
RECORD_BLOCKED = "当前会话为 no_write/isolated 模式，禁止记录练习结果"


def _read_blocked_payload(action: str) -> dict[str, Any]:
    """读取 `blocked payload` 相关数据。"""
    return {"allowed": False, "action": action, "reason": STATE_READ_BLOCKED}


def blocked_recommend_practice(course: str, user_name: str = "stu_demo") -> dict[str, Any]:
    """处理 `blocked_recommend_practice` 相关逻辑。

    Args:
        course: str => `course` 参数。
        user_name: str => `user_name` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    return {**_read_blocked_payload("recommend_practice"), "user_name": user_name,
            "course": course, "count": 0, "recommendations": []}


def blocked_get_mastery_report(course: str = "", user_name: str = "stu_demo") -> dict[str, Any]:
    """处理 `blocked_get_mastery_report` 相关逻辑。

    Args:
        course: str => `course` 参数。
        user_name: str => `user_name` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    return {**_read_blocked_payload("get_mastery_report"), "user_name": user_name,
            "course": course or None, "total_points": 0, "avg_mastery": 0.0,
            "weak_points": [], "strong_points": [], "stale_points": []}


def blocked_record_answer(kp_id: str, user_name: str = "stu_demo") -> dict[str, Any]:
    """处理 `blocked_record_answer` 相关逻辑。

    Args:
        kp_id: str => kp ID。
        user_name: str => `user_name` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    return {"user_name": user_name, "kp_id": kp_id, "saved": False, "reason": RECORD_BLOCKED}


def blocked_get_core_memories() -> dict[str, Any]:
    """处理 `blocked_get_core_memories` 相关逻辑。"""
    return {"allowed": False, "count": 0, "memories": [], "reason": MEMORY_READ_BLOCKED}


def blocked_search_core_memories(query: str) -> dict[str, Any]:
    """处理 `blocked_search_core_memories` 相关逻辑。"""
    return {"allowed": False, "query": query, "count": 0, "memories": [],
            "reason": MEMORY_READ_BLOCKED}


def blocked_save_core_memory(memory_key: str, content: str, category: str = "general") -> dict[str, Any]:
    """处理 `blocked_save_core_memory` 相关逻辑。

    Args:
        memory_key: str => `memory_key` 参数。
        content: str => 待处理内容。
        category: str => `category` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    return {"saved": False, "memory_key": memory_key, "content": content,
            "category": category, "reason": MEMORY_WRITE_BLOCKED}


def blocked_delete_core_memory(memory_key: str) -> dict[str, Any]:
    """处理 `blocked_delete_core_memory` 相关逻辑。"""
    return {"deleted": False, "memory_key": memory_key, "reason": MEMORY_DELETE_BLOCKED}


BLOCKED_BUILDERS = {
    "recommend_practice": blocked_recommend_practice,
    "get_mastery_report": blocked_get_mastery_report,
    "record_answer": blocked_record_answer,
    "get_core_memories": blocked_get_core_memories,
    "search_core_memories": blocked_search_core_memories,
    "save_core_memory": blocked_save_core_memory,
    "delete_core_memory": blocked_delete_core_memory,
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
    import json
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


# web_search.py 里真实的报错文案，用于工具异常恢复样本。
# 不编造搜索结果 —— 没有真实 SearXNG 实例就只做错误恢复，
# 等后端能导出真实检索结果再补正例。
WEB_SEARCH_ERRORS = [
    "搜索请求超时",
    "SearXNG 禁止 JSON 输出，请检查 settings.yml 中是否启用了 search.formats.json",
    "SearXNG 返回 HTTP 502",
    "无法连接到 SearXNG：Connection refused",
    "SearXNG 返回的不是有效 JSON",
]


FIXTURE_FUNCTIONS = {
    "arxiv_search": arxiv_search,
    "get_time": get_time,
    "get_weather": get_weather,
    "recommend_practice": recommend_practice,
    "get_mastery_report": get_mastery_report,
    "get_mastery_level": get_mastery_level,
    "record_answer": record_answer,
    "get_weak_prerequisites": get_weak_prerequisites_tool,
    "get_review_timing": get_review_timing,
    "record_learning_evidence": record_learning_evidence,
    "get_learning_evidence_summary": get_learning_evidence_summary,
    "search_core_memories": search_core_memories,
    "get_core_memories": get_core_memories,
    "save_core_memory": save_core_memory,
    "delete_core_memory": delete_core_memory,
}
