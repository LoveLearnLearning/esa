# backend/core/stores/group_store.py

from __future__ import annotations

import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class GroupStore(BaseSQLiteStore):
    """对话分组读写类。"""

    _UPDATEABLE_FIELDS = frozenset(
        {"name", "description", "custom_instruction", "style", "tone"}
    )

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    custom_instruction TEXT NOT NULL DEFAULT '',
                    style TEXT,
                    tone TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_groups_user
                ON groups (user_id, updated_at)
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_group(
        self,
        user_id: str,
        name: str,
        description: str = "",
        custom_instruction: str = "",
        style: str | None = None,
        tone: str | None = None,
        group_limit: int | None = None,
    ) -> dict | None:
        now = self._now()
        group: dict = {
            "group_id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": name,
            "description": description,
            "custom_instruction": custom_instruction,
            "style": style,
            "tone": tone,
            "created_at": now,
            "updated_at": now,
        }

        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if group_limit is not None:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM groups WHERE user_id = ?",
                        (user_id,),
                    ).fetchone()
                    if int(row["count"]) >= group_limit:
                        connection.rollback()
                        return None

                connection.execute(
                    """
                    INSERT INTO groups (
                        group_id, user_id, name, description,
                        custom_instruction, style, tone, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group["group_id"],
                        group["user_id"],
                        group["name"],
                        group["description"],
                        group["custom_instruction"],
                        group["style"],
                        group["tone"],
                        group["created_at"],
                        group["updated_at"],
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return group

    def get_group(
        self,
        group_id: str,
        user_id: str | None = None,
    ) -> dict | None:
        sql = """
            SELECT g.group_id, g.user_id, g.name, g.description,
                   g.custom_instruction, g.style, g.tone,
                   g.created_at, g.updated_at,
                   (
                       SELECT COUNT(*)
                       FROM conversations c
                       WHERE c.group_id = g.group_id
                         AND c.user_id = g.user_id
                   ) AS conversation_count
            FROM groups g
            WHERE g.group_id = ?
        """
        params: tuple = (group_id,)
        if user_id is not None:
            sql += " AND g.user_id = ?"
            params += (user_id,)

        row = self.query_one(sql, params)
        return dict(row) if row is not None else None

    def list_groups(self, user_id: str) -> list[dict]:
        rows = self.query_all(
            """
            SELECT g.group_id, g.user_id, g.name, g.description,
                   g.custom_instruction, g.style, g.tone,
                   g.created_at, g.updated_at,
                   COUNT(c.conversation_id) AS conversation_count
            FROM groups g
            LEFT JOIN conversations c
              ON c.group_id = g.group_id
             AND c.user_id = g.user_id
            WHERE g.user_id = ?
            GROUP BY g.group_id
            ORDER BY g.updated_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]

    def update_group(
        self,
        group_id: str,
        user_id: str | None = None,
        **fields: str | None,
    ) -> bool:
        unknown = set(fields) - self._UPDATEABLE_FIELDS
        if unknown:
            raise ValueError(f"不允许更新的字段: {sorted(unknown)}")
        if not fields:
            return self.get_group(group_id, user_id) is not None

        updates = dict(fields)
        updates["updated_at"] = self._now()
        set_clause = ", ".join(f"{name} = ?" for name in updates)
        sql = f"UPDATE groups SET {set_clause} WHERE group_id = ?"
        params: tuple = (*updates.values(), group_id)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        return self.execute(sql, params) > 0

    def delete_group(self, group_id: str, user_id: str) -> bool:
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                exists = connection.execute(
                    """
                    SELECT 1 FROM groups
                    WHERE group_id = ? AND user_id = ?
                    """,
                    (group_id, user_id),
                ).fetchone()
                if exists is None:
                    connection.rollback()
                    return False

                connection.execute(
                    """
                    UPDATE conversations
                    SET group_id = NULL
                    WHERE group_id = ? AND user_id = ?
                    """,
                    (group_id, user_id),
                )
                cursor = connection.execute(
                    """
                    DELETE FROM groups
                    WHERE group_id = ? AND user_id = ?
                    """,
                    (group_id, user_id),
                )
                connection.commit()
                return cursor.rowcount > 0
            except Exception:
                connection.rollback()
                raise
