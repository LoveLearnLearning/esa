"""Authorize classroom resources for a trusted workspace identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.router.models import TrustedIdentity


@dataclass(frozen=True, slots=True)
class ClassroomAuthorization:
    class_authorized: bool
    assignment_authorized: bool
    capabilities: frozenset[str] = frozenset()

    @property
    def authorized(self) -> bool:
        return self.class_authorized and self.assignment_authorized


def authorize_classroom_resources(
    *,
    teaching_store: Any,
    identity: TrustedIdentity,
    workspace_type: str,
    class_id: str | None,
    assignment_id: str | None,
) -> ClassroomAuthorization:
    """Resolve teacher ownership or active student membership for one binding."""

    if class_id is None:
        return ClassroomAuthorization(
            class_authorized=assignment_id is None,
            assignment_authorized=assignment_id is None,
        )
    if workspace_type not in {"learning", "teaching"}:
        return ClassroomAuthorization(False, assignment_id is None)

    classroom = teaching_store.get_class(class_id)
    if classroom is None or classroom.get("status") != "active":
        return ClassroomAuthorization(False, assignment_id is None)

    if workspace_type == "teaching":
        class_authorized = (
            identity.account_role == "teacher"
            and classroom.get("owner_teacher_id") == identity.user_id
        )
        capabilities = frozenset({"classroom", "classroom_management"})
    else:
        membership = teaching_store.get_membership_for_student(
            class_id=class_id,
            student_id=identity.user_id,
        )
        class_authorized = (
            identity.account_role == "student"
            and membership is not None
            and membership.get("status") == "active"
        )
        capabilities = frozenset(
            {"classroom", "own_assignments", "own_submissions", "published_feedback"}
        )

    if not class_authorized:
        return ClassroomAuthorization(False, assignment_id is None)
    if assignment_id is None:
        return ClassroomAuthorization(True, True, capabilities)

    assignment = teaching_store.get_assignment(assignment_id)
    assignment_authorized = (
        assignment is not None and assignment.get("class_id") == class_id
    )
    if workspace_type == "learning":
        assignment_authorized = assignment_authorized and assignment.get("status") in {
            "published",
            "closed",
            "archived",
        }
    if assignment_authorized:
        capabilities = capabilities | {"assignment"}
    return ClassroomAuthorization(True, bool(assignment_authorized), capabilities)
