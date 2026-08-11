"""SQLite persistence for the Student Model V2.

Mastery is a long-term understanding estimate and never decays with time.
Retention is derived at read time from ``last_practiced_at`` and
``stability_days``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from backend.agent.learning.student_model import StudentModel
from backend.core.stores.sqlite_connection import connect_sqlite


class MasteryStore:
    MIN_MASTERY = StudentModel.MIN_MASTERY
    MAX_MASTERY = StudentModel.MAX_MASTERY
    DEFAULT_MASTERY = StudentModel.PRIOR_MASTERY
    REVIEW_THRESHOLD = StudentModel.REVIEW_THRESHOLD
    BASE_STABILITY = StudentModel.INITIAL_STABILITY_DAYS

    def __init__(self, database_path: str | Path = "data/mastery.db") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.__initialize()

    def __connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.database_path)

    def __initialize(self) -> None:
        with self.__connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_mastery (
                    user_name TEXT NOT NULL,
                    kp_id TEXT NOT NULL,
                    mastery_level REAL NOT NULL DEFAULT 50.0,
                    practice_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    last_practiced_at TEXT NOT NULL,
                    last_decay_at TEXT NOT NULL,
                    stability_days REAL NOT NULL DEFAULT 4.0,
                    evidence_weight REAL NOT NULL DEFAULT 0.0,
                    model_version INTEGER NOT NULL DEFAULT 2,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_name, kp_id)
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(user_mastery)"
                ).fetchall()
            }
            if "user_id" in columns and "user_name" not in columns:
                connection.execute(
                    "ALTER TABLE user_mastery RENAME COLUMN user_id TO user_name"
                )
                columns.remove("user_id")
                columns.add("user_name")
            migrations = {
                "stability_days": (
                    "ALTER TABLE user_mastery ADD COLUMN "
                    "stability_days REAL NOT NULL DEFAULT 4.0"
                ),
                "evidence_weight": (
                    "ALTER TABLE user_mastery ADD COLUMN "
                    "evidence_weight REAL NOT NULL DEFAULT 0.0"
                ),
                "model_version": (
                    "ALTER TABLE user_mastery ADD COLUMN "
                    "model_version INTEGER NOT NULL DEFAULT 2"
                ),
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)

    @staticmethod
    def __now_iso() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _unseen(user_name: str, kp_id: str) -> dict:
        return {
            "user_name": user_name,
            "kp_id": kp_id,
            "has_record": False,
            "mastery_level": None,
            "status": "unseen",
            "retention": None,
            "evidence_confidence": 0.0,
            "stability_days": None,
            "needs_review": False,
            "practice_count": 0,
            "correct_count": 0,
            "last_practiced_at": None,
        }

    @staticmethod
    def _row_state(row: sqlite3.Row, *, now: datetime | None = None) -> dict:
        mastery = float(row["mastery_level"])
        stability = float(row["stability_days"])
        weight = float(row["evidence_weight"])
        confidence = StudentModel.evidence_confidence(weight)
        retention = StudentModel.retention(
            last_practiced_at=row["last_practiced_at"],
            stability_days=stability,
            now=now,
        )
        return {
            "user_name": row["user_name"],
            "kp_id": row["kp_id"],
            "has_record": confidence > 0.0,
            "mastery_level": round(mastery, 2),
            "retention": round(retention, 3),
            "evidence_confidence": round(confidence, 3),
            "stability_days": round(stability, 2),
            "evidence_weight": round(weight, 4),
            "status": StudentModel.status(mastery, confidence),
            "needs_review": (
                confidence >= 0.20
                and retention < StudentModel.REVIEW_THRESHOLD
            ),
            "practice_count": int(row["practice_count"]),
            "correct_count": int(row["correct_count"]),
            "last_practiced_at": row["last_practiced_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "model_version": int(row["model_version"]),
        }

    def get(self, user_name: str, kp_id: str) -> dict | None:
        user_name = user_name.strip()
        kp_id = kp_id.strip()
        if not user_name or not kp_id:
            return None
        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT user_name, kp_id, mastery_level, practice_count,
                       correct_count, last_practiced_at, stability_days,
                       evidence_weight, model_version, created_at, updated_at
                FROM user_mastery
                WHERE user_name = ? AND kp_id = ?
                """,
                (user_name, kp_id),
            ).fetchone()
        if row is None or float(row["evidence_weight"]) <= 0.0:
            return None
        return self._row_state(row)

    def get_state(self, user_name: str, kp_id: str) -> dict:
        return self.get(user_name, kp_id) or self._unseen(
            user_name.strip(), kp_id.strip()
        )

    def get_mastery_level(self, user_name: str, kp_id: str) -> float:
        record = self.get(user_name, kp_id)
        return (
            self.DEFAULT_MASTERY
            if record is None
            else float(record["mastery_level"])
        )

    def apply_evidence(
        self,
        *,
        user_name: str,
        kp_id: str,
        activity_type: str,
        correct: bool | None,
        evidence_reliability: float = 1.0,
        hint_level: int = 0,
        attempts: int = 1,
        independent: bool | None = None,
        recall_score: float | None = None,
        explanation_score: float | None = None,
        transfer_score: float | None = None,
    ) -> dict:
        user_name = user_name.strip()
        kp_id = kp_id.strip()
        if not user_name:
            raise ValueError("user_name 不能为空")
        if not kp_id:
            raise ValueError("kp_id 不能为空")

        signal = StudentModel.evidence_signal(
            activity_type=activity_type,
            correct=correct,
            evidence_reliability=evidence_reliability,
            hint_level=hint_level,
            attempts=attempts,
            independent=independent,
            recall_score=recall_score,
            explanation_score=explanation_score,
            transfer_score=transfer_score,
        )
        now_iso = self.__now_iso()
        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT user_name, kp_id, mastery_level, practice_count,
                       correct_count, last_practiced_at, stability_days,
                       evidence_weight, model_version, created_at, updated_at
                FROM user_mastery
                WHERE user_name = ? AND kp_id = ?
                """,
                (user_name, kp_id),
            ).fetchone()

            if row is None and signal.performance is None:
                return self._unseen(user_name, kp_id)

            if row is None:
                mastery = StudentModel.PRIOR_MASTERY
                practice_count = 0
                correct_count = 0
                stability_days = StudentModel.INITIAL_STABILITY_DAYS
                evidence_weight = 0.0
                created_at = now_iso
            else:
                mastery = float(row["mastery_level"])
                practice_count = int(row["practice_count"])
                correct_count = int(row["correct_count"])
                stability_days = float(row["stability_days"])
                evidence_weight = float(row["evidence_weight"])
                created_at = row["created_at"]

            old_mastery = mastery
            mastery, evidence_weight = StudentModel.update_mastery(
                mastery=mastery,
                evidence_weight=evidence_weight,
                signal=signal,
            )
            stability_days = StudentModel.update_stability(
                stability_days=stability_days,
                mastery=mastery,
                signal=signal,
            )
            if signal.performance is not None:
                practice_count += 1
                if correct is True:
                    correct_count += 1

            connection.execute(
                """
                INSERT INTO user_mastery (
                    user_name, kp_id, mastery_level, practice_count,
                    correct_count, last_practiced_at, last_decay_at,
                    stability_days, evidence_weight, model_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?, ?)
                ON CONFLICT(user_name, kp_id) DO UPDATE SET
                    mastery_level = excluded.mastery_level,
                    practice_count = excluded.practice_count,
                    correct_count = excluded.correct_count,
                    last_practiced_at = excluded.last_practiced_at,
                    last_decay_at = excluded.last_decay_at,
                    stability_days = excluded.stability_days,
                    evidence_weight = excluded.evidence_weight,
                    model_version = 2,
                    updated_at = excluded.updated_at
                """,
                (
                    user_name,
                    kp_id,
                    round(mastery, 4),
                    practice_count,
                    correct_count,
                    now_iso,
                    now_iso,
                    round(stability_days, 4),
                    round(evidence_weight, 4),
                    created_at,
                    now_iso,
                ),
            )
            updated_row = connection.execute(
                """
                SELECT user_name, kp_id, mastery_level, practice_count,
                       correct_count, last_practiced_at, stability_days,
                       evidence_weight, model_version, created_at, updated_at
                FROM user_mastery
                WHERE user_name = ? AND kp_id = ?
                """,
                (user_name, kp_id),
            ).fetchone()

        state = self._row_state(updated_row)
        state.update(
            {
                "old_mastery": round(old_mastery, 2),
                "mastery_delta": round(mastery - old_mastery, 2),
                "signal_performance": (
                    None
                    if signal.performance is None
                    else round(signal.performance, 3)
                ),
                "evidence_quality": round(signal.quality, 3),
            }
        )
        return state

    def record_answer(
        self,
        user_name: str,
        kp_id: str,
        correct: bool,
        confidence: float = 1.0,
    ) -> dict:
        return self.apply_evidence(
            user_name=user_name,
            kp_id=kp_id,
            activity_type="practice",
            correct=correct,
            evidence_reliability=confidence,
        )

    def apply_decay(self, user_name: str) -> int:
        """Compatibility no-op: V2 mastery must never decay."""
        return 0

    def list_for_user(
        self,
        user_name: str,
        *,
        kp_ids: set[str] | None = None,
    ) -> list[dict]:
        user_name = user_name.strip()
        if not user_name:
            return []
        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT user_name, kp_id, mastery_level, practice_count,
                       correct_count, last_practiced_at, stability_days,
                       evidence_weight, model_version, created_at, updated_at
                FROM user_mastery
                WHERE user_name = ? AND evidence_weight > 0
                """,
                (user_name,),
            ).fetchall()
        return [
            self._row_state(row)
            for row in rows
            if kp_ids is None or row["kp_id"] in kp_ids
        ]

    def _top(self, user_name: str, k: int, *, ascending: bool) -> list[dict]:
        states = self.list_for_user(user_name)
        states.sort(
            key=lambda item: float(item["mastery_level"]),
            reverse=not ascending,
        )
        return states[: max(0, k)]

    def get_top_weak(self, user_name: str, k: int = 3) -> list[dict]:
        return self._top(user_name, k, ascending=True)

    def get_top_strong(self, user_name: str, k: int = 3) -> list[dict]:
        return self._top(user_name, k, ascending=False)

    def get_report(
        self,
        user_name: str,
        course: str | None = None,
        kg_store=None,
    ) -> dict:
        course_ids: set[str] | None = None
        if course:
            if kg_store is None:
                raise ValueError("kg_store is required when course is specified")
            course_ids = {item["id"] for item in kg_store.get_course_points(course)}
        points = self.list_for_user(user_name, kp_ids=course_ids)
        weak = sorted(points, key=lambda item: item["mastery_level"])[:5]
        strong = sorted(
            points, key=lambda item: item["mastery_level"], reverse=True
        )[:5]
        stale = sorted(
            [item for item in points if item["needs_review"]],
            key=lambda item: item["retention"],
        )[:5]
        return {
            "user_name": user_name.strip(),
            "course": course,
            "total_points": len(points),
            "avg_mastery": (
                round(
                    sum(float(item["mastery_level"]) for item in points)
                    / len(points),
                    2,
                )
                if points
                else 0.0
            ),
            "weak_points": weak,
            "strong_points": strong,
            "stale_points": stale,
        }

    def get_priority_ranking(
        self,
        user_name: str,
        course: str,
        weeks_to_exam: int,
        total_weeks: int,
        kg_store,
    ) -> list[dict]:
        points = kg_store.get_course_points(course.strip())
        if not user_name.strip() or not points:
            return []
        states = {
            state["kp_id"]: state for state in self.list_for_user(user_name)
        }
        exam_urgency = (
            max(0.0, 1.0 - weeks_to_exam / total_weeks)
            if total_weeks > 0
            else 0.0
        )
        results: list[dict] = []
        for point in points:
            state = states.get(point["id"])
            if state is None:
                mastery_need = 0.45
                review_pressure = 0.0
                mastery_level = None
                practice_count = 0
                confidence = 0.0
                retention = None
            else:
                mastery_level = float(state["mastery_level"])
                mastery_need = 1.0 - mastery_level / 100.0
                retention = float(state["retention"])
                review_pressure = max(
                    0.0,
                    (StudentModel.REVIEW_THRESHOLD - retention)
                    / StudentModel.REVIEW_THRESHOLD,
                )
                practice_count = int(state["practice_count"])
                confidence = float(state["evidence_confidence"])
            weak_prereqs = self.get_weak_prerequisites(
                user_name=user_name,
                kp_id=point["id"],
                kg_store=kg_store,
            )
            prerequisite_risk = min(1.0, len(weak_prereqs) / 3.0)
            priority = (
                0.35 * mastery_need
                + 0.20 * review_pressure
                + 0.20 * float(point["weight"])
                + 0.15 * exam_urgency
                + 0.10 * prerequisite_risk
            )
            results.append(
                {
                    "kp_id": point["id"],
                    "name": point["name"],
                    "course": point["course"],
                    "weight": point["weight"],
                    "mastery_level": mastery_level,
                    "retention": retention,
                    "evidence_confidence": confidence,
                    "practice_count": practice_count,
                    "has_record": state is not None,
                    "priority": round(priority, 4),
                }
            )
        results.sort(key=lambda item: item["priority"], reverse=True)
        return results

    def get_review_timing(
        self,
        user_name: str,
        kp_id: str,
        threshold: float | None = None,
    ) -> dict:
        state = self.get(user_name, kp_id)
        if state is None:
            return {
                "has_record": False,
                "needs_review": False,
                "current_retention": None,
                "days_until_review": None,
                "recommended_date": None,
                "stability_days": None,
                "practice_count": 0,
            }
        normalized_threshold = (
            StudentModel.REVIEW_THRESHOLD if threshold is None else threshold
        )
        total_days = StudentModel.days_until_threshold(
            stability_days=float(state["stability_days"]),
            threshold=normalized_threshold,
        )
        last = datetime.fromisoformat(state["last_practiced_at"])
        now = datetime.now(last.tzinfo) if last.tzinfo is not None else datetime.now()
        elapsed = max(0.0, (now - last).total_seconds() / 86400.0)
        remaining = max(0, int(total_days - elapsed))
        return {
            "has_record": True,
            "needs_review": float(state["retention"]) < normalized_threshold,
            "current_retention": state["retention"],
            "days_until_review": remaining,
            "recommended_date": (
                now + timedelta(days=remaining)
            ).date().isoformat(),
            "stability_days": state["stability_days"],
            "practice_count": state["practice_count"],
        }

    def get_weak_prerequisites(
        self,
        user_name: str,
        kp_id: str,
        kg_store,
        mastery_threshold: float = 50.0,
        max_depth: int = 5,
    ) -> list[dict]:
        prerequisites = kg_store.get_prerequisites(
            kp_id.strip(), max_depth=max_depth
        )
        states = {
            state["kp_id"]: state for state in self.list_for_user(user_name)
        }
        weak: list[dict] = []
        for point in prerequisites:
            if point["kp_id"] == kp_id or int(point.get("depth", 0)) <= 0:
                continue
            state = states.get(point["kp_id"])
            if state is not None and float(state["mastery_level"]) >= mastery_threshold:
                continue
            weak.append(
                {
                    "kp_id": point["kp_id"],
                    "name": point["name"],
                    "course": point["course"],
                    "depth": point["depth"],
                    "mastery_level": (
                        None if state is None else state["mastery_level"]
                    ),
                    "status": "unseen" if state is None else state["status"],
                    "retention": None if state is None else state["retention"],
                    "evidence_confidence": (
                        0.0 if state is None else state["evidence_confidence"]
                    ),
                }
            )
        weak.sort(key=lambda item: int(item["depth"]), reverse=True)
        return weak
