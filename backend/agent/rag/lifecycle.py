"""Explicit application ownership for the process-wide RAG service."""

from __future__ import annotations

from collections.abc import Callable

from .agent_api import configure_retrieval_service, reset_retrieval_service
from .retrieval.service import RetrievalService
from backend.core.log.logger import get_pipeline_logger


logger = get_pipeline_logger("RAG", __name__)


class RAGApplicationLifecycle:
    """Start and stop the single retrieval service owned by an ESA process."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        factory: Callable[[], RetrievalService] | None = None,
    ) -> None:
        from backend.core.utils import config

        self.enabled = config.RAG_ENABLED if enabled is None else enabled
        if factory is None:
            deployment_manifest = config.RAG_INDEX_DEPLOYMENT_MANIFEST_PATH

            def default_factory() -> RetrievalService:
                from .runtime import create_retrieval_service

                return create_retrieval_service(deployment_manifest)

            self._factory = default_factory
        else:
            self._factory = factory
        self.service: RetrievalService | None = None

    def start(self) -> RetrievalService | None:
        if not self.enabled:
            logger.info("application RAG disabled")
            return None
        if self.service is not None:
            return self.service
        logger.info("application RAG startup started")
        service = self._factory()
        warmup = getattr(service, "warmup", None)
        if callable(warmup):
            logger.info("application RAG model warmup started")
            warmup()
            logger.info("application RAG model warmup completed")
        configure_retrieval_service(service)
        self.service = service
        logger.info("application RAG startup completed")
        return self.service

    def close(self) -> None:
        if self.service is not None:
            logger.info("application RAG shutdown")
            reset_retrieval_service()
            self.service = None

    def __enter__(self) -> "RAGApplicationLifecycle":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
