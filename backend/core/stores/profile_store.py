# backend/core/stores/profile_store.py

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ProfileStore(BaseSQLiteStore):
    """
    用户画像维度缓存表读写类

    user_profile_dimensions 表用于缓存派生/推断出的画像维度 供展示与用户确认
    它不替代原始记忆 仅作为缓存层
    """

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 user_profile_dimensions 表"""
        with self._connect() as connection:
            connection.execute(
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
                """
            )

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """辅助函数 将一行记录反序列化为 dict

        value_json 与 source_memory_ids_json 会被解析为对应的 Python 对象

        Args:
            row: sqlite3.Row => 表中的一行记录

        Returns:
            dict => 反序列化后的字段字典
        """
        return {
            "user_id": row["user_id"],
            "field_key": row["field_key"],
            "value": json.loads(row["value_json"]),
            "origin": row["origin"],
            "confidence": row["confidence"],
            "status": row["status"],
            "source_memory_ids": json.loads(row["source_memory_ids_json"]),
            "last_confirmed_at": row["last_confirmed_at"],
            "expires_at": row["expires_at"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_dimension(
        self,
        user_id: str,
        field_key: str,
        value: object,
        origin: str,
        confidence: float,
        source_memory_ids: list[str] | None = None,
        status: str = "active",
        expires_at: str | None = None,
    ) -> bool:
        """写入或更新一条画像维度记录

        使用 INSERT ... ON CONFLICT DO UPDATE 实现原子 upsert
        命中冲突时 version 自增 updated_at 刷新; 新插入时 version=1

        Args:
            user_id: str                              => 用户 id
            field_key: str                            => 维度键名
            value: object                             => 维度值 会被序列化为 JSON
            origin: str                               => 来源标识
            confidence: float                         => 置信度 0.0~1.0
            source_memory_ids: list[str] | None = None => 关联记忆 id 列表 None 视为空列表
            status: str = "active"                    => 状态 active/suppressed
            expires_at: str | None = None             => 过期时间 ISO 字符串 None 表示不过期

        Returns:
            bool => 是否写入成功(rowcount > 0)
        """
        now_iso = datetime.now().isoformat()
        value_json = json.dumps(value, ensure_ascii=False)
        ids = source_memory_ids if source_memory_ids is not None else []
        source_memory_ids_json = json.dumps(ids, ensure_ascii=False)

        count = self.execute(
            """
            INSERT INTO user_profile_dimensions (
                user_id, field_key, value_json, origin, confidence, status,
                source_memory_ids_json, last_confirmed_at, expires_at, version,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
            ON CONFLICT(user_id, field_key) DO UPDATE SET
                value_json = excluded.value_json,
                origin = excluded.origin,
                confidence = excluded.confidence,
                status = excluded.status,
                source_memory_ids_json = excluded.source_memory_ids_json,
                expires_at = excluded.expires_at,
                version = user_profile_dimensions.version + 1,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                field_key,
                value_json,
                origin,
                confidence,
                status,
                source_memory_ids_json,
                expires_at,
                now_iso,
                now_iso,
            ),
        )

        return count > 0

    def get_dimension(self, user_id: str, field_key: str) -> dict | None:
        """查询单条画像维度记录

        Args:
            user_id: str   => 用户 id
            field_key: str => 维度键名

        Returns:
            dict | None:
                dict => 反序列化后的维度记录 含所有字段
                None => 记录不存在
        """
        row = self.query_one(
            """
            SELECT user_id, field_key, value_json, origin, confidence, status,
                   source_memory_ids_json, last_confirmed_at, expires_at, version,
                   created_at, updated_at
            FROM user_profile_dimensions
            WHERE user_id = ? AND field_key = ?
            """,
            (user_id, field_key),
        )

        if row is None:
            return None

        return self._row_to_dict(row)

    def list_dimensions(
        self,
        user_id: str,
        status_filter: str | None = None,
    ) -> list[dict]:
        """查询用户的全部画像维度记录

        Args:
            user_id: str                       => 用户 id
            status_filter: str | None = None   => 状态过滤 None 表示不过滤

        Returns:
            list[dict] => 反序列化后的维度记录列表 按 updated_at DESC 排序
        """
        if status_filter is None:
            rows = self.query_all(
                """
                SELECT user_id, field_key, value_json, origin, confidence, status,
                       source_memory_ids_json, last_confirmed_at, expires_at, version,
                       created_at, updated_at
                FROM user_profile_dimensions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
        else:
            rows = self.query_all(
                """
                SELECT user_id, field_key, value_json, origin, confidence, status,
                       source_memory_ids_json, last_confirmed_at, expires_at, version,
                       created_at, updated_at
                FROM user_profile_dimensions
                WHERE user_id = ? AND status = ?
                ORDER BY updated_at DESC
                """,
                (user_id, status_filter),
            )

        return [self._row_to_dict(row) for row in rows]

    def suppress_dimension(self, user_id: str, field_key: str) -> bool:
        """将指定维度置为 suppressed 状态

        Args:
            user_id: str   => 用户 id
            field_key: str => 维度键名

        Returns:
            bool => 是否更新成功(记录存在且被更新)
        """
        now_iso = datetime.now().isoformat()

        count = self.execute(
            """
            UPDATE user_profile_dimensions
            SET status = 'suppressed',
                version = version + 1,
                updated_at = ?
            WHERE user_id = ? AND field_key = ? AND status = 'active'
            """,
            (now_iso, user_id, field_key),
        )

        return count > 0

    def restore_dimension(self, user_id: str, field_key: str) -> bool:
        """将指定维度恢复为 active 状态

        Args:
            user_id: str   => 用户 id
            field_key: str => 维度键名

        Returns:
            bool => 是否更新成功(记录存在且被更新)
        """
        now_iso = datetime.now().isoformat()

        count = self.execute(
            """
            UPDATE user_profile_dimensions
            SET status = 'active',
                version = version + 1,
                updated_at = ?
            WHERE user_id = ? AND field_key = ?
            """,
            (now_iso, user_id, field_key),
        )

        return count > 0
