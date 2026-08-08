# backend/agent/learning/pedagogy_router.py

from __future__ import annotations

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

    def to_prompt_context(self) -> str:
        if self.skill_name is None:
            return (
                f"任务类型：{self.task_type}。"
                "本轮没有强制推荐教学 Skill；按用户显式要求正常回答。"
            )
        return (
            f"任务类型：{self.task_type}。"
            f"候选教学 Skill：{self.skill_name}。"
            f"路由理由：{self.reason}。"
            "这是系统生成的候选策略，不得覆盖用户当前消息；"
            "若确实匹配，应先调用 load_skill 加载正文。"
        )


class PedagogyRouter:
    """
    确定性教学策略路由器。

    第一版刻意不用第二个 LLM：它只做高置信度意图分流，低置信度时返回 None，
    让主 Agent 继续依据 Skill 描述自行决定。这样能提高稳定性，又不会把系统
    变成新的多 Agent 编排层。
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
                return PedagogyDecision(
                    skill_name=skill_name,
                    reason="前端 TaskMode 已明确声明用户意图",
                    confidence=1.0,
                    task_type="learning",
                )

        # 明确工程任务不要套教育脚手架。
        if any(marker in lowered for marker in cls._ENGINEERING_MARKERS):
            return PedagogyDecision(
                skill_name=None,
                reason="检测到工程/部署/调试语境",
                confidence=0.95,
                task_type="engineering",
            )

        if any(marker in lowered for marker in cls._TEACH_BACK_MARKERS):
            return PedagogyDecision(
                skill_name="teach_back",
                reason="用户明确要求复述/理解验证",
                confidence=0.98,
                task_type="learning",
            )

        if any(marker in lowered for marker in cls._REVIEW_MARKERS):
            return PedagogyDecision(
                skill_name="homework_review",
                reason="用户提交了自己的作答并要求检查",
                confidence=0.92,
                task_type="learning",
            )

        if any(marker in lowered for marker in cls._STUCK_MARKERS):
            return PedagogyDecision(
                skill_name="progressive_hint",
                reason="用户明确表示卡住或请求提示",
                confidence=0.92,
                task_type="learning",
            )

        if (
            "掌握度" in text
            or "学习情况" in text
            or "学情" in text
        ):
            return PedagogyDecision(
                skill_name="mastery_report",
                reason="用户询问掌握度或学情",
                confidence=0.9,
                task_type="learning",
            )

        if (
            "今天练什么" in text
            or "推荐练习" in text
            or "刷题计划" in text
        ):
            return PedagogyDecision(
                skill_name="practice_recommendation",
                reason="用户请求练习推荐",
                confidence=0.9,
                task_type="learning",
            )

        if (
            ("学习计划" in text or "复习计划" in text)
            and ("帮我" in text or "制定" in text or "生成" in text)
        ):
            return PedagogyDecision(
                skill_name="study_plan",
                reason="用户请求制定学习/复习计划",
                confidence=0.88,
                task_type="learning",
            )

        if any(marker in lowered for marker in cls._CONCEPT_MARKERS):
            return PedagogyDecision(
                skill_name="retrieve_first",
                reason="用户正在学习概念/原理，适合先做低成本检索练习",
                confidence=0.72 if profile is None else 0.8,
                task_type="learning",
            )

        return PedagogyDecision(
            skill_name=None,
            reason="没有检测到足够高置信度的教学策略触发条件",
            confidence=0.5,
            task_type="general",
        )
