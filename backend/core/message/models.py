"""Prompt rendering contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSection:
    key: str
    title: str
    content: str
    trust: str
    order: int
    stable: bool = False

