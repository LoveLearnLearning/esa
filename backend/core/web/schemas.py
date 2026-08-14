# backend/core/web/schemas.py

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# 风格/语调合法枚举 供偏好与分组接口共用
VALID_STYLES = {"concise", "detailed", "socratic"}
VALID_TONES = {"friendly", "formal", "encouraging", "strict"}
# 当前仅支持计算机学科
VALID_MAJORS = {"cs"}


# 请求
class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    verification_code: str = Field(pattern=r"^\d{6}$")
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    account_role: Literal["student", "teacher"] = "student"


class LoginRequest(BaseModel):
    username: str
    password: str


class EmailCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class BindEmailRequest(EmailCodeRequest):
    verification_code: str = Field(pattern=r"^\d{6}$")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
    replace_message_id: int | None = Field(default=None, ge=1)


class ResearchProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)


class ResearchProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["active", "archived"] | None = None

    @model_validator(mode="after")
    def require_an_update(self):
        if not self.model_fields_set or all(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("at least one project field must be provided")
        return self


class FrontierTrackingCreateRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    time_window_years: int = Field(default=5, ge=1, le=20)
    max_results: int = Field(default=20, ge=5, le=40)


class ResearchDocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    document_type: Literal["outline", "literature_review", "paper", "notes"]
    content: str = Field(default="", max_length=200_000)


class ResearchDocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, max_length=200_000)


class ResearchWritingJobCreateRequest(BaseModel):
    operation: Literal["outline", "literature_review", "polish", "format_check"]
    instruction: str = Field(default="", max_length=4000)
    source_text: str = Field(default="", max_length=200_000)


class ResearchAnalysisJobCreateRequest(BaseModel):
    analysis_type: Literal[
        "descriptive", "correlation", "group_compare", "text_frequency"
    ]
    parameters: dict[str, str] = Field(default_factory=dict)


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=64)
    group_id: str | None = Field(default=None)
    workspace_type: Literal["learning", "teaching", "research"] = "learning"
    research_project_id: str | None = None
    class_id: str | None = None
    assignment_id: str | None = None

    @model_validator(mode="after")
    def validate_resource_bindings(self):
        if self.research_project_id and self.workspace_type != "research":
            raise ValueError("research_project_id requires the research workspace")
        if (self.class_id or self.assignment_id) and self.workspace_type not in {
            "learning",
            "teaching",
        }:
            raise ValueError(
                "classroom bindings require the learning or teaching workspace"
            )
        if self.assignment_id and not self.class_id:
            raise ValueError("assignment_id requires class_id")
        return self


class ConversationPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=64)
    group_id: str | None = Field(default=None)
    class_id: str | None = None
    assignment_id: str | None = None


class ResearchProjectProfileUpdateRequest(BaseModel):
    agent_instructions: str = Field(default="", max_length=12000)
    expected_revision: int | None = Field(default=None, ge=0)


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    description: str = Field(default="", max_length=100)
    custom_instruction: str = Field(default="", max_length=500)
    style: str | None = Field(default=None)
    tone: str | None = Field(default=None)


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=100)
    custom_instruction: str | None = Field(default=None, max_length=500)
    style: str | None = Field(default=None)
    tone: str | None = Field(default=None)


class CoreMemoryUpsertRequest(BaseModel):
    memory_key: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=1000)
    category: str = Field(default="general", max_length=32)


class CoreMemoryCreateRequest(BaseModel):
    memory_key: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="general", max_length=32)
    scope_type: str = Field(default="global", pattern="^(global|workspace)$")
    workspace_type: Literal["learning", "teaching", "research"] | None = None


class CoreMemoryUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = Field(default=None, max_length=32)


class CoreMemoryRestoreRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class MemoryCandidateDecisionRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = Field(default=None, max_length=32)
    scope_type: str | None = Field(default=None, pattern="^(global|workspace)$")
    workspace_type: Literal["learning", "teaching", "research"] | None = None


class UserPreferencesOut(BaseModel):
    preferred_style: str
    preferred_tone: str
    custom_instruction: str


class UpdatePreferencesRequest(BaseModel):
    preferred_style: str | None = Field(None)
    preferred_tone: str | None = Field(None)
    custom_instruction: str | None = Field(None, max_length=500)


# 学习档案 专业/年级/教学周/学期总周数
# 与输出偏好分端点：GET/PATCH /me/profile
class UserProfileOut(BaseModel):
    major: str
    grade: str
    current_week: int
    total_weeks: int
    profile_enabled: bool


class UpdateUserProfileRequest(BaseModel):
    major: str | None = Field(None)
    grade: str | None = Field(None, max_length=32)
    current_week: int | None = Field(None, ge=1, le=30)
    total_weeks: int | None = Field(None, ge=1, le=30)
    profile_enabled: bool | None = Field(None)


# ===== Profile V2 Schema =====


class ProfileFieldOut(BaseModel):
    """单个画像维度 含来源与置信度"""

    field: str
    value: object
    origin: str
    confidence: float


class ProfileViewOut(BaseModel):
    """完整画像视图。

    顶层学情字段为旧客户端保留；分节字段承载 Profile V2 数据。
    """

    major: str
    grade: str
    current_week: int
    total_weeks: int
    profile_enabled: bool
    explicit: list[ProfileFieldOut] = Field(default_factory=list)
    preferences: list[ProfileFieldOut] = Field(default_factory=list)
    goals: list[ProfileFieldOut] = Field(default_factory=list)
    projects: list[ProfileFieldOut] = Field(default_factory=list)
    learning_state: list[ProfileFieldOut] = Field(default_factory=list)
    inferred_patterns: list[ProfileFieldOut] = Field(default_factory=list)
    profile_version: int = 0
    generated_at: str = ""


class ProfileSourcesOut(BaseModel):
    """画像字段来源解释"""

    field_key: str
    origin: str
    confidence: float
    source_memory_ids: list[str] = Field(default_factory=list)
    last_confirmed_at: str | None = None
    found: bool = True


class UpdateProfileExplicitRequest(BaseModel):
    """更新显式画像字段 只允许更新显式设置项"""

    major: str | None = Field(None)
    grade: str | None = Field(None, max_length=32)
    current_week: int | None = Field(None, ge=1, le=30)
    total_weeks: int | None = Field(None, ge=1, le=30)
    preferred_style: str | None = Field(None)
    preferred_tone: str | None = Field(None)
    custom_instruction: str | None = Field(None, max_length=500)


class MemorySettingsOut(BaseModel):
    """记忆与画像开关"""

    saved_memory_enabled: bool = True
    chat_history_enabled: bool = True
    auto_extract_enabled: bool = False
    learning_profile_enabled: bool
    inferred_profile_enabled: bool
    default_conversation_mode: str = "normal"


class UpdateMemorySettingsRequest(BaseModel):
    """更新记忆与画像开关"""

    saved_memory_enabled: bool | None = Field(None)
    chat_history_enabled: bool | None = Field(None)
    auto_extract_enabled: bool | None = Field(None)
    learning_profile_enabled: bool | None = Field(None)
    inferred_profile_enabled: bool | None = Field(None)
    default_conversation_mode: str | None = Field(None)


# 响应
class LoginResponse(BaseModel):
    session_id: str
    user_id: str
    username: str
    email: str | None = None
    account_role: Literal["student", "teacher"]
    expires_at: datetime


class MessageOut(BaseModel):
    role: str
    content: str
    name: str | None = None
    created_at: str | None = None


class GroupOut(BaseModel):
    group_id: str
    user_id: str
    name: str
    description: str
    custom_instruction: str
    style: str | None = None
    tone: str | None = None
    conversation_count: int = 0
    created_at: str
    updated_at: str
