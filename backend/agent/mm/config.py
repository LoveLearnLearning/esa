"""多模态附件摄取的集中配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.agent.rag.paths import workspace_root
from backend.core.utils import config as app_config


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class MMConfig:
    artifact_root: Path
    direct_context_token_limit: int
    tokenizer_path: str
    mineru_command: Path
    mineru_timeout_seconds: int
    mineru_attempts: int
    vlm_base_url: str
    vlm_model: str
    vlm_model_revision: str | None
    vlm_timeout_seconds: float
    vlm_attempts: int
    vlm_max_concurrency: int
    embedding_model: str
    embedding_device: str

    @classmethod
    def from_env(cls) -> "MMConfig":
        root = workspace_root()
        revision = os.environ.get("MM_VLM_MODEL_REVISION")
        return cls(
            artifact_root=Path(
                os.environ.get("MM_ARTIFACT_ROOT", root / "runtime/mm")
            ).expanduser().resolve(),
            direct_context_token_limit=_positive_int(
                "MM_DIRECT_CONTEXT_TOKEN_LIMIT", 48_000
            ),
            tokenizer_path=os.environ.get(
                "MM_TOKENIZER_PATH", str(app_config.MODEL_PATH)
            ),
            mineru_command=Path(
                os.environ.get("MM_MINERU_COMMAND", root / "bin/run-mineru")
            ).expanduser().resolve(),
            mineru_timeout_seconds=_positive_int(
                "MM_MINERU_TIMEOUT_SECONDS", 7200
            ),
            mineru_attempts=_positive_int("MM_MINERU_ATTEMPTS", 2),
            vlm_base_url=os.environ.get(
                "MM_VLM_BASE_URL", "http://127.0.0.1:8000/v1"
            ).rstrip("/"),
            vlm_model=os.environ.get("MM_VLM_MODEL", "Qwen3-VL"),
            vlm_model_revision=revision.strip() if revision and revision.strip() else None,
            vlm_timeout_seconds=_positive_float("MM_VLM_TIMEOUT_SECONDS", 120.0),
            vlm_attempts=_positive_int("MM_VLM_ATTEMPTS", 2),
            vlm_max_concurrency=_positive_int("MM_VLM_MAX_CONCURRENCY", 4),
            embedding_model=os.environ.get(
                "MM_EMBEDDING_MODEL", app_config.RAG_EMBEDDING_MODEL_PATH
            ),
            embedding_device=os.environ.get(
                "MM_EMBEDDING_DEVICE", app_config.RAG_EMBEDDING_DEVICE
            ),
        )

