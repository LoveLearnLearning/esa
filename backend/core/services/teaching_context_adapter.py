"""Core adapter exposing a minimal authorized teaching context to Agent tools."""

from __future__ import annotations

from typing import Any


class TeachingContextAdapter:
    def __init__(self, teaching_store: Any) -> None:
        self._store = teaching_store

    def read_teaching_context(
        self,
        *,
        user_id: str,
        class_id: str | None,
        assignment_id: str | None,
    ) -> dict[str, Any]:
        if not class_id:
            raise ValueError("teaching context is not bound to a classroom")
        classroom = self._store.get_class(class_id)
        if (
            classroom is None
            or classroom.get("owner_teacher_id") != user_id
            or classroom.get("status") != "active"
        ):
            raise ValueError("teaching classroom is no longer authorized")

        assignment = None
        if assignment_id:
            candidate = self._store.get_assignment(assignment_id)
            if candidate is None or candidate.get("class_id") != class_id:
                raise ValueError("teaching assignment is no longer authorized")
            assignment = {
                key: candidate.get(key)
                for key in (
                    "assignment_id",
                    "title",
                    "status",
                    "due_at",
                    "total_points",
                )
            }

        return {
            "classroom": {
                key: classroom.get(key)
                for key in (
                    "class_id",
                    "name",
                    "canonical_course",
                    "term",
                    "status",
                )
            },
            "assignment": assignment,
        }
