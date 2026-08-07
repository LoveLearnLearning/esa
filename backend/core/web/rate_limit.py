# backend/core/web/rate_limit.py

"""简单的内存限流器 (P2-13)

避免引入 slowapi 依赖 用滑动窗口计数器实现。
多 Worker 场景下各进程独立计数 实际限流上限 = limit * worker_count
对于防滥用场景(批量篡改)已足够 生产可替换为 Redis 实现。
"""

from __future__ import annotations

import functools
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import HTTPException, status


@dataclass
class _Window:
    """滑动窗口计数器"""
    count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class RateLimiter:
    """简单的内存限流器

    Usage:
        limiter = RateLimiter()
        @limiter.limit("10/minute")
        def my_endpoint(...): ...
    """

    def __init__(self) -> None:
        # key: (user_id, endpoint) -> _Window
        self._windows: dict[str, _Window] = defaultdict(_Window)
        # 解析 "10/minute" -> (10, 60)
        self._limits: dict[str, tuple[int, int]] = {}

    def _parse_limit(self, limit_str: str) -> tuple[int, int]:
        """解析 '10/minute' -> (10, 60)"""
        if limit_str in self._limits:
            return self._limits[limit_str]
        count_str, _, unit_str = limit_str.partition("/")
        count = int(count_str)
        unit_map = {"second": 1, "minute": 60, "hour": 3600}
        window = unit_map.get(unit_str, 60)
        self._limits[limit_str] = (count, window)
        return count, window

    def check(self, key: str, limit_str: str) -> None:
        """检查是否超过限流 超过则抛 429

        Args:
            key: str => 限流键 (通常为 user_id + endpoint)
            limit_str: str => 限流规则 如 "10/minute"
        """
        max_count, window_seconds = self._parse_limit(limit_str)
        now = time.monotonic()
        window = self._windows[key]

        # 窗口过期则重置
        if now - window.window_start > window_seconds:
            window.count = 0
            window.window_start = now

        window.count += 1
        if window.count > max_count:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"请求过于频繁 限流: {limit_str} 请稍后再试",
            )

    def limit(self, limit_str: str):
        """装饰器 用于 FastAPI 端点

        需要端点有 session: CurrentSession 参数来获取 user_id。
        使用 functools.wraps 保留原始签名 确保 FastAPI 依赖注入正常工作。
        """
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # 从 kwargs 中找 session
                session = kwargs.get("session")
                if session is None:
                    # 从位置参数中找 (依赖注入的 session 通常是位置参数)
                    for arg in args:
                        if hasattr(arg, "user_id"):
                            session = arg
                            break
                user_id = getattr(session, "user_id", "anonymous") if session else "anonymous"
                key = f"{user_id}:{func.__name__}"
                self.check(key, limit_str)
                return func(*args, **kwargs)
            return wrapper
        return decorator


# 全局限流器实例
profile_limiter = RateLimiter()
