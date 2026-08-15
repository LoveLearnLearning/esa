# backend/core/message/models.py

"""Prompt rendering contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSection:
    """封装 `PromptSection` 的状态与行为。"""
    key: str
    title: str
    content: str
    trust: str
    order: int
    stable: bool = False
