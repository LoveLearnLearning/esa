from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClassCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    canonical_course: str = Field(min_length=1, max_length=80)
    term: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=500)


class InviteStudentRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)


class InvitationResponseRequest(BaseModel):
    accept: bool


class QuestionInput(BaseModel):
    question_type: Literal["short_answer", "code"] = "short_answer"
    prompt: str = Field(min_length=1, max_length=20_000)
    max_points: float = Field(gt=0, le=1000)
    rubric: str = Field(default="", max_length=10_000)
    reference_answer: str = Field(default="", max_length=20_000)
    kp_id: str | None = Field(default=None, max_length=128)


class AssignmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=10_000)
    due_at: datetime | None = None
    questions: list[QuestionInput] = Field(min_length=1, max_length=30)


class AnswerInput(BaseModel):
    question_id: str
    answer_text: str = Field(default="", max_length=100_000)


class SubmissionCreateRequest(BaseModel):
    answers: list[AnswerInput] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_questions(self):
        ids = [item.question_id for item in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("同一道题不能重复提交答案")
        return self


class AnswerReviewInput(BaseModel):
    answer_id: str
    score: float = Field(ge=0, le=1000)
    error_type: Literal[
        "conceptual", "procedural", "strategic", "representation",
        "prerequisite", "careless", "unknown"
    ] | None = None
    feedback: str = Field(default="", max_length=10_000)
    kp_id: str | None = Field(default=None, max_length=128)


class SubmissionReviewRequest(BaseModel):
    reviews: list[AnswerReviewInput] = Field(min_length=1, max_length=30)
