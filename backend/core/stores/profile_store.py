# backend/core/stores/profile_store.py

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore

logger = logging.getLogger(__name__)


class ProfileStore(BaseSQLiteStore):
    """
    用户画像维度缓存表读写类

    user_profile_dimensions 表用于缓存派生/推断出的画像维度 供展示与用户确认
    它不替代原始记忆 仅作为缓存层
    """

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 user_profile_dimensions 及相关表

        审计日志表与版本表也在此创建 兼容未运行迁移系统的测试场景。
        迁移系统 (migrations.py) 会幂等执行相同的 DDL 不冲突。
        """
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
            # 审计日志表 (P1-8)
            connection.execute(
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
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON profile_audit_log(user_id)"
            )
            # 版本持久化表 (P1-7)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_versions (
                    user_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    generated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, version)
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

        抑制成功后写入审计日志 便于事后追溯。

        Args:
            user_id: str   => 用户 id
            field_key: str => 维度键名

        Returns:
            bool => 是否更新成功(记录存在且被更新)
        """
        now_iso = datetime.now().isoformat()

        # 先读取变更前状态 用于审计
        before = self.get_dimension(user_id, field_key)

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

        if count > 0:
            self._insert_audit_log(
                user_id=user_id,
                action="suppress",
                field_key=field_key,
                before_json=json.dumps(before, ensure_ascii=False) if before else None,
                after_json=json.dumps({"status": "suppressed"}, ensure_ascii=False),
                actor="user",
            )

        return count > 0

    def restore_dimension(self, user_id: str, field_key: str) -> bool:
        """将指定维度恢复为 active 状态

        恢复成功后写入审计日志。

        Args:
            user_id: str   => 用户 id
            field_key: str => 维度键名

        Returns:
            bool => 是否更新成功(记录存在且被更新)
        """
        now_iso = datetime.now().isoformat()

        before = self.get_dimension(user_id, field_key)

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

        if count > 0:
            self._insert_audit_log(
                user_id=user_id,
                action="restore",
                field_key=field_key,
                before_json=json.dumps(before, ensure_ascii=False) if before else None,
                after_json=json.dumps({"status": "active"}, ensure_ascii=False),
                actor="user",
            )

        return count > 0

    def cleanup_expired_dimensions(self, retention_days: int = 90) -> int:
        """清理过期的画像维度记录

        删除满足以下条件的记录:
        - expires_at IS NOT NULL AND expires_at < now()  (已过期)
        - OR status='suppressed' AND updated_at < now() - retention_days (已抑制超过保留期)

        时间戳以 ISO 字符串存储 字典序与时间序一致 故用字符串比较即可。
        截止时间在 Python 侧计算 避免与 SQLite 内置 datetime('now') 时区/格式不一致。

        Args:
            retention_days: int = 90 => suppressed 记录的保留天数

        Returns:
            int => 删除的记录数
        """
        now_iso = datetime.now().isoformat()
        cutoff_iso = (datetime.now() - timedelta(days=retention_days)).isoformat()

        count = self.execute(
            """
            DELETE FROM user_profile_dimensions
            WHERE (expires_at IS NOT NULL AND expires_at < ?)
               OR (status = 'suppressed' AND updated_at < ?)
            """,
            (now_iso, cutoff_iso),
        )
        return count

    # ------------------------------------------------------------------ 审计日志

    def _insert_audit_log(
        self,
        user_id: str,
        action: str,
        field_key: str | None = None,
        before_json: str | None = None,
        after_json: str | None = None,
        actor: str = "user",
    ) -> None:
        """写入一条画像操作审计记录

        审计日志写入失败不影响主操作 不抛异常。

        Args:
            user_id: str                => 用户 id
            action: str                 => 操作类型 suppress/restore/update_settings
            field_key: str | None       => 涉及的字段 key
            before_json: str | None     => 变更前状态 JSON
            after_json: str | None      => 变更后状态 JSON
            actor: str = "user"         => 操作者 user/system/agent
        """
        now_iso = datetime.now().isoformat()
        audit_id = str(uuid.uuid4())
        try:
            self.execute(
                """
                INSERT INTO profile_audit_log (
                    audit_id, user_id, action, field_key,
                    before_json, after_json, actor, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (audit_id, user_id, action, field_key, before_json, after_json, actor, now_iso),
            )
        except Exception:
            logger.warning(
                "审计日志写入失败 user=%s action=%s field_key=%s",
                user_id,
                action,
                field_key,
                exc_info=True,
            )

    def list_audit_logs(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """查询用户的画像操作审计记录

        Args:
            user_id: str       => 用户 id
            limit: int = 50    => 最多返回条数

        Returns:
            list[dict] => 审计记录列表 按时间倒序
        """
        rows = self.query_all(
            """
            SELECT audit_id, user_id, action, field_key,
                   before_json, after_json, actor, created_at
            FROM profile_audit_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ 版本持久化

    def get_next_profile_version(self, user_id: str) -> int:
        """获取并自增用户的画像版本号 (持久化到 profile_versions 表)

        使用单条 INSERT ... SELECT COALESCE(MAX(version), 0) + 1 原子自增
        消除原 SELECT MAX + INSERT 两步的竞态条件。
        SQLite 写入串行化保证并发安全。
        profile_versions 表由迁移系统创建 (V004)。

        Args:
            user_id: str => 用户 id

        Returns:
            int => 新的版本号 (从 1 开始)
        """
        now_iso = datetime.now().isoformat()

        # 单条原子 INSERT: 子查询 MAX(version)+1 与 INSERT 在同一语句内
        # SQLite 写串行化保证不会有两个并发 INSERT 算出相同 version
        self.execute(
            """
            INSERT INTO profile_versions (user_id, version, generated_at)
            VALUES (?, (SELECT COALESCE(MAX(version), 0) + 1 FROM profile_versions WHERE user_id = ?), ?)
            """,
            (user_id, user_id, now_iso),
        )

        # 回读刚写入的版本号
        row = self.query_one(
            "SELECT MAX(version) as max_ver FROM profile_versions WHERE user_id = ?",
            (user_id,),
        )
        return row["max_ver"] if row and row["max_ver"] is not None else 1

    def delete_all_dimensions(self, user_id: str) -> int:
        """删除用户的所有画像维度记录 (被遗忘权 P2-16)

        物理删除 user_profile_dimensions 中该用户的所有记录。
        同时写入审计日志 便于事后追溯。
        注意: 不删除 memory_settings 表的记录 (由 UserStore 管理)。

        Args:
            user_id: str => 用户 id

        Returns:
            int => 删除的记录数
        """
        # 先记录审计日志
        self._insert_audit_log(
            user_id=user_id,
            action="delete_all",
            field_key=None,
            before_json=None,
            after_json=None,
            actor="user",
        )

        count = self.execute(
            "DELETE FROM user_profile_dimensions WHERE user_id = ?",
            (user_id,),
        )
        return count

    def export_all_dimensions(self, user_id: str) -> list[dict]:
        """导出用户的所有画像维度记录 (数据导出 P2-16)

        返回该用户全部画像维度的完整数据 包括 active 和 suppressed。
        供 GDPR 数据导出使用。

        Args:
            user_id: str => 用户 id

        Returns:
            list[dict] => 全部维度记录列表
        """
        return self.list_dimensions(user_id, status_filter=None)
