# backend/core/stores/conversation_summary_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ConversationSummaryStore(BaseSQLiteStore):
    """Stores lossless pointers plus generated summaries for old chat context."""

    def __init__(self, database_path: str | Path) -> None:
        """初始化 `ConversationSummaryStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                summarized_through_message_id INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL,
                source_message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id)
                    REFERENCES conversations(conversation_id) ON DELETE CASCADE
            )
            """
        )
        self.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_summaries_updated
            ON conversation_summaries(updated_at)
            """
        )

    @staticmethod
    def _now() -> str:
        """处理 `_now` 相关逻辑。"""
        return datetime.now(timezone.utc).isoformat()

    def get(self, conversation_id: str) -> dict | None:
        """获取 `get` 相关数据。"""
        row = self.query_one(
            """
            SELECT conversation_id, summarized_through_message_id, summary,
                   source_message_count, created_at, updated_at
            FROM conversation_summaries
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        return dict(row) if row is not None else None

    def list_offline_candidates(
        self,
        *,
        offline_before: str,
        limit: int = 20,
    ) -> list[dict]:
        """列出 `offline candidates` 相关数据。

        Args:
            offline_before: str => `offline_before` 参数。
            limit: int => 返回数量上限。

        Returns:
            list[dict] => 处理结果。
        """
        now = self._now()
        rows = self.query_all(
            """
            SELECT c.conversation_id, c.user_id,
                   COALESCE(s.summarized_through_message_id, 0)
                       AS summarized_through_message_id,
                   COALESCE(s.summary, '') AS summary,
                   COALESCE(s.source_message_count, 0) AS source_message_count
            FROM conversations c
            LEFT JOIN user_presence p ON p.user_id = c.user_id
            LEFT JOIN conversation_summaries s
                   ON s.conversation_id = c.conversation_id
            LEFT JOIN conversation_turn_leases l
                   ON l.conversation_id = c.conversation_id
                  AND l.expires_at > ?
            WHERE l.conversation_id IS NULL
              AND (
                    p.user_id IS NULL
                    OR p.is_online = 0
                    OR p.last_seen_at <= ?
                  )
              AND EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id = c.conversation_id
                      AND m.id > COALESCE(s.summarized_through_message_id, 0)
                  )
            ORDER BY c.updated_at ASC
            LIMIT ?
            """,
            (now, offline_before, limit),
        )
        return [dict(row) for row in rows]

    def get_messages_after(
        self,
        conversation_id: str,
        message_id: int,
    ) -> list[dict]:
        """获取 `messages after` 相关数据。

        Args:
            conversation_id: str => 对话 ID。
            message_id: int => 消息 ID。

        Returns:
            list[dict] => 处理结果。
        """
        rows = self.query_all(
            """
            SELECT id, role, content, name, is_visible, created_at
            FROM messages
            WHERE conversation_id = ? AND id > ?
            ORDER BY id ASC
            """,
            (conversation_id, message_id),
        )
        return [dict(row) for row in rows]

    def upsert(
        self,
        *,
        conversation_id: str,
        summarized_through_message_id: int,
        summary: str,
        source_message_count: int,
    ) -> bool:
        """处理 `upsert` 相关逻辑。

        Args:
            conversation_id: str => 对话 ID。
            summarized_through_message_id: int => summarized through message ID。
            summary: str => `summary` 参数。
            source_message_count: int => `source_message_count` 参数。

        Returns:
            bool => 处理结果。
        """
        now = self._now()
        changed = self.execute(
            """
            INSERT INTO conversation_summaries (
                conversation_id,
                summarized_through_message_id,
                summary,
                source_message_count,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                summarized_through_message_id =
                    excluded.summarized_through_message_id,
                summary = excluded.summary,
                source_message_count = excluded.source_message_count,
                updated_at = excluded.updated_at
            WHERE excluded.summarized_through_message_id
                  > conversation_summaries.summarized_through_message_id
            """,
            (
                conversation_id,
                summarized_through_message_id,
                summary,
                source_message_count,
                now,
                now,
            ),
        )
        return changed > 0

    def upsert_if_offline(
        self,
        *,
        conversation_id: str,
        summarized_through_message_id: int,
        summary: str,
        source_message_count: int,
        offline_before: str,
    ) -> bool:
        """Persist a summary only if the user is still offline and no turn is active.

        The eligibility check and write share one ``BEGIN IMMEDIATE`` transaction.
        This prevents a late model response from advancing the summary boundary after
        the user has returned or a new chat turn has started.
        """
        now = self._now()
        connection = self._connect()
        connection.isolation_level = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            eligible = connection.execute(
                """
                SELECT 1
                FROM conversations c
                LEFT JOIN user_presence p ON p.user_id = c.user_id
                WHERE c.conversation_id = ?
                  AND NOT EXISTS (
                        SELECT 1 FROM conversation_turn_leases l
                        WHERE l.conversation_id = c.conversation_id
                          AND l.expires_at > ?
                  )
                  AND (
                        p.user_id IS NULL
                        OR p.is_online = 0
                        OR p.last_seen_at <= ?
                  )
                """,
                (conversation_id, now, offline_before),
            ).fetchone()
            if eligible is None:
                connection.rollback()
                return False

            cursor = connection.execute(
                """
                INSERT INTO conversation_summaries (
                    conversation_id,
                    summarized_through_message_id,
                    summary,
                    source_message_count,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    summarized_through_message_id =
                        excluded.summarized_through_message_id,
                    summary = excluded.summary,
                    source_message_count = excluded.source_message_count,
                    updated_at = excluded.updated_at
                WHERE excluded.summarized_through_message_id
                      > conversation_summaries.summarized_through_message_id
                """,
                (
                    conversation_id,
                    summarized_through_message_id,
                    summary,
                    source_message_count,
                    now,
                    now,
                ),
            )
            connection.commit()
            return cursor.rowcount > 0
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
