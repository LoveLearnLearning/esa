# backend/agent/tools/mastery_tools.py
#
# 注册 3 个 Agent 工具，向 LLM 暴露 MasteryStore + KnowledgeGraphStore 的数据能力：
#   - recommend_practice: 推荐练习知识点（含优先级与理由）
#   - get_mastery_report: 获取掌握度报告
#   - record_answer:      记录一次练习结果并更新掌握度
#
# 设计决策：
#   1. 工具签名不含 user_id 参数，从 memory_tools.current_user ContextVar 获取
#      与 save_core_memory 等现有工具一致，避免 Agent 被诱导跨用户写库
#   2. 模块级实例化 MasteryStore + KnowledgeGraphStore，数据库路径与 core_memory.db
#      对齐到 memories/data/，便于统一备份与迁移
#   3. recommend_practice 对 Top5 推荐项追加 get_weak_prerequisites 追溯结果
#   4. 触发时机由 Skill 文档定义，本模块只提供数据能力不做自动落库
#   5. total_weeks（学期总周数）属于用户学习档案字段，定义在 UserRecord 中
#      本模块通过 current_total_weeks ContextVar 接收 Agent 注入的用户实际值
#      （Task 6 _prepare_run 调用 set_current_total_weeks）
#      未注入时 fallback 到 UserRecord.TOTAL_WEEKS_DEFAULT，避免硬编码

from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.tools.memory_tools import get_current_user
from backend.agent.tools.tools import tr
from backend.core.utils.models import UserRecord

MEMORIES_DIR = Path(__file__).resolve().parent.parent / "memories"

# 模块级实例化（参考 memory_tools.py 中 core_memory 的模式）
kg_store = KnowledgeGraphStore(
    database_path=MEMORIES_DIR / "data" / "knowledge_graph.db",
)
mastery_store = MasteryStore(
    database_path=MEMORIES_DIR / "data" / "mastery.db",
)

# 当前用户的学期总周数（由 Agent 在 _prepare_run 时通过 set_current_total_weeks 注入）
# 未注入时为 None，recommend_practice 会 fallback 到 UserRecord.TOTAL_WEEKS_DEFAULT
current_total_weeks: ContextVar[int | None] = ContextVar(
    "current_total_weeks",
    default=None,
)


def set_current_total_weeks(total_weeks: int) -> None:
    """辅助函数：设置当前用户的学期总周数

    由 Agent._prepare_run 在每次对话开始时调用（Task 6 集成）
    从 UserRecord.total_weeks 读取并注入 ContextVar

    Args:
        total_weeks: int => 学期总周数
    """
    current_total_weeks.set(total_weeks)


def _build_reasons(
    point: dict,
    weak_prereqs: list[dict],
    weeks_to_exam: int,
    total_weeks: int,
) -> list[str]:
    """辅助函数 生成推荐理由

    根据 spec 推荐理由覆盖 4 类:
        - 掌握度低: mastery_level < 50
        - 权重高:   weight >= 0.7
        - 距期末近: weeks_to_exam <= total_weeks / 4
        - 前置薄弱: weak_prereqs 非空

    Args:
        point: dict          => get_priority_ranking 返回的知识点项
        weak_prereqs: list   => get_weak_prerequisites 返回的薄弱前置链
        weeks_to_exam: int   => 距期末周数
        total_weeks: int     => 学期总周数

    Returns:
        list[str]            => 推荐理由列表 至少 1 条
    """
    reasons: list[str] = []

    mastery = float(point.get("mastery_level", 50.0))
    weight = float(point.get("weight", 0.0))

    if mastery < 50.0:
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


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "recommend_practice",
            "description": (
                "推荐当前用户在某课程中需要重点练习的知识点 "
                "返回按优先级降序的知识点列表 每条包含掌握度 权重 优先级得分 推荐理由 "
                "优先级综合考虑掌握度 考试权重 距期末时间 前置依赖薄弱程度 "
                "当用户要求推荐练习 制定刷题计划 或询问今天练什么时调用"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course": {
                        "type": "string",
                        "description": "课程名 例如 数据结构 / 操作系统 / 算法设计与分析",
                    },
                    "weeks_to_exam": {
                        "type": "integer",
                        "description": "距期末考试的周数 0 表示本周考试 16+ 表示距期末很远",
                    },
                },
                "required": ["course", "weeks_to_exam"],
            },
        },
    }
)
def recommend_practice(
    course: str,
    weeks_to_exam: int,
) -> dict[str, Any]:
    """推荐当前用户在某课程中需要重点练习的知识点

    内部流程：
        1. 调用 MasteryStore.get_priority_ranking 获取按优先级降序的知识点
        2. 对前 5 个推荐项 调用 MasteryStore.get_weak_prerequisites 追溯前置薄弱点
        3. 拼装推荐理由（掌握度低/权重高/距期末近/前置薄弱）

    Args:
        course: str          => 课程名
        weeks_to_exam: int   => 距期末周数

    Returns:
        dict => {
            user_id, course, count, recommendations: [
                {kp_id, name, course, weight, mastery_level,
                 practice_count, priority, reasons, weak_prerequisites}
            ]
        }
    """
    user_id = get_current_user()

    # 学期总周数：优先用 Agent 注入的当前用户值，否则用系统默认值
    total_weeks = current_total_weeks.get() or UserRecord.TOTAL_WEEKS_DEFAULT

    ranking = mastery_store.get_priority_ranking(
        user_id=user_id,
        course=course,
        weeks_to_exam=weeks_to_exam,
        total_weeks=total_weeks,
        kg_store=kg_store,
    )

    if not ranking:
        return {
            "user_id": user_id,
            "course": course,
            "count": 0,
            "recommendations": [],
            "note": f"未找到课程 {course!r} 的知识点 请确认课程名",
        }

    # 对 Top5 推荐项追加前置薄弱追溯与理由
    recommendations: list[dict[str, Any]] = []
    for point in ranking[:5]:
        weak_prereqs = mastery_store.get_weak_prerequisites(
            user_id=user_id,
            kp_id=point["kp_id"],
            kg_store=kg_store,
        )
        reasons = _build_reasons(
            point=point,
            weak_prereqs=weak_prereqs,
            weeks_to_exam=weeks_to_exam,
            total_weeks=total_weeks,
        )
        recommendations.append(
            {
                "kp_id": point["kp_id"],
                "name": point["name"],
                "course": point["course"],
                "weight": point["weight"],
                "mastery_level": point["mastery_level"],
                "practice_count": point["practice_count"],
                "priority": point["priority"],
                "reasons": reasons,
                "weak_prerequisites": weak_prereqs,
            }
        )

    return {
        "user_id": user_id,
        "course": course,
        "count": len(recommendations),
        "recommendations": recommendations,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_mastery_report",
            "description": (
                "获取当前用户的掌握度报告 包含平均掌握度 掌握度最低/最高的知识点 "
                "以及超过 7 天未练习的知识点 "
                "当用户询问掌握度 学习情况 学情 进度时调用"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course": {
                        "type": "string",
                        "description": "课程名 留空则返回全部课程数据",
                    },
                },
                "required": [],
            },
        },
    }
)
def get_mastery_report(course: str = "") -> dict[str, Any]:
    """获取当前用户的掌握度报告

    内部调用 MasteryStore.get_report，当指定 course 时通过 kg_store 过滤该课程知识点

    Args:
        course: str = ""   => 课程名 留空返回全部

    Returns:
        dict => {user_id, course, total_points, avg_mastery,
                 weak_points, strong_points, stale_points}
    """
    user_id = get_current_user()

    course_arg = course.strip() if course else None

    return mastery_store.get_report(
        user_id=user_id,
        course=course_arg,
        kg_store=kg_store,
    )


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "record_answer",
            "description": (
                "记录当前用户一次练习结果并更新该知识点的掌握度 "
                "答对 mastery 上升(随练习次数递减 不超过 95) "
                "答错 mastery 下降(不低于 10) "
                "由练习批改 Skill 引导调用 用户主动提交答案后才记录"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "知识点 id 例如 binary_tree_traversal / process_scheduling",
                    },
                    "correct": {
                        "type": "boolean",
                        "description": "是否答对 True=答对 False=答错",
                    },
                    "confidence": {
                        "type": "number",
                        "description": (
                            "答题置信度 0.0-1.0 模拟 BKT 的 P(G)/P(S) 概率 "
                            "1.0=高置信度(填空/编程/证明) 0.5=低置信度(选择题可能蒙对) "
                            "默认 1.0"
                        ),
                    },
                },
                "required": ["kp_id", "correct"],
            },
        },
    }
)
def record_answer(
    kp_id: str,
    correct: bool,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """记录一次练习结果并更新掌握度

    内部调用 MasteryStore.record_answer，confidence 模拟 BKT 的 P(G)/P(S)

    Args:
        kp_id: str                => 知识点 id
        correct: bool             => 是否答对
        confidence: float = 1.0   => 答题置信度 0.0-1.0

    Returns:
        dict => {user_id, kp_id, mastery_level, practice_count,
                 correct_count, last_practiced_at}
    """
    user_id = get_current_user()

    return mastery_store.record_answer(
        user_id=user_id,
        kp_id=kp_id,
        correct=correct,
        confidence=confidence,
    )
