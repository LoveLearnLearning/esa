# backend/core/services/teaching_analysis_service.py

"""Structured homework analysis with a deterministic offline fallback."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.services.auxiliary_llm_service import (
    AuxiliaryLLMClient,
    AuxiliaryLLMUnavailable,
)
from backend.core.stores.teaching_store import TeachingStore


class TeachingAnalysisService:
    """提供 `teaching analysis service` 领域服务。"""
    def __init__(
        self,
        store: TeachingStore,
        llm_client: AuxiliaryLLMClient | None = None,
    ) -> None:
        """初始化 `TeachingAnalysisService` 实例。"""
        self.store = store
        self.llm_client = llm_client

    @staticmethod
    def _fallback(answer: dict) -> dict[str, Any]:
        """处理 `_fallback` 相关逻辑。"""
        text = str(answer.get("answer_text") or "").strip()
        reference = str(answer.get("reference_answer") or "").strip()
        rubric = str(answer.get("rubric") or "").strip()
        max_points = float(answer["max_points"])
        if not text:
            ratio = 0.0
            feedback = "未检测到有效作答，请教师确认。"
        elif reference and text.casefold() == reference.casefold():
            ratio = 1.0
            feedback = "答案与参考答案一致，请教师复核表达与过程。"
        else:
            tokens = {
                token.casefold()
                for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", reference + " " + rubric)
            }
            hits = sum(token in text.casefold() for token in tokens)
            ratio = min(0.8, hits / max(1, min(5, len(tokens)))) if tokens else 0.5
            feedback = "模型服务不可用，已按评分关键词生成低置信度建议，必须人工复核。"
        return {
            "answer_id": answer["answer_id"],
            "score": round(max_points * ratio, 2),
            "error_type": None if ratio >= 0.8 else "unknown",
            "feedback": feedback,
            "confidence": 0.35,
            "kp_id": answer.get("kp_id"),
            "analysis_source": "deterministic_fallback",
        }

    async def _analyze_answer(self, answer: dict) -> dict[str, Any]:
        """处理 `_analyze_answer` 相关逻辑。"""
        if self.llm_client is None:
            return self._fallback(answer)
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是教师批改助手。只输出一个 JSON 对象，不输出推理过程。"
                    "字段为 score(number), error_type(conceptual/procedural/strategic/"
                    "representation/prerequisite/careless/unknown/null), feedback(string), "
                    "confidence(0-1), kp_id(string/null)。分数必须在 0 与满分之间。"
                    "这是建议，教师会最终复核。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "题目": answer["prompt"],
                        "题型": answer["question_type"],
                        "满分": answer["max_points"],
                        "评分标准": answer["rubric"],
                        "参考答案": answer["reference_answer"],
                        "学生答案": answer["answer_text"],
                        "预设知识点": answer.get("kp_id"),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            raw = await self.llm_client.chat(prompt, max_tokens=500, temperature=0.1)
            match = re.search(r"\{[\s\S]*\}", raw)
            if match is None:
                raise ValueError("missing JSON")
            data = json.loads(match.group(0))
            score = max(0.0, min(float(answer["max_points"]), float(data["score"])))
            return {
                "answer_id": answer["answer_id"],
                "score": round(score, 2),
                "error_type": data.get("error_type"),
                "feedback": str(data.get("feedback") or ""),
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                "kp_id": data.get("kp_id") or answer.get("kp_id"),
                "analysis_source": "auxiliary_llm",
            }
        except (AuxiliaryLLMUnavailable, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self._fallback(answer)

    async def analyze_submission(self, submission_id: str, actor_id: str) -> dict:
        """处理 `analyze_submission` 相关逻辑。

        Args:
            submission_id: str => submission ID。
            actor_id: str => actor ID。

        Returns:
            dict => 处理结果。
        """
        submission = self.store.get_submission(submission_id)
        if submission is None:
            raise ValueError("submission_not_found")
        try:
            results = [
                await self._analyze_answer(answer) for answer in submission["answers"]
            ]
            self.store.save_analysis(
                submission_id=submission_id, results=results, actor_id=actor_id
            )
        except Exception:
            self.store.mark_analysis_failed(submission_id)
            raise
        return self.store.get_submission(submission_id) or {}
