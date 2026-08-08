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
    """结构化用户画像维度、审计日志与版本号的 SQLite 存储层。"""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
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
                "CREATE INDEX IF NOT EXISTS idx_audit_user_id "
                "ON profile_audit_log(user_id)"
            )
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

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
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
        """原子写入/更新画像维度；同一 field_key 更新时 version 自增。"""
        now_iso = datetime.now().isoformat()
        value_json = json.dumps(value, ensure_ascii=False)
        source_json = json.dumps(source_memory_ids or [], ensure_ascii=False)

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
                source_json,
                expires_at,
                now_iso,
                now_iso,
            ),
        )
        return count > 0

    def get_dimension(
        self,
        user_id: str,
        field_key: str,
        *,
        include_expired: bool = False,
    ) -> dict | None:
        """读取单个画像维度；默认不返回已过期数据。"""
        if include_expired:
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
        else:
            now_iso = datetime.now().isoformat()
            row = self.query_one(
                """
                SELECT user_id, field_key, value_json, origin, confidence, status,
                       source_memory_ids_json, last_confirmed_at, expires_at, version,
                       created_at, updated_at
                FROM user_profile_dimensions
                WHERE user_id = ? AND field_key = ?
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (user_id, field_key, now_iso),
            )

        return None if row is None else self._row_to_dict(row)

    def list_dimensions(
        self,
        user_id: str,
        status_filter: str | None = None,
        *,
        include_expired: bool = False,
    ) -> list[dict]:
        """列出画像维度；运行时默认 fail-closed 排除已过期记录。"""
        clauses = ["user_id = ?"]
        params: list[object] = [user_id]

        if status_filter is not None:
            clauses.append("status = ?")
            params.append(status_filter)

        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(datetime.now().isoformat())

        where = " AND ".join(clauses)
        rows = self.query_all(
            f"""
            SELECT user_id, field_key, value_json, origin, confidence, status,
                   source_memory_ids_json, last_confirmed_at, expires_at, version,
                   created_at, updated_at
            FROM user_profile_dimensions
            WHERE {where}
            ORDER BY updated_at DESC
            """,
            tuple(params),
        )
        return [self._row_to_dict(row) for row in rows]

    def delete_dimension(
        self,
        user_id: str,
        field_key: str,
        *,
        actor: str = "system",
    ) -> bool:
        """物理删除单个画像维度并记录审计；供受控投影撤销等内部流程使用。"""
        before = self.get_dimension(user_id, field_key, include_expired=True)
        if before is None:
            return False

        count = self.execute(
            "DELETE FROM user_profile_dimensions WHERE user_id = ? AND field_key = ?",
            (user_id, field_key),
        )
        if count > 0:
            self._insert_audit_log(
                user_id=user_id,
                action="delete_dimension",
                field_key=field_key,
                before_json=json.dumps(before, ensure_ascii=False),
                after_json=None,
                actor=actor,
            )
        return count > 0

    def suppress_dimension(self, user_id: str, field_key: str) -> bool:
        now_iso = datetime.now().isoformat()
        before = self.get_dimension(user_id, field_key, include_expired=True)
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
        now_iso = datetime.now().isoformat()
        before = self.get_dimension(user_id, field_key, include_expired=True)
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
        now_iso = datetime.now().isoformat()
        cutoff_iso = (datetime.now() - timedelta(days=retention_days)).isoformat()
        return self.execute(
            """
            DELETE FROM user_profile_dimensions
            WHERE (expires_at IS NOT NULL AND expires_at < ?)
               OR (status = 'suppressed' AND updated_at < ?)
            """,
            (now_iso, cutoff_iso),
        )

    def _insert_audit_log(
        self,
        user_id: str,
        action: str,
        field_key: str | None = None,
        before_json: str | None = None,
        after_json: str | None = None,
        actor: str = "user",
    ) -> None:
        try:
            self.execute(
                """
                INSERT INTO profile_audit_log (
                    audit_id, user_id, action, field_key,
                    before_json, after_json, actor, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    action,
                    field_key,
                    before_json,
                    after_json,
                    actor,
                    datetime.now().isoformat(),
                ),
            )
        except Exception:
            logger.warning(
                "审计日志写入失败 user=%s action=%s field_key=%s",
                user_id,
                action,
                field_key,
                exc_info=True,
            )

    def list_audit_logs(self, user_id: str, limit: int = 50) -> list[dict]:
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

    def get_next_profile_version(self, user_id: str) -> int:
        now_iso = datetime.now().isoformat()
        self.execute(
            """
            INSERT INTO profile_versions (user_id, version, generated_at)
            VALUES (
                ?,
                (SELECT COALESCE(MAX(version), 0) + 1
                 FROM profile_versions WHERE user_id = ?),
                ?
            )
            """,
            (user_id, user_id, now_iso),
        )
        row = self.query_one(
            "SELECT MAX(version) AS max_ver FROM profile_versions WHERE user_id = ?",
            (user_id,),
        )
        return row["max_ver"] if row and row["max_ver"] is not None else 1

    def delete_all_dimensions(self, user_id: str) -> int:
        self._insert_audit_log(
            user_id=user_id,
            action="delete_all",
            actor="user",
        )
        return self.execute(
            "DELETE FROM user_profile_dimensions WHERE user_id = ?",
            (user_id,),
        )

    def export_all_dimensions(self, user_id: str) -> list[dict]:
        """数据导出应包含已过期/已抑制记录，避免导出接口静默丢数据。"""
        return self.list_dimensions(
            user_id,
            status_filter=None,
            include_expired=True,
        )
