# backend/agent/learning/evidence_store.py

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.core.stores.sqlite_connection import connect_sqlite


class LearningEvidenceStore:
    """
    学习证据存储层。

    Mastery 只回答“当前掌握度大约是多少”；Learning Evidence 记录这个判断
    是怎样产生的：是否独立完成、用了几级提示、是否能解释、是否能迁移、
    学生自报信心以及错误类型等。
    """

    ERROR_TYPES = {
        "conceptual",
        "procedural",
        "strategic",
        "representation",
        "prerequisite",
        "careless",
        "unknown",
    }

    def __init__(
        self,
        database_path: str | Path = "data/learning_evidence.db",
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_evidence (
                    id TEXT PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    kp_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    correct INTEGER,
                    self_confidence REAL,
                    evidence_reliability REAL NOT NULL DEFAULT 1.0,
                    hint_level INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 1,
                    independent INTEGER,
                    recall_score REAL,
                    explanation_score REAL,
                    transfer_score REAL,
                    error_type TEXT,
                    misconception TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_evidence_user_kp_time
                ON learning_evidence(user_name, kp_id, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_evidence_user_time
                ON learning_evidence(user_name, created_at DESC)
                """
            )

    @staticmethod
    def _clamp_optional(value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.0, min(1.0, float(value)))

    def record(
        self,
        *,
        user_name: str,
        kp_id: str,
        activity_type: str,
        correct: bool | None = None,
        self_confidence: float | None = None,
        evidence_reliability: float = 1.0,
        hint_level: int = 0,
        attempts: int = 1,
        independent: bool | None = None,
        recall_score: float | None = None,
        explanation_score: float | None = None,
        transfer_score: float | None = None,
        error_type: str | None = None,
        misconception: str | None = None,
    ) -> dict:
        user_name = user_name.strip()
        kp_id = kp_id.strip()
        activity_type = activity_type.strip() or "practice"

        if not user_name:
            raise ValueError("user_name 不能为空")
        if not kp_id:
            raise ValueError("kp_id 不能为空")

        hint_level = max(0, min(5, int(hint_level)))
        attempts = max(1, int(attempts))
        evidence_reliability = max(0.0, min(1.0, float(evidence_reliability)))

        normalized_error_type = (error_type or "").strip().lower() or None
        if (
            normalized_error_type is not None
            and normalized_error_type not in self.ERROR_TYPES
        ):
            raise ValueError(
                f"不支持的 error_type={normalized_error_type!r}"
            )

        normalized_misconception = (misconception or "").strip() or None
        evidence_id = uuid4().hex
        created_at = datetime.now().isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO learning_evidence (
                    id, user_name, kp_id, activity_type, correct,
                    self_confidence, evidence_reliability,
                    hint_level, attempts, independent,
                    recall_score, explanation_score, transfer_score,
                    error_type, misconception, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    user_name,
                    kp_id,
                    activity_type,
                    None if correct is None else int(correct),
                    self._clamp_optional(self_confidence),
                    evidence_reliability,
                    hint_level,
                    attempts,
                    None if independent is None else int(independent),
                    self._clamp_optional(recall_score),
                    self._clamp_optional(explanation_score),
                    self._clamp_optional(transfer_score),
                    normalized_error_type,
                    normalized_misconception,
                    created_at,
                ),
            )

        return {
            "id": evidence_id,
            "user_name": user_name,
            "kp_id": kp_id,
            "activity_type": activity_type,
            "correct": correct,
            "self_confidence": self._clamp_optional(self_confidence),
            "evidence_reliability": evidence_reliability,
            "hint_level": hint_level,
            "attempts": attempts,
            "independent": independent,
            "recall_score": self._clamp_optional(recall_score),
            "explanation_score": self._clamp_optional(explanation_score),
            "transfer_score": self._clamp_optional(transfer_score),
            "error_type": normalized_error_type,
            "misconception": normalized_misconception,
            "created_at": created_at,
        }

    def get_recent(
        self,
        user_name: str,
        *,
        kp_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        user_name = user_name.strip()
        kp_id = (kp_id or "").strip() or None
        limit = max(1, min(200, int(limit)))

        if not user_name:
            return []

        with self._connect() as connection:
            if kp_id is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM learning_evidence
                    WHERE user_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_name, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM learning_evidence
                    WHERE user_name = ? AND kp_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_name, kp_id, limit),
                ).fetchall()

        results: list[dict] = []
        for row in rows:
            item = dict(row)
            if item["correct"] is not None:
                item["correct"] = bool(item["correct"])
            if item["independent"] is not None:
                item["independent"] = bool(item["independent"])
            results.append(item)
        return results

    def get_summary(
        self,
        user_name: str,
        *,
        kp_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        rows = self.get_recent(user_name, kp_id=kp_id, limit=limit)

        if not rows:
            return {
                "user_name": user_name.strip(),
                "kp_id": (kp_id or "").strip() or None,
                "evidence_count": 0,
                "correct_rate": None,
                "avg_self_confidence": None,
                "avg_hint_level": None,
                "independent_rate": None,
                "avg_recall_score": None,
                "avg_explanation_score": None,
                "avg_transfer_score": None,
                "error_type_counts": {},
                "recent_misconceptions": [],
            }

        def avg(values: list[float]) -> float | None:
            if not values:
                return None
            return round(sum(values) / len(values), 3)

        correct_values = [
            1.0 if row["correct"] else 0.0
            for row in rows
            if row["correct"] is not None
        ]
        self_confidences = [
            float(row["self_confidence"])
            for row in rows
            if row["self_confidence"] is not None
        ]
        independent_values = [
            1.0 if row["independent"] else 0.0
            for row in rows
            if row["independent"] is not None
        ]
        recall_scores = [
            float(row["recall_score"])
            for row in rows
            if row["recall_score"] is not None
        ]
        explanation_scores = [
            float(row["explanation_score"])
            for row in rows
            if row["explanation_score"] is not None
        ]
        transfer_scores = [
            float(row["transfer_score"])
            for row in rows
            if row["transfer_score"] is not None
        ]

        error_counts = Counter(
            row["error_type"]
            for row in rows
            if row["error_type"]
        )

        misconceptions: list[str] = []
        for row in rows:
            value = row.get("misconception")
            if value and value not in misconceptions:
                misconceptions.append(value)
            if len(misconceptions) >= 5:
                break

        return {
            "user_name": user_name.strip(),
            "kp_id": (kp_id or "").strip() or None,
            "evidence_count": len(rows),
            "correct_rate": avg(correct_values),
            "avg_self_confidence": avg(self_confidences),
            "avg_hint_level": avg(
                [float(row["hint_level"]) for row in rows]
            ),
            "independent_rate": avg(independent_values),
            "avg_recall_score": avg(recall_scores),
            "avg_explanation_score": avg(explanation_scores),
            "avg_transfer_score": avg(transfer_scores),
            "error_type_counts": dict(error_counts),
            "recent_misconceptions": misconceptions,
        }
