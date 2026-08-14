"""Facade that starts and reads authoritative existing research jobs."""

from __future__ import annotations

from backend.core.workflows.research.models import WorkflowRun


class ResearchWorkflowFacade:
    def __init__(
        self,
        *,
        project_store,
        frontier_store,
        frontier_service,
        writing_store,
        writing_service,
        data_store,
        data_service,
    ) -> None:
        self.project_store = project_store
        self.frontier_store = frontier_store
        self.frontier_service = frontier_service
        self.writing_store = writing_store
        self.writing_service = writing_service
        self.data_store = data_store
        self.data_service = data_service

    def _project(self, project_id: str, user_id: str) -> dict:
        project = self.project_store.get_project(project_id, user_id)
        if project is None:
            raise KeyError(project_id)
        if project["status"] != "active":
            raise ValueError("research project is archived")
        return project

    @staticmethod
    def _view(kind: str, job: dict) -> WorkflowRun:
        return WorkflowRun(
            kind,
            job["job_id"],
            job["project_id"],
            job["user_id"],
            job["status"],
            job["created_at"],
            job,
        )

    def start_frontier_tracking(
        self,
        *,
        project_id: str,
        user_id: str,
        query: str,
        time_window_years: int = 5,
        max_results: int = 20,
    ) -> WorkflowRun:
        self._project(project_id, user_id)
        job = self.frontier_store.create_job(
            project_id=project_id,
            user_id=user_id,
            query=query.strip(),
            time_window_years=time_window_years,
            max_results=max_results,
        )
        self.frontier_service.submit(job["job_id"])
        return self._view("frontier_tracking", job)

    def start_research_writing(
        self,
        *,
        document_id: str,
        user_id: str,
        operation: str,
        instruction: str = "",
        source_text: str = "",
    ) -> WorkflowRun:
        document = self.writing_store.get_document(document_id, user_id)
        if document is None:
            raise KeyError(document_id)
        self._project(document["project_id"], user_id)
        job = self.writing_store.create_job(
            document_id=document_id,
            project_id=document["project_id"],
            user_id=user_id,
            operation=operation,
            instruction=instruction,
            source_text=source_text,
        )
        self.writing_service.submit(job["job_id"])
        return self._view("research_writing", job)

    def start_dataset_analysis(
        self,
        *,
        dataset_id: str,
        user_id: str,
        analysis_type: str,
        parameters: dict,
    ) -> WorkflowRun:
        dataset = self.data_store.get_dataset(dataset_id, user_id)
        if dataset is None:
            raise KeyError(dataset_id)
        self._project(dataset["project_id"], user_id)
        job = self.data_store.create_job(
            dataset_id=dataset_id,
            project_id=dataset["project_id"],
            user_id=user_id,
            analysis_type=analysis_type,
            parameters=parameters,
        )
        self.data_service.submit(job["job_id"])
        return self._view("dataset_analysis", job)

    def get(self, workflow_type: str, job_id: str, user_id: str) -> WorkflowRun | None:
        stores = {
            "frontier_tracking": self.frontier_store,
            "research_writing": self.writing_store,
            "dataset_analysis": self.data_store,
        }
        store = stores.get(workflow_type)
        if store is None:
            raise ValueError("unsupported workflow type")
        job = store.get_job(job_id, user_id)
        return self._view(workflow_type, job) if job else None
