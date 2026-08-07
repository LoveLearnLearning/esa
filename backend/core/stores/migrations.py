# backend/core/stores/migrations.py

"""
数据库迁移版本管理。

schema_migrations 表记录已应用的迁移版本 应用启动时按版本号顺序执行未应用的迁移。
每个迁移是一个 (version, description, sql_or_func) 元组 幂等执行。

设计原则:
    - 迁移必须幂等 重复执行不报错 (CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE)
    - 迁移按 version 升序执行 不可回滚 (回滚需编写单独的 down 脚本)
    - 现有 Store._initialize 仍保留 作为表创建的兜底
    - 迁移系统在此基础上追踪版本 便于增量 DDL 变更与回滚审计
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# 迁移定义: (version, description, sql_statements)
# sql_statements 中的每条语句会在独立事务中幂等执行
MigrationDef = tuple[int, str, list[str]]

MIGRATIONS: list[MigrationDef] = [
    (
        1,
        "create_user_profile_dimensions",
        [
            """
            CREATE TABLE IF NOT EXISTS user_profile_dimensions (
                user_id TEXT NOT NULL,
                field_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                origin TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                last_confirmed_at TEXT,
                expires_at TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, field_key),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
        ],
    ),
    (
        2,
        "create_memory_settings",
        [
            """
            CREATE TABLE IF NOT EXISTS memory_settings (
                user_id TEXT PRIMARY KEY,
                saved_memory_enabled INTEGER NOT NULL DEFAULT 1,
                chat_history_enabled INTEGER NOT NULL DEFAULT 1,
                auto_extract_enabled INTEGER NOT NULL DEFAULT 0,
                learning_profile_enabled INTEGER NOT NULL DEFAULT 1,
                inferred_profile_enabled INTEGER NOT NULL DEFAULT 1,
                default_conversation_mode TEXT NOT NULL DEFAULT 'normal',
                episodic_retention_days INTEGER NOT NULL DEFAULT 180,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                CHECK(default_conversation_mode IN ('normal', 'no_write', 'isolated'))
            )
            """,
        ],
    ),
    (
        3,
        "create_profile_audit_log",
        [
            """
            CREATE TABLE IF NOT EXISTS profile_audit_log (
                audit_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                field_key TEXT,
                before_json TEXT,
                after_json TEXT,
                actor TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON profile_audit_log(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON profile_audit_log(created_at)",
        ],
    ),
    (
        4,
        "create_profile_versions",
        [
            """
            CREATE TABLE IF NOT EXISTS profile_versions (
                user_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, version),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
        ],
    ),
]


def run_migrations(database_path: str | Path) -> int:
    """执行未应用的数据库迁移

    创建 schema_migrations 表 (若不存在) 按版本号升序执行未应用的迁移。
    每条迁移在独立事务中执行 失败时回滚并抛出异常。

    Args:
        database_path: str | Path => SQLite 数据库路径

    Returns:
        int => 本次新应用的迁移数量
    """
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    applied = 0
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # 创建版本追踪表
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT
            )
            """
        )
        conn.commit()

        # 查询已应用的版本
        applied_versions: set[int] = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations")
        }

        # 按版本号升序执行未应用的迁移
        for version, description, statements in MIGRATIONS:
            if version in applied_versions:
                continue

            logger.info("应用数据库迁移 V%03d: %s", version, description)
            try:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
                    (version, datetime.now().isoformat(), description),
                )
                conn.commit()
                applied += 1
            except Exception:
                conn.rollback()
                logger.exception("数据库迁移 V%03d 失败 已回滚", version)
                raise
    finally:
        conn.close()

    if applied > 0:
        logger.info("数据库迁移完成 新应用 %d 个", applied)
    return applied
