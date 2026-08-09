from __future__ import annotations

import uuid
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
            )
        }

    def list_courses(self, user_id: str) -> list[dict]:
        rows = self.query_all(
            """
            SELECT id, name, teacher, location, weekday, start_period,
                   end_period, start_week, end_week, color_value
            FROM schedule_courses
            WHERE user_id = ?
            ORDER BY weekday, start_period, name
            """,
            (user_id,),
        )
        return [self._course(row) for row in rows]

    def get_course(self, user_id: str, course_id: str) -> dict | None:
        row = self.query_one(
            """
            SELECT id, name, teacher, location, weekday, start_period,
                   end_period, start_week, end_week, color_value
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

    def upsert_course(self, user_id: str, course: dict) -> dict:
        course_id = str(course.get("id") or uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.execute(
            """
            INSERT INTO schedule_courses (
                id, user_id, name, teacher, location, weekday, start_period,
                end_period, start_week, end_week, color_value, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                now,
                now,
            ),
        )
        return {**course, "id": course_id}

    def import_courses(self, user_id: str, courses: list[dict]) -> list[dict]:
        imported: list[dict] = []
        existing = {
            (
                item["name"],
                item["weekday"],
                item["start_period"],
                item["end_period"],
                item["start_week"],
                item["end_week"],
            )
            for item in self.list_courses(user_id)
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
            imported.append(self.upsert_course(user_id, course))
            existing.add(identity)
        return imported

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
