# backend/agent/tools/learning_tools.py

from __future__ import annotations

from typing import Any

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.memories.paths import LEARNING_EVIDENCE_DB_PATH
from backend.agent.tools.memory_tools import (
    get_current_user,
    memory_read_allowed,
    memory_write_allowed,
)
from backend.agent.tools.tools import tr

evidence_store = LearningEvidenceStore(
    database_path=LEARNING_EVIDENCE_DB_PATH,
)


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "record_learning_evidence",
            "description": (
                "记录一次学习过程证据，例如是否独立完成、使用几级提示、"
                "自评信心、解释能力、迁移能力和错误类型。"
                "只有在学生已经实际作答/复述/尝试后才调用，不得凭空生成证据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "知识点 id",
                    },
                    "activity_type": {
                        "type": "string",
                        "enum": [
                            "practice",
                            "homework",
                            "retrieval",
                            "hint",
                            "teach_back",
                            "transfer",
                            "review",
                        ],
                        "description": "产生该证据的学习活动类型",
                    },
                    "correct": {
                        "type": "boolean",
                        "description": "是否正确；无法二值判断时可不传",
                    },
                    "self_confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": (
                            "学生本人明确表达的答题信心 0-1；"
                            "学生没有提供时不要猜测、不要传"
                        ),
                    },
                    "evidence_reliability": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": (
                            "这次表现作为掌握证据的可靠性；"
                            "它不是学生自评信心。默认 1.0"
                        ),
                    },
                    "hint_level": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 5,
                        "description": "实际使用的最高提示等级，0=未使用提示",
                    },
                    "attempts": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "完成本次活动前的实际尝试次数",
                    },
                    "independent": {
                        "type": "boolean",
                        "description": "是否在没有实质性提示/答案泄露的情况下独立完成",
                    },
                    "recall_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "主动回忆完整度 0-1",
                    },
                    "explanation_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Teach-back 解释质量 0-1",
                    },
                    "transfer_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "迁移到新情境的表现 0-1",
                    },
                    "error_type": {
                        "type": "string",
                        "enum": [
                            "conceptual",
                            "procedural",
                            "strategic",
                            "representation",
                            "prerequisite",
                            "careless",
                            "unknown",
                        ],
                        "description": "错误类型；只有确有错误证据时填写",
                    },
                    "misconception": {
                        "type": "string",
                        "description": "可复用的具体误解描述；不要写泛泛的“粗心”",
                    },
                },
                "required": ["kp_id", "activity_type"],
            },
        },
    }
)
def record_learning_evidence(
    kp_id: str,
    activity_type: str,
    correct: bool | None = None,
    self_confidence: float | None = None,
    evidence_reliability: float = 1.0,
    hint_level: int = 0,
    attempts: int = 1,
    independent: bool | None = None,
    recall_score: float | None = None,
    explanation_score: float | None = None,
    transfer_score: float | None = None,
    error_type: str | None = None,
    misconception: str | None = None,
) -> dict[str, Any]:
    user_name = get_current_user()

    if not memory_write_allowed():
        return {
            "saved": False,
            "user_name": user_name,
            "kp_id": kp_id,
            "reason": "当前会话为 no_write/isolated 模式，禁止写入学习证据",
        }

    evidence = evidence_store.record(
        user_name=user_name,
        kp_id=kp_id,
        activity_type=activity_type,
        correct=correct,
        self_confidence=self_confidence,
        evidence_reliability=evidence_reliability,
        hint_level=hint_level,
        attempts=attempts,
        independent=independent,
        recall_score=recall_score,
        explanation_score=explanation_score,
        transfer_score=transfer_score,
        error_type=error_type,
        misconception=misconception,
    )
    return {"saved": True, "evidence": evidence}


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_learning_evidence_summary",
            "description": (
                "读取当前用户近期学习证据摘要，包含独立完成率、平均提示等级、"
                "自评信心、解释/迁移得分和常见误区。"
                "只有制定教学策略或学习诊断时才调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "可选知识点 id；留空表示用户整体近期证据",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "description": "最多统计最近多少条证据，默认 50",
                    },
                },
                "required": [],
            },
        },
    }
)
def get_learning_evidence_summary(
    kp_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    user_name = get_current_user()

    if not memory_read_allowed():
        return {
            "allowed": False,
            "user_name": user_name,
            "kp_id": kp_id or None,
            "reason": "当前会话为 isolated 模式，禁止读取学习证据",
        }

    summary = evidence_store.get_summary(
        user_name,
        kp_id=kp_id.strip() or None,
        limit=limit,
    )
    return {"allowed": True, **summary}
