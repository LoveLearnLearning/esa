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


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1)


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
