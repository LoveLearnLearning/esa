import logging
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator


_log_context: ContextVar[dict[str, str]] = ContextVar(
    "esa_pipeline_log_context",
    default={},
)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _log_context.get()
        record.owner = getattr(record, "owner", "APP")
        record.user_id = context.get("user_id", "-")
        record.conversation_id = context.get("conversation_id", "-")
        record.attachment_id = context.get("attachment_id", "-")
        return True


def get_pipeline_logger(owner: str, name: str) -> logging.LoggerAdapter:
    """Return a logger whose records identify the owning pipeline."""

    return logging.LoggerAdapter(logging.getLogger(name), {"owner": owner.upper()})


@contextmanager
def pipeline_log_context(**values: str | None) -> Iterator[None]:
    """Attach request ownership identifiers to nested DocIR/MM/RAG logs."""

    current = dict(_log_context.get())
    current.update(
        {key: str(value) for key, value in values.items() if value is not None}
    )
    token = _log_context.set(current)
    try:
        yield
    finally:
        _log_context.reset(token)


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    context_filter = _ContextFilter()
    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | %(levelname)-8s | owner=%(owner)s | %(name)s | "
            "user=%(user_id)s conversation=%(conversation_id)s "
            "attachment=%(attachment_id)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Uvicorn may install its own console handler before importing the app. In
    # that case, leave console ownership to Uvicorn while still creating the
    # ESA file handler below.
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.addFilter(context_filter)
        console_handler.setFormatter(formatter)
        setattr(console_handler, "_esa_handler", "console")
        root_logger.addHandler(console_handler)

    if not any(
        getattr(handler, "_esa_handler", None) == "file"
        for handler in root_logger.handlers
    ):
        file_handler = RotatingFileHandler(
            filename=log_dir / "backend.log",
            maxBytes=20 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.addFilter(context_filter)
        file_handler.setFormatter(formatter)
        setattr(file_handler, "_esa_handler", "file")
        root_logger.addHandler(file_handler)
