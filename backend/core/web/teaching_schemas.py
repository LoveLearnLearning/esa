# backend/core/web/teaching_schemas.py

"""定义接口请求与响应结构。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClassCreateRequest(BaseModel):
    """表示 `class create request` 数据结构。"""
    name: str = Field(min_length=1, max_length=80)
    canonical_course: str = Field(min_length=1, max_length=80)
    term: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=500)


class InviteStudentRequest(BaseModel):
    """表示 `invite student request` 数据结构。"""
    username: str = Field(min_length=1, max_length=32)


class InvitationResponseRequest(BaseModel):
    """表示 `invitation response request` 数据结构。"""
    accept: bool


class JoinClassRequest(BaseModel):
    """表示 `join class request` 数据结构。"""
    class_code: str = Field(min_length=8, max_length=8, pattern=r"^[A-Za-z0-9]{8}$")


class QuestionInput(BaseModel):
    """表示 `question input` 数据结构。"""
    question_type: Literal["short_answer", "code"] = "short_answer"
    prompt: str = Field(min_length=1, max_length=20_000)
    max_points: float = Field(gt=0, le=1000)
    rubric: str = Field(default="", max_length=10_000)
    reference_answer: str = Field(default="", max_length=20_000)
    kp_id: str | None = Field(default=None, max_length=128)


class AssignmentCreateRequest(BaseModel):
    """表示 `assignment create request` 数据结构。"""
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=10_000)
    due_at: datetime | None = None
    questions: list[QuestionInput] = Field(min_length=1, max_length=30)


class AnswerInput(BaseModel):
    """表示 `answer input` 数据结构。"""
    question_id: str
    answer_text: str = Field(default="", max_length=100_000)


class SubmissionCreateRequest(BaseModel):
    """表示 `submission create request` 数据结构。"""
    answers: list[AnswerInput] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_questions(self):
        """处理 `unique_questions` 相关逻辑。"""
        ids = [item.question_id for item in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("同一道题不能重复提交答案")
        return self


class AnswerReviewInput(BaseModel):
    """表示 `answer review input` 数据结构。"""
    answer_id: str
    score: float = Field(ge=0, le=1000)
    error_type: Literal[
        "conceptual", "procedural", "strategic", "representation",
        "prerequisite", "careless", "unknown"
    ] | None = None
    feedback: str = Field(default="", max_length=10_000)
    kp_id: str | None = Field(default=None, max_length=128)


class SubmissionReviewRequest(BaseModel):
    """表示 `submission review request` 数据结构。"""
    reviews: list[AnswerReviewInput] = Field(min_length=1, max_length=30)
