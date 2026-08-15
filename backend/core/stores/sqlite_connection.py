# backend/core/stores/sqlite_connection.py

"""提供 `sqlite_connection` 相关功能。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


# Startup initializes several independent stores against the same database.
# On the shared filesystem used by the cluster, a short metadata/write lock can
# outlive SQLite's usual five-second default even though no deadlock exists.
DEFAULT_SQLITE_TIMEOUT_SECONDS = 30.0


def connect_sqlite(
    database_path: str | Path,
    *,
    timeout: float = DEFAULT_SQLITE_TIMEOUT_SECONDS,
) -> sqlite3.Connection:
    """创建项目统一的 SQLite 连接。

    SQLite 的外键开关属于连接级配置，因此每一个连接都必须显式开启。
    ``busy_timeout`` 与 Python 驱动的 ``timeout`` 保持一致，减少短暂写锁竞争
    被误报为 ``database is locked`` 的概率。
    """
    connection = sqlite3.connect(str(database_path), timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {max(0, int(timeout * 1000))}")
    return connection
