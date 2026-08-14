"""Unified view over existing research job stores."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    workflow_type: str
    job_id: str
    project_id: str
    user_id: str
    status: str
    created_at: str
    payload: dict

    def to_dict(self) -> dict:
        return {
            "workflow_type": self.workflow_type, "job_id": self.job_id,
            "project_id": self.project_id, "user_id": self.user_id,
            "status": self.status, "created_at": self.created_at,
            "payload": self.payload,
        }

