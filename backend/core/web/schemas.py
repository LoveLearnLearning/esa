# backend/core/web/schemas.py

from datetime import datetime

from pydantic import BaseModel, Field


# 请求
class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=64)


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


# 响应
class LoginResponse(BaseModel):
    session_id: str
    user_id: str
    username: str
    expires_at: datetime


class MessageOut(BaseModel):
    role: str
    content: str
    name: str | None = None
    created_at: str | None = None
