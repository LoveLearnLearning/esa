# backend/core/workflows/research/actions.py

"""Agent Action adapters for the existing research workflow facade."""

from __future__ import annotations

from typing import Any

from backend.core.workflows.research.facade import ResearchWorkflowFacade

RESEARCH_ACTION_TYPES = (
    "start_frontier_tracking",
    "start_research_writing",
    "start_dataset_analysis",
)


def validate_research_action(
    action: dict[str, Any],
    *,
    project_store: Any,
    writing_store: Any,
    data_store: Any,
) -> None:
    """校验 `research action` 相关数据。

    Args:
        action: dict[str, Any] => `action` 参数。
        project_store: Any => `project_store` 参数。
        writing_store: Any => `writing_store` 参数。
        data_store: Any => `data_store` 参数。
    """
    arguments = action["arguments"]
    bound_project_id = action["resource_snapshot"].get("project_id")
    if not bound_project_id:
        raise ValueError("research action is not bound to a project")

    project_id = arguments.get("project_id") or bound_project_id
    if action["action_type"] == "start_research_writing":
        document = writing_store.get_document(
            arguments.get("document_id", ""), action["user_id"]
        )
        if document is None:
            raise ValueError("research document is no longer authorized")
        project_id = document["project_id"]
    elif action["action_type"] == "start_dataset_analysis":
        dataset = data_store.get_dataset(
            arguments.get("dataset_id", ""), action["user_id"]
        )
        if dataset is None:
            raise ValueError("research dataset is no longer authorized")
        project_id = dataset["project_id"]
    elif action["action_type"] != "start_frontier_tracking":
        raise ValueError("unsupported action type")

    if project_id != bound_project_id:
        raise ValueError("research resource is outside the bound project")
    project = project_store.get_project(project_id, action["user_id"])
    if project is None or project["status"] != "active":
        raise ValueError("research project is no longer authorized")


def execute_research_action(
    action: dict[str, Any], facade: ResearchWorkflowFacade
) -> dict[str, Any]:
    """执行 `research action` 相关数据。

    Args:
        action: dict[str, Any] => `action` 参数。
        facade: ResearchWorkflowFacade => `facade` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    arguments = action["arguments"]
    if action["action_type"] == "start_frontier_tracking":
        run = facade.start_frontier_tracking(
            user_id=action["user_id"], **arguments
        )
    elif action["action_type"] == "start_research_writing":
        run = facade.start_research_writing(
            user_id=action["user_id"], **arguments
        )
    elif action["action_type"] == "start_dataset_analysis":
        run = facade.start_dataset_analysis(
            user_id=action["user_id"], **arguments
        )
    else:
        raise ValueError("unsupported action type")
    return run.to_dict()
