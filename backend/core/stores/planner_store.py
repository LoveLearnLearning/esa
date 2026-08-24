"""User-scoped planner persistence."""

from __future__ import annotations

import uuid
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class PlannerStore(BaseSQLiteStore):
    """Persist todos and goals for one authenticated user."""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS planner_todos (
                    todo_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    due_at TEXT,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_planner_todos_user
                ON planner_todos(user_id, done, due_at, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS planner_goals (
                    goal_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    target_at TEXT,
                    progress INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(progress BETWEEN 0 AND 100)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_planner_goals_user
                ON planner_goals(user_id, target_at, created_at DESC)
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _todo(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["done"] = bool(value["done"])
        return value

    @staticmethod
    def _goal(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def list_todos(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            """
            SELECT todo_id, user_id, title, due_at, done, created_at, updated_at
            FROM planner_todos WHERE user_id = ?
            ORDER BY done ASC, COALESCE(due_at, '9999') ASC, created_at DESC
            """,
            (user_id,),
        )
        return [self._todo(row) for row in rows]

    def get_todo(self, todo_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            """
            SELECT todo_id, user_id, title, due_at, done, created_at, updated_at
            FROM planner_todos WHERE todo_id = ? AND user_id = ?
            """,
            (todo_id, user_id),
        )
        return self._todo(row) if row is not None else None

    def create_todo(
        self, user_id: str, title: str, *, due_at: str | None = None
    ) -> dict[str, Any]:
        now = self._now()
        todo_id = str(uuid.uuid4())
        self.execute(
            """
            INSERT INTO planner_todos
                (todo_id, user_id, title, due_at, done, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (todo_id, user_id, title, due_at, now, now),
        )
        item = self.get_todo(todo_id, user_id)
        if item is None:  # pragma: no cover - the preceding insert owns this id
            raise RuntimeError("created todo could not be reloaded")
        return item

    def update_todo(self, todo_id: str, user_id: str, **fields: Any) -> bool:
        allowed = {"title", "due_at", "done"}
        if set(fields) - allowed:
            raise ValueError("unsupported todo field")
        if not fields:
            return self.get_todo(todo_id, user_id) is not None
        values = dict(fields)
        if "done" in values:
            values["done"] = int(bool(values["done"]))
        values["updated_at"] = self._now()
        clause = ", ".join(f"{key} = ?" for key in values)
        return (
            self.execute(
                f"UPDATE planner_todos SET {clause} WHERE todo_id = ? AND user_id = ?",
                (*values.values(), todo_id, user_id),
            )
            > 0
        )

    def delete_todo(self, todo_id: str, user_id: str) -> bool:
        return (
            self.execute(
                "DELETE FROM planner_todos WHERE todo_id = ? AND user_id = ?",
                (todo_id, user_id),
            )
            > 0
        )

    def list_goals(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            """
            SELECT goal_id, user_id, title, description, target_at, progress,
                   created_at, updated_at
            FROM planner_goals WHERE user_id = ?
            ORDER BY CASE WHEN progress = 100 THEN 1 ELSE 0 END,
                     COALESCE(target_at, '9999') ASC, created_at DESC
            """,
            (user_id,),
        )
        return [self._goal(row) for row in rows]

    def get_goal(self, goal_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            """
            SELECT goal_id, user_id, title, description, target_at, progress,
                   created_at, updated_at
            FROM planner_goals WHERE goal_id = ? AND user_id = ?
            """,
            (goal_id, user_id),
        )
        return self._goal(row) if row is not None else None

    def create_goal(
        self,
        user_id: str,
        title: str,
        *,
        description: str = "",
        target_at: str | None = None,
        progress: int = 0,
    ) -> dict[str, Any]:
        now = self._now()
        goal_id = str(uuid.uuid4())
        self.execute(
            """
            INSERT INTO planner_goals
                (goal_id, user_id, title, description, target_at, progress,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (goal_id, user_id, title, description, target_at, progress, now, now),
        )
        item = self.get_goal(goal_id, user_id)
        if item is None:  # pragma: no cover - the preceding insert owns this id
            raise RuntimeError("created goal could not be reloaded")
        return item

    def update_goal(self, goal_id: str, user_id: str, **fields: Any) -> bool:
        allowed = {"title", "description", "target_at", "progress"}
        if set(fields) - allowed:
            raise ValueError("unsupported goal field")
        if not fields:
            return self.get_goal(goal_id, user_id) is not None
        values = {**fields, "updated_at": self._now()}
        clause = ", ".join(f"{key} = ?" for key in values)
        return (
            self.execute(
                f"UPDATE planner_goals SET {clause} WHERE goal_id = ? AND user_id = ?",
                (*values.values(), goal_id, user_id),
            )
            > 0
        )

    def delete_goal(self, goal_id: str, user_id: str) -> bool:
        return (
            self.execute(
                "DELETE FROM planner_goals WHERE goal_id = ? AND user_id = ?",
                (goal_id, user_id),
            )
            > 0
        )
