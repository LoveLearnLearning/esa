"""Migration-owned classroom bindings for teaching conversations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ClassroomConversationStore(BaseSQLiteStore):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _initialize(self) -> None:
        raise RuntimeError("classroom binding schema must be installed by migrations")

    def get(self, conversation_id: str, user_id: str) -> dict | None:
        row = self.query_one(
            "SELECT * FROM classroom_conversation_bindings WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
        )
        return dict(row) if row is not None else None

    def bind(
        self,
        *,
        conversation_id: str,
        user_id: str,
        class_id: str,
        assignment_id: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        self.execute(
            """INSERT INTO classroom_conversation_bindings
               (conversation_id,user_id,class_id,assignment_id,created_at,updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(conversation_id) DO UPDATE SET
               class_id=excluded.class_id,assignment_id=excluded.assignment_id,
               updated_at=excluded.updated_at
               WHERE classroom_conversation_bindings.user_id=excluded.user_id""",
            (conversation_id, user_id, class_id, assignment_id, now, now),
        )
        item = self.get(conversation_id, user_id)
        if item is None:
            raise PermissionError("conversation binding belongs to another user")
        return item

    def unbind(self, conversation_id: str, user_id: str) -> bool:
        return self.execute(
            "DELETE FROM classroom_conversation_bindings WHERE conversation_id=? AND user_id=?",
            (conversation_id,user_id),
        ) > 0
