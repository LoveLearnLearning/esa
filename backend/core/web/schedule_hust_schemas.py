from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, SecretStr, model_validator


class HustChallengeStartRequest(BaseModel):
    semester_name: str | None = Field(None, min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "HustChallengeStartRequest":
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date 和 end_date 必须同时提供")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class HustChallengeOut(BaseModel):
    challenge_id: str
    captcha_image_base64: str
    captcha_mime_type: str
    expires_at: str
    recommended_semester_name: str
    recommended_start_date: str
    recommended_end_date: str


class HustChallengeCompleteRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=64)
    # 字段错误响应可能回显 input，因此密码只转换为 SecretStr，长度由导入器校验。
    password: SecretStr
    captcha: str = Field(min_length=1, max_length=16)
    semester_name: str | None = Field(None, min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    target: str = Field(default="current", pattern=r"^(current|new)$")
    table_name: str | None = Field(default=None, max_length=40)
