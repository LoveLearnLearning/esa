# backend/agent/learning/pedagogy_router.py

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.agent.memories.memory_models import ProfileSnapshot


@dataclass(frozen=True, slots=True)
class PedagogyDecision:
    """一次轻量教学策略路由结果。"""

    skill_name: str | None
    reason: str
    confidence: float
    task_type: str
    teaching_depth: str = "standard"
    primary_kp_id: str | None = None
    prerequisite_first: bool = False
    learning_notes: tuple[str, ...] = ()

    def to_prompt_context(self, loaded_skill_body: str | None = None) -> str:
        lines = [f"任务类型：{self.task_type}"]
        if self.task_type == "learning":
            if self.primary_kp_id:
                lines.append(f"当前知识点：{self.primary_kp_id}")
            lines.append(f"教学深度：{self.teaching_depth}")
            lines.append("")
            lines.append("教学策略：")
            depth_guidance = {
                "foundation": "当前掌握度较低，从直觉和最小例子开始，再给正式定义",
                "standard": "按标准深度讲解，聚焦核心机制、易错点和一个迁移问题",
                "advanced": "减少基础定义复述，增加边界条件、复杂度、辨析和迁移",
            }
            lines.append(f"- {depth_guidance[self.teaching_depth]}")
            if self.prerequisite_first:
                lines.append("- 检测到薄弱前置知识，必要时先补前置再回到当前知识点")
            lines.extend(f"- {note}" for note in self.learning_notes)

        if self.skill_name is None:
            lines.append("本轮没有强制推荐教学 Skill；按用户显式要求正常回答。")
        elif loaded_skill_body:
            lines.extend(
                [
                    f"已按需加载教学 Skill：{self.skill_name}",
                    f"路由理由：{self.reason}",
                    "该 Skill 由系统内部加载，无需再调用 load_skill；"
                    "若它确实匹配用户当前任务，按下方正文执行。",
                    "",
                    f"## {self.skill_name}",
                    loaded_skill_body,
                ]
            )
        else:
            lines.extend(
                [
                    f"候选教学 Skill：{self.skill_name}",
                    f"路由理由：{self.reason}",
                    "这是系统生成的候选策略，不得覆盖用户当前消息；"
                    "若确实匹配，应先调用 load_skill 加载正文。",
                ]
            )
        return "\n".join(lines)


class PedagogyRouter:
    """
    确定性教学策略路由器。

    刻意不使用第二个 LLM：它只做高置信度意图分流，低置信度时返回 None。
    命中时由 Agent 按需加载对应 Skill 正文，但仍由主 Agent 结合用户当前消息
    决定具体执行，不引入新的多 Agent 编排层。
    """

    _ENGINEERING_MARKERS = (
        "部署",
        "环境配置",
        "安装",
        "依赖",
        "服务器",
        "接口",
        "api",
        "仓库",
        "git",
        "github",
        "报错",
        "异常",
        "日志",
        "端口",
        "docker",
        "nginx",
        "cuda",
        "nccl",
        "vllm",
        "slurm",
    )
    _AMBIGUOUS_ENGINEERING_MARKERS = {"依赖", "接口", "异常"}

    _STUCK_MARKERS = (
        "不会",
        "卡住",
        "卡在",
        "没思路",
        "给点提示",
        "给我提示",
        "提示一下",
        "下一步怎么",
        "不知道怎么",
    )

    _REVIEW_MARKERS = (
        "批改",
        "检查我的答案",
        "看看我做得对不对",
        "我的答案是",
        "我写的是",
        "我算的是",
        "我做完了",
    )

    _CONCEPT_MARKERS = (
        "讲解",
        "解释",
        "什么是",
        "怎么理解",
        "原理",
        "为什么",
        "概念",
    )

    _TEACH_BACK_MARKERS = (
        "让我复述",
        "让我讲一遍",
        "考考我是不是真的懂了",
        "检查我能不能讲清楚",
        "teach back",
    )

    _PRACTICE_MARKERS = (
        "出一道题",
        "出一道",
        "出个题",
        "给我一道题",
        "来一道题",
        "考考我",
        "开始练习",
        "继续练习",
        "练一道",
        "做道题",
    )

    _PRACTICE_CANCEL_MARKERS = (
        "取消练习",
        "停止练习",
        "不做了",
        "换个话题",
        "算了",
    )

    _PRACTICE_HEADER_RE = re.compile(
        r"【练习题｜知识点[：:]\s*(?P<kp_id>[^】]+)】"
    )

    _MATH_TASK_MARKERS = (
        "帮我算",
        "算一下",
        "计算一下",
        "等于多少",
        "结果是多少",
        "求导",
        "求积分",
        "算积分",
        "求极限",
        "解方程",
        "化简",
        "因式分解",
        "泰勒展开",
        "组合数",
        "排列数",
        "位运算",
        "按位",
        "左移",
        "右移",
        "异或",
        "补码",
        "popcount",
        "log2(",
    )

    @classmethod
    def _pending_practice_kp_id(
        cls,
        history: list[dict] | None,
    ) -> str | None:
        """读取最近一条 Agent 回复中的待作答标记。

        只检查最近的 assistant 消息：批改完成后的新 assistant
        回复会自然终止旧题状态，避免把后续闲聊误当作答。
        """
        for message in reversed(history or []):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                return None
            match = cls._PRACTICE_HEADER_RE.search(content)
            return match.group("kp_id").strip() if match else None
        return None

    @staticmethod
    def _resolve_profile_policy(profile):
        if profile is None or not profile.relevant_learning_state:
            return "standard", None, False, ()

        value = profile.relevant_learning_state[0].value
        if not isinstance(value, dict):
            return "standard", None, False, ()

        mastery = value.get("mastery", {})
        has_record = bool(mastery.get("has_record"))
        try:
            level = float(mastery.get("level"))
        except (TypeError, ValueError):
            level = None

        if not has_record or level is None:
            teaching_depth = "standard"
        elif level < 40:
            teaching_depth = "foundation"
        elif level < 75:
            teaching_depth = "standard"
        else:
            teaching_depth = "advanced"

        prereqs = value.get("prerequisites", [])
        prerequisite_first = any(
            isinstance(item, dict) and item.get("status") == "weak"
            for item in prereqs
        )

        notes = []
        retention = mastery.get("retention")
        if retention is not None and float(retention) < 0.65:
            notes.append(
                "掌握度代表长期理解，当前记忆保持率较低；先做主动回忆或快速复习"
            )

        evidence_confidence = mastery.get("evidence_confidence")
        if evidence_confidence is not None and float(evidence_confidence) < 0.35:
            notes.append(
                "当前水平判断证据不足，不要武断断言用户会或不会；优先用小题确认"
            )

        evidence = value.get("evidence", {})
        avg_hint = evidence.get("avg_hint_level")
        if avg_hint is not None and avg_hint >= 2:
            notes.append("用户近期提示依赖较高，优先分级提示，避免直接泄露完整答案")

        independent = evidence.get("independent_rate")
        if independent is not None and independent < 0.4:
            notes.append("用户近期独立完成率偏低，应增加主动回忆与独立尝试")

        misconceptions = evidence.get("recent_misconceptions") or []
        if misconceptions:
            notes.append("注意近期误区：" + "；".join(misconceptions[:3]))

        return (
            teaching_depth,
            value.get("kp_id"),
            prerequisite_first,
            tuple(notes),
        )

    @classmethod
    def route(
        cls,
        message: str,
        *,
        history: list[dict] | None = None,
        profile: "ProfileSnapshot | None" = None,
    ) -> PedagogyDecision:
        text = (message or "").strip()
        lowered = text.lower()
        (
            teaching_depth,
            primary_kp_id,
            prerequisite_first,
            learning_notes,
        ) = cls._resolve_profile_policy(profile)

        def decision(
            skill_name: str | None,
            reason: str,
            confidence: float,
            task_type: str,
            *,
            resolved_kp_id: str | None = None,
        ) -> PedagogyDecision:
            return PedagogyDecision(
                skill_name=skill_name,
                reason=reason,
                confidence=confidence,
                task_type=task_type,
                teaching_depth=teaching_depth,
                primary_kp_id=resolved_kp_id or primary_kp_id,
                prerequisite_first=prerequisite_first,
                learning_notes=learning_notes,
            )

        # Flutter TaskMode 的显式指令优先，避免前后端各自猜一遍意图。
        task_mode_mapping = (
            ("任务模式：批改作业", "homework_review"),
            ("任务模式：学习情况报告", "mastery_report"),
            ("任务模式：练习推荐", "practice_recommendation"),
            ("任务模式：生成复习计划", "study_plan"),
            ("任务模式：知识点与概念讲解", "retrieve_first"),
            ("任务模式：讲解题目", "progressive_hint"),
        )
        for marker, skill_name in task_mode_mapping:
            if marker in text:
                return decision(
                    skill_name,
                    "前端 TaskMode 已明确声明用户意图",
                    1.0,
                    "learning",
                )

        pending_practice_kp_id = cls._pending_practice_kp_id(history)
        cancelled_practice = any(
            marker in text for marker in cls._PRACTICE_CANCEL_MARKERS
        )
        if pending_practice_kp_id is not None and not cancelled_practice:
            return decision(
                "adaptive_practice",
                "用户正在回答上一轮由 Agent 发出的练习题",
                1.0,
                "learning",
                resolved_kp_id=pending_practice_kp_id,
            )

        # 明确工程任务不要套教育脚手架。
        has_engineering_marker = any(
            marker in lowered for marker in cls._ENGINEERING_MARKERS
        )
        has_strong_engineering_marker = any(
            marker in lowered
            for marker in cls._ENGINEERING_MARKERS
            if marker not in cls._AMBIGUOUS_ENGINEERING_MARKERS
        )
        if has_engineering_marker and (
            primary_kp_id is None or has_strong_engineering_marker
        ):
            return decision(None, "检测到工程/部署/调试语境", 0.95, "engineering")

        if any(marker in lowered for marker in cls._TEACH_BACK_MARKERS):
            return decision(
                "teach_back", "用户明确要求复述/理解验证", 0.98, "learning"
            )

        if any(marker in text for marker in cls._PRACTICE_MARKERS):
            return decision(
                "adaptive_practice",
                "用户请求开始或继续一次自适应练习",
                0.96,
                "learning",
            )

        if any(marker in lowered for marker in cls._REVIEW_MARKERS):
            return decision(
                "homework_review", "用户提交了自己的作答并要求检查", 0.92, "learning"
            )

        if any(marker in lowered for marker in cls._STUCK_MARKERS):
            return decision(
                "progressive_hint", "用户明确表示卡住或请求提示", 0.92, "learning"
            )

        if (
            "掌握度" in text
            or "学习情况" in text
            or "学情" in text
        ):
            return decision(
                "mastery_report", "用户询问掌握度或学情", 0.9, "learning"
            )

        if (
            "今天练什么" in text
            or "推荐练习" in text
            or "刷题计划" in text
        ):
            return decision(
                "practice_recommendation", "用户请求练习推荐", 0.9, "learning"
            )

        if (
            ("学习计划" in text or "复习计划" in text)
            and ("帮我" in text or "制定" in text or "生成" in text)
        ):
            return decision(
                "study_plan", "用户请求制定学习/复习计划", 0.88, "learning"
            )

        if any(marker in lowered for marker in cls._MATH_TASK_MARKERS):
            return decision(
                "math_problem_solving",
                "用户请求数值、符号或位运算任务",
                0.94,
                "learning",
            )

        if any(marker in lowered for marker in cls._CONCEPT_MARKERS):
            return decision(
                "retrieve_first",
                "用户正在学习概念/原理，适合先做低成本检索练习",
                0.72 if profile is None else 0.8,
                "learning",
            )

        if primary_kp_id is not None:
            return decision(
                None,
                "已解析出当前知识点，应用画像驱动的教学策略",
                0.75,
                "learning",
            )

        return decision(
            None,
            "没有检测到足够高置信度的教学策略触发条件",
            0.5,
            "general",
        )
