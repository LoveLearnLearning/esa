from __future__ import annotations

import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore

DEFAULT_SETTINGS = {
    "morning_period_count": 4,
    "afternoon_period_count": 4,
    "evening_period_count": 4,
    "morning_start_minutes": 480,
    "afternoon_start_minutes": 840,
    "evening_start_minutes": 1140,
    "period_duration_minutes": 45,
    "break_duration_minutes": 10,
    "term_start_date": "",
}


DEFAULT_TABLE_NAME = "默认课表"


def ensure_schedule_tables_schema(connection) -> None:
    """建 schedule_tables、给 schedule_courses 补 table_id 并回填老数据。

    幂等：store 初始化与版本化迁移共用，老库的既有课程会归入自动创建
    的"默认课表"。migrations.py 的 V8 也调用本函数，两条路径保持一致。
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_tables (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_tables_user "
        "ON schedule_tables(user_id)"
    )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(schedule_courses)").fetchall()
    }
    if "table_id" not in columns:
        connection.execute("ALTER TABLE schedule_courses ADD COLUMN table_id TEXT")
    now = datetime.now(timezone.utc).isoformat()
    orphan_users = [
        row["user_id"]
        for row in connection.execute(
            "SELECT DISTINCT user_id FROM schedule_courses WHERE table_id IS NULL"
        ).fetchall()
    ]
    for user_id in orphan_users:
        row = connection.execute(
            "SELECT id FROM schedule_tables WHERE user_id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT id FROM schedule_tables WHERE user_id = ? "
                "ORDER BY created_at LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is not None:
            table_id = row["id"]
        else:
            table_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO schedule_tables "
                "(id, user_id, name, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (table_id, user_id, DEFAULT_TABLE_NAME, now, now),
            )
        connection.execute(
            "UPDATE schedule_courses SET table_id = ? "
            "WHERE user_id = ? AND table_id IS NULL",
            (table_id, user_id),
        )


class ScheduleStore(BaseSQLiteStore):
    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schedule_courses (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    teacher TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    weekday INTEGER NOT NULL,
                    start_period INTEGER NOT NULL,
                    end_period INTEGER NOT NULL,
                    start_week INTEGER NOT NULL,
                    end_week INTEGER NOT NULL,
                    color_value INTEGER NOT NULL DEFAULT 4280701931,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(weekday BETWEEN 1 AND 7),
                    CHECK(start_period BETWEEN 1 AND 24),
                    CHECK(end_period BETWEEN start_period AND 24),
                    CHECK(start_week BETWEEN 1 AND 30),
                    CHECK(end_week BETWEEN start_week AND 30)
                );
                CREATE INDEX IF NOT EXISTS idx_schedule_courses_user
                ON schedule_courses(user_id, weekday, start_period);
                CREATE TABLE IF NOT EXISTS schedule_settings (
                    user_id TEXT PRIMARY KEY,
                    morning_period_count INTEGER NOT NULL DEFAULT 4,
                    afternoon_period_count INTEGER NOT NULL DEFAULT 4,
                    evening_period_count INTEGER NOT NULL DEFAULT 4,
                    morning_start_minutes INTEGER NOT NULL DEFAULT 480,
                    afternoon_start_minutes INTEGER NOT NULL DEFAULT 840,
                    evening_start_minutes INTEGER NOT NULL DEFAULT 1140,
                    period_duration_minutes INTEGER NOT NULL DEFAULT 45,
                    break_duration_minutes INTEGER NOT NULL DEFAULT 10,
                    term_start_date TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(schedule_settings)"
                ).fetchall()
            }
            if "term_start_date" not in columns:
                connection.execute(
                    "ALTER TABLE schedule_settings "
                    "ADD COLUMN term_start_date TEXT NOT NULL DEFAULT ''"
                )
            ensure_schedule_tables_schema(connection)

    @staticmethod
    def _course(row) -> dict:
        return {
            key: row[key]
            for key in (
                "id",
                "name",
                "teacher",
                "location",
                "weekday",
                "start_period",
                "end_period",
                "start_week",
                "end_week",
                "color_value",
                "table_id",
            )
        }

    # ---- 课程表（多张课表）管理 ----

    def list_tables(self, user_id: str) -> list[dict]:
        rows = self.query_all(
            """
            SELECT id, name, is_active FROM schedule_tables
            WHERE user_id = ? ORDER BY created_at, id
            """,
            (user_id,),
        )
        return [
            {"id": row["id"], "name": row["name"], "is_active": bool(row["is_active"])}
            for row in rows
        ]

    def get_table(self, user_id: str, table_id: str) -> dict | None:
        row = self.query_one(
            "SELECT id, name, is_active FROM schedule_tables "
            "WHERE user_id = ? AND id = ?",
            (user_id, table_id),
        )
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "is_active": bool(row["is_active"]),
        }

    def ensure_active_table(self, user_id: str) -> str:
        """返回当前激活课程表 id；没有任何课程表时创建默认课表。"""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM schedule_tables WHERE user_id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            if row is not None:
                return row["id"]
            row = connection.execute(
                "SELECT id FROM schedule_tables WHERE user_id = ? "
                "ORDER BY created_at, id LIMIT 1",
                (user_id,),
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row is not None:
                connection.execute(
                    "UPDATE schedule_tables SET is_active = 1, updated_at = ? "
                    "WHERE id = ?",
                    (now, row["id"]),
                )
                return row["id"]
            table_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO schedule_tables "
                "(id, user_id, name, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (table_id, user_id, DEFAULT_TABLE_NAME, now, now),
            )
            return table_id

    def create_table(self, user_id: str, name: str, *, activate: bool = True) -> dict:
        table_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if activate:
                connection.execute(
                    "UPDATE schedule_tables SET is_active = 0 WHERE user_id = ?",
                    (user_id,),
                )
            connection.execute(
                "INSERT INTO schedule_tables "
                "(id, user_id, name, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (table_id, user_id, name, 1 if activate else 0, now, now),
            )
        return {"id": table_id, "name": name, "is_active": activate}

    def rename_table(self, user_id: str, table_id: str, name: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        return (
            self.execute(
                "UPDATE schedule_tables SET name = ?, updated_at = ? "
                "WHERE user_id = ? AND id = ?",
                (name, now, user_id, table_id),
            )
            > 0
        )

    def activate_table(self, user_id: str, table_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM schedule_tables WHERE user_id = ? AND id = ?",
                (user_id, table_id),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE schedule_tables SET is_active = 0 WHERE user_id = ?",
                (user_id,),
            )
            connection.execute(
                "UPDATE schedule_tables SET is_active = 1, updated_at = ? WHERE id = ?",
                (now, table_id),
            )
            return True

    def delete_table(self, user_id: str, table_id: str) -> list[dict]:
        """删除课程表及其课程，返回被删除的课程。

        最后一张课程表不允许删除（抛 ValueError）；删除的是激活表时，
        自动激活剩余最早创建的一张。
        """
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, is_active FROM schedule_tables WHERE user_id = ? "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            target = next((row for row in rows if row["id"] == table_id), None)
            if target is None:
                return []
            if len(rows) <= 1:
                raise ValueError("至少需要保留一张课程表")
            removed = [
                self._course(row)
                for row in connection.execute(
                    "SELECT id, name, teacher, location, weekday, start_period, "
                    "end_period, start_week, end_week, color_value, table_id "
                    "FROM schedule_courses WHERE user_id = ? AND table_id = ?",
                    (user_id, table_id),
                ).fetchall()
            ]
            connection.execute(
                "DELETE FROM schedule_courses WHERE user_id = ? AND table_id = ?",
                (user_id, table_id),
            )
            connection.execute(
                "DELETE FROM schedule_tables WHERE user_id = ? AND id = ?",
                (user_id, table_id),
            )
            if target["is_active"]:
                fallback = next(row for row in rows if row["id"] != table_id)
                connection.execute(
                    "UPDATE schedule_tables SET is_active = 1, updated_at = ? "
                    "WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), fallback["id"]),
                )
            return removed

    def list_courses(self, user_id: str, table_id: str | None = None) -> list[dict]:
        """列出课程；table_id 为 None 时返回用户全部课程表的课程。"""
        sql = """
            SELECT id, name, teacher, location, weekday, start_period,
                   end_period, start_week, end_week, color_value, table_id
            FROM schedule_courses
            WHERE user_id = ?
            """
        params: tuple = (user_id,)
        if table_id is not None:
            sql += " AND table_id = ?"
            params = (user_id, table_id)
        sql += " ORDER BY weekday, start_period, name"
        return [self._course(row) for row in self.query_all(sql, params)]

    def get_course(self, user_id: str, course_id: str) -> dict | None:
        row = self.query_one(
            """
            SELECT id, name, teacher, location, weekday, start_period,
                   end_period, start_week, end_week, color_value, table_id
            FROM schedule_courses WHERE user_id = ? AND id = ?
            """,
            (user_id, course_id),
        )
        return self._course(row) if row is not None else None

    def get_settings(self, user_id: str) -> dict:
        row = self.query_one(
            """
            SELECT morning_period_count, afternoon_period_count,
                   evening_period_count, morning_start_minutes,
                   afternoon_start_minutes, evening_start_minutes,
                   period_duration_minutes, break_duration_minutes,
                   term_start_date
            FROM schedule_settings WHERE user_id = ?
            """,
            (user_id,),
        )
        return dict(row) if row is not None else dict(DEFAULT_SETTINGS)

    def upsert_course(
        self, user_id: str, course: dict, table_id: str | None = None
    ) -> dict:
        """写入课程。table_id 未指定时：更新已有课程保持原课程表，
        新课程写入当前激活课程表。"""
        course_id = str(course.get("id") or uuid.uuid4())
        if table_id is None:
            table_id = course.get("table_id")
        if table_id is None:
            existing = self.get_course(user_id, course_id)
            table_id = (
                existing["table_id"]
                if existing is not None
                else self.ensure_active_table(user_id)
            )
        now = datetime.now(timezone.utc).isoformat()
        self.execute(
            """
            INSERT INTO schedule_courses (
                id, user_id, name, teacher, location, weekday, start_period,
                end_period, start_week, end_week, color_value, table_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                teacher = excluded.teacher,
                location = excluded.location,
                weekday = excluded.weekday,
                start_period = excluded.start_period,
                end_period = excluded.end_period,
                start_week = excluded.start_week,
                end_week = excluded.end_week,
                color_value = excluded.color_value,
                table_id = excluded.table_id,
                updated_at = excluded.updated_at
            WHERE schedule_courses.user_id = excluded.user_id
            """,
            (
                course_id,
                user_id,
                course["name"],
                course.get("teacher", ""),
                course.get("location", ""),
                course["weekday"],
                course["start_period"],
                course["end_period"],
                course["start_week"],
                course["end_week"],
                course.get("color_value", 0xFF2563EB),
                table_id,
                now,
                now,
            ),
        )
        return {**course, "id": course_id, "table_id": table_id}

    @staticmethod
    def _time_conflicts(a: dict, b: dict) -> bool:
        return (
            a["weekday"] == b["weekday"]
            and a["start_period"] <= b["end_period"]
            and b["start_period"] <= a["end_period"]
            and a["start_week"] <= b["end_week"]
            and b["start_week"] <= a["end_week"]
        )

    def import_courses(
        self, user_id: str, courses: list[dict], table_id: str | None = None
    ) -> tuple[list[dict], list[dict]]:
        """批量导入课程到指定课程表（缺省为当前激活课程表）。

        与该课程表已有课程六元组完全相同的跳过（幂等重复导入）；与该表
        已有课程或本批已导入课程存在时间冲突（同星期、节次与周次范围重
        叠）的也跳过——识别错误的课叠在同一格会让整张课表不可用，宁可
        少导。返回 (imported, skipped_conflicts)。
        """
        if table_id is None:
            table_id = self.ensure_active_table(user_id)
        imported: list[dict] = []
        skipped: list[dict] = []
        kept = self.list_courses(user_id, table_id)
        existing = {
            (
                item["name"],
                item["weekday"],
                item["start_period"],
                item["end_period"],
                item["start_week"],
                item["end_week"],
            )
            for item in kept
        }
        for course in courses:
            identity = (
                course["name"],
                course["weekday"],
                course["start_period"],
                course["end_period"],
                course["start_week"],
                course["end_week"],
            )
            if identity in existing:
                continue
            if any(self._time_conflicts(course, item) for item in kept):
                skipped.append(course)
                continue
            imported.append(self.upsert_course(user_id, course, table_id))
            kept.append(course)
            existing.add(identity)
        return imported, skipped

    def delete_course(self, user_id: str, course_id: str) -> bool:
        return (
            self.execute(
                "DELETE FROM schedule_courses WHERE user_id = ? AND id = ?",
                (user_id, course_id),
            )
            > 0
        )

    def save_settings(self, user_id: str, settings: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        values = {**DEFAULT_SETTINGS, **settings}
        self.execute(
            """
            INSERT INTO schedule_settings (
                user_id, morning_period_count, afternoon_period_count,
                evening_period_count, morning_start_minutes,
                afternoon_start_minutes, evening_start_minutes,
                period_duration_minutes, break_duration_minutes,
                term_start_date, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                morning_period_count = excluded.morning_period_count,
                afternoon_period_count = excluded.afternoon_period_count,
                evening_period_count = excluded.evening_period_count,
                morning_start_minutes = excluded.morning_start_minutes,
                afternoon_start_minutes = excluded.afternoon_start_minutes,
                evening_start_minutes = excluded.evening_start_minutes,
                period_duration_minutes = excluded.period_duration_minutes,
                break_duration_minutes = excluded.break_duration_minutes,
                term_start_date = excluded.term_start_date,
                updated_at = excluded.updated_at
            """,
            (user_id, *values.values(), now),
        )
        return values
