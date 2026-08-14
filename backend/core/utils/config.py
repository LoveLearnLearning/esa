# backend/core/utils/config.py

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from backend.agent.rag.paths import workspace_root

if TYPE_CHECKING:
    # debug
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods

DEBUG_MODE: bool = os.environ.get("ESA_DEBUG", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

BACKEND_ROOT = Path(__file__).resolve().parents[2]

SEARXNG_BASE_URL = os.environ.get("SEARXNG_BASE_URL", "http://127.0.0.1:8888")

# model
MODEL_PATH: str = os.environ.get("ESA_MODEL_PATH", "Qwen/Qwen3.5-122B-A10B")
MODEL_DTYPE: ModelDType = "bfloat16"
MODEL_KV_CACHE_DTYPE: CacheDType = "auto"
MODEL_GPU_MEMORY_UTILIZATION: float = 0.95
MODEL_MAX_MODEL_LENGTH: int = 81920
MODEL_MAX_OUTPUT_TOKENS: int = 8192
MODEL_MAX_NUM_SEQS: int = 16
MODEL_QUANTIZATION: QuantizationMethods | None = None
MODEL_TENSOR_PARALLEL_SIZE: int = 4

# Auxiliary model: dedicated to document parsing and offline context compression.
# It is served by the local vLLM sidecar and is never exposed publicly.
AUXILIARY_MODEL_PATH: str = os.environ.get(
    "ESA_AUXILIARY_MODEL_PATH", "Qwen/Qwen3.5-9B"
)
AUXILIARY_MODEL_NAME: str = "esa-qwen3.5-9b"
AUXILIARY_MODEL_BASE_URL: str = "http://127.0.0.1:51025/v1"
AUXILIARY_MODEL_PORT: int = 51025
AUXILIARY_MODEL_DTYPE: str = "bfloat16"
AUXILIARY_MODEL_GPU_MEMORY_UTILIZATION: float = 0.80
AUXILIARY_MODEL_MAX_MODEL_LENGTH: int = 32768
AUXILIARY_MODEL_MAX_OUTPUT_TOKENS: int = 4096
AUXILIARY_MODEL_MAX_NUM_SEQS: int = 8
AUXILIARY_MODEL_MAX_IMAGES_PER_PROMPT: int = 4
AUXILIARY_MODEL_REQUEST_TIMEOUT: float = 180.0

# agent runtime
AGENT_LOOP_TIME: int = 10
AGENT_TOOL_TIMEOUT_SECONDS: float = 30.0

# Offline conversation context compression. Original messages are retained;
# the summary only replaces old messages in the next model prompt.
CONVERSATION_COMPRESSION_ENABLED: bool = True
CONVERSATION_OFFLINE_AFTER_SECONDS: int = 300
CONVERSATION_COMPRESSION_SCAN_INTERVAL: int = 30
CONVERSATION_COMPRESSION_MIN_MESSAGES: int = 12
CONVERSATION_COMPRESSION_MIN_NEW_MESSAGES: int = 6
CONVERSATION_COMPRESSION_KEEP_RECENT_MESSAGES: int = 8
CONVERSATION_COMPRESSION_MAX_INPUT_CHARS: int = 60000
CONVERSATION_COMPRESSION_MAX_OUTPUT_TOKENS: int = 2048

# ------------- rag ---------------

RAG_WORKSPACE_ROOT = workspace_root()

_T = TypeVar("_T")


def _path_from_env(name: str, default: Path) -> Path:
    """Return an absolute, expanded path while keeping deployment configurable."""

    return Path(os.environ.get(name, default)).expanduser().resolve()


def _str_from_env(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be blank")
    return value


def _optional_str_from_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or None


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _int_from_env(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float_from_env(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def _optional_float_from_env(
    name: str,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return _float_from_env(
        name,
        0.0,
        minimum=minimum,
        maximum=maximum,
    )


def _choice_from_env(
    name: str,
    default: _T,
    choices: tuple[_T, ...],
) -> _T:
    value = cast(_T, os.environ.get(name, default))
    if value not in choices:
        expected = ", ".join(map(str, choices))
        raise ValueError(f"{name} must be one of: {expected}")
    return value


def _csv_from_env(name: str, default: str) -> tuple[str, ...]:
    """Read a comma-separated environment setting without accepting blanks."""

    values = tuple(
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    )
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


# HTTP deployment.  The public browser-facing URL is supplied by Nginx; the
# application itself owns the /api prefix so the proxy must preserve the URI.
API_PREFIX: str = "/api"
SERVER_HOST: str = _str_from_env("HOST", "0.0.0.0")
SERVER_PORT: int = _int_from_env("PORT", 51024)
if SERVER_PORT > 65535:
    raise ValueError("PORT must be <= 65535")

CORS_ALLOWED_ORIGINS: tuple[str, ...] = _csv_from_env(
    "ESA_CORS_ALLOWED_ORIGINS",
    "https://esa.lovelearnlearning.cn",
)
if "*" in CORS_ALLOWED_ORIGINS:
    raise ValueError("ESA_CORS_ALLOWED_ORIGINS must list explicit origins")
TRUSTED_HOSTS: tuple[str, ...] = _csv_from_env(
    "ESA_TRUSTED_HOSTS",
    "esa.lovelearnlearning.cn,localhost,127.0.0.1",
)
if "*" in TRUSTED_HOSTS:
    raise ValueError("ESA_TRUSTED_HOSTS must list explicit hosts")
# Never trust arbitrary clients to supply X-Forwarded-* headers.  Production
# must set this to the actual reverse-proxy source IP; loopback remains the
# safe local default.
FORWARDED_ALLOW_IPS: tuple[str, ...] = _csv_from_env(
    "ESA_FORWARDED_ALLOW_IPS",
    "127.0.0.1",
)
if "*" in FORWARDED_ALLOW_IPS:
    raise ValueError("ESA_FORWARDED_ALLOW_IPS must list trusted proxy addresses")
ENABLE_LEGACY_API_ROUTES: bool = _bool_from_env(
    "ESA_ENABLE_LEGACY_API_ROUTES",
    True,
)

# Workspace runtime rollout. Authorization is always computed by Core Router;
# these switches only select the execution adapter during a staged deployment.
WORKSPACE_ROUTER_SHADOW_ENABLED: bool = _bool_from_env("ESA_WORKSPACE_ROUTER_SHADOW_ENABLED", True)
WORKSPACE_RUNTIME_ENABLED: bool = _bool_from_env("ESA_WORKSPACE_RUNTIME_ENABLED", True)
WORKSPACE_RUNTIME_LEARNING_ENABLED: bool = _bool_from_env("ESA_WORKSPACE_RUNTIME_LEARNING_ENABLED", True)
WORKSPACE_RUNTIME_TEACHING_ENABLED: bool = _bool_from_env("ESA_WORKSPACE_RUNTIME_TEACHING_ENABLED", True)
WORKSPACE_RUNTIME_RESEARCH_ENABLED: bool = _bool_from_env("ESA_WORKSPACE_RUNTIME_RESEARCH_ENABLED", True)
CORE_MEMORY_V2_ENABLED: bool = _bool_from_env("ESA_CORE_MEMORY_V2_ENABLED", True)
RESEARCH_WORKFLOW_TOOLS_ENABLED: bool = _bool_from_env("ESA_RESEARCH_WORKFLOW_TOOLS_ENABLED", True)

# User uploads are persisted before any model or DocIR work begins. The public
# proxy limit must be at least this large.
USER_ATTACHMENT_ROOT: Path = _path_from_env(
    "ESA_USER_ATTACHMENT_ROOT",
    BACKEND_ROOT / "data" / "user",
)
USER_ATTACHMENT_MAX_BYTES: int = _int_from_env(
    "ESA_USER_ATTACHMENT_MAX_BYTES",
    200 * 1024 * 1024,
)

# Email verification on the supercomputer. Fill these constants in the private
# deployment copy of this file; the standalone mail server has its own config.
EMAIL_PROVIDER: Literal["disabled", "service"] = "service"
EMAIL_SERVICE_URL: str = "https://mail-api.lovelearnlearning.cn"
EMAIL_SERVICE_TOKEN: str = (
    "e9493dca7a911f60226ec698e90678add37d8d28eb3f02271706026d7ba491d5"
)
EMAIL_VERIFICATION_SECRET: str = (
    "22d6394ed15a7dec1b3bac78e3f5cf2739386483aeca3c88d4cafad40e4d0da2"
)
EMAIL_CODE_TTL_SECONDS: int = 600
EMAIL_CODE_COOLDOWN_SECONDS: int = 60
EMAIL_CODE_MAX_ATTEMPTS: int = 5
EMAIL_CODE_EMAIL_HOURLY_LIMIT: int = 5
EMAIL_CODE_IP_HOURLY_LIMIT: int = 20


# collection and deployment
RAG_ENABLED: bool = _bool_from_env("RAG_ENABLED", False)
RAG_COLLECTION_ID = "collection_e55166f798ef1c361c72de9a"
RAG_DEPLOYMENT_ID = "deployment_357bd9c84d8404fae42c2740"
RAG_COLLECTION_MANIFEST_PATH: Path = _path_from_env(
    "RAG_COLLECTION_MANIFEST_PATH",
    RAG_WORKSPACE_ROOT
    / f"artifacts/chunk/collections/{RAG_COLLECTION_ID}/manifest.json",
)
RAG_INDEX_DEPLOYMENT_ROOT: Path = _path_from_env(
    "RAG_INDEX_DEPLOYMENT_ROOT", RAG_WORKSPACE_ROOT / "artifacts/rag/indexes"
)

# qdrant
RAG_QDRANT_BASE_URL: str = _str_from_env("RAG_QDRANT_BASE_URL", "http://127.0.0.1:6333")
RAG_QDRANT_COLLECTION: str = _str_from_env(
    "RAG_QDRANT_COLLECTION", "rag_qwen3_embedding_4b_v2"
)
RAG_QDRANT_TIMEOUT: float = _float_from_env("RAG_QDRANT_TIMEOUT", 30.0, minimum=0.001)
RAG_QDRANT_UPSERT_BATCH_SIZE: int = _int_from_env("RAG_QDRANT_UPSERT_BATCH_SIZE", 64)

# embedding
EmbeddingBackend = Literal["reference", "transformers", "vllm"]
RAG_EMBEDDING_BACKEND: EmbeddingBackend = _choice_from_env(
    "RAG_EMBEDDING_BACKEND",
    "transformers",
    ("reference", "transformers", "vllm"),
)
RAG_EMBEDDING_MODEL_PATH: str = _str_from_env(
    "RAG_EMBEDDING_MODEL_PATH", "Qwen/Qwen3-Embedding-4B"
)
RAG_EMBEDDING_BASE_URL: str | None = _optional_str_from_env("RAG_EMBEDDING_BASE_URL")
RAG_EMBEDDING_DEVICE: str = _str_from_env("RAG_EMBEDDING_DEVICE", "cuda")
RAG_EMBEDDING_RUNTIME_DEVICE: str | None = _optional_str_from_env(
    "RAG_EMBEDDING_RUNTIME_DEVICE"
)
RAG_EMBEDDING_DIMENSION: int = _int_from_env("RAG_EMBEDDING_DIMENSION", 2560)
RAG_EMBEDDING_MAX_LENGTH: int = _int_from_env("RAG_EMBEDDING_MAX_LENGTH", 8192)
RAG_EMBEDDING_BATCH_SIZE: int = _int_from_env("RAG_EMBEDDING_BATCH_SIZE", 8)
RAG_EMBEDDING_TIMEOUT: float = _float_from_env(
    "RAG_EMBEDDING_TIMEOUT", 120.0, minimum=0.001
)

# reranker
RerankerBackend = Literal["none", "transformers", "vllm"]
RAG_RERANKER_ENABLED: bool = _bool_from_env("RAG_RERANKER_ENABLED", False)
RAG_RERANKER_BACKEND: RerankerBackend = _choice_from_env(
    "RAG_RERANKER_BACKEND",
    "transformers" if RAG_RERANKER_ENABLED else "none",
    ("none", "transformers", "vllm"),
)
RAG_RERANKER_MODEL_PATH: str = _str_from_env(
    "RAG_RERANKER_MODEL_PATH", "Qwen/Qwen3-Reranker-4B"
)
RAG_RERANKER_BASE_URL: str | None = _optional_str_from_env("RAG_RERANKER_BASE_URL")
RAG_RERANKER_DEVICE: str = _str_from_env("RAG_RERANKER_DEVICE", "cuda")
RAG_RERANKER_MAX_LENGTH: int = _int_from_env("RAG_RERANKER_MAX_LENGTH", 8192)
RAG_RERANKER_TIMEOUT: float = _float_from_env(
    "RAG_RERANKER_TIMEOUT", 120.0, minimum=0.001
)

# retrieval
RAG_DENSE_LIMIT: int = _int_from_env("RAG_DENSE_LIMIT", 20)
RAG_BM25_BODY_LIMIT: int = _int_from_env("RAG_BM25_BODY_LIMIT", 20)
RAG_BM25_HEADING_LIMIT: int = _int_from_env("RAG_BM25_HEADING_LIMIT", 20)
RAG_RRF_LIMIT: int = _int_from_env("RAG_RRF_LIMIT", 30)
RAG_RERANK_LIMIT: int = _int_from_env("RAG_RERANK_LIMIT", 20)
RAG_RERANKER_BATCH_SIZE: int = _int_from_env("RAG_RERANKER_BATCH_SIZE", 4)
RAG_FINAL_LIMIT: int = _int_from_env("RAG_FINAL_LIMIT", 5)
RAG_RRF_K: int = _int_from_env("RAG_RRF_K", 60)
RAG_SECTION_WINDOW: int = _int_from_env("RAG_SECTION_WINDOW", 1, minimum=0)
RAG_MAX_CONTEXT_TOKENS: int = _int_from_env("RAG_MAX_CONTEXT_TOKENS", 8192)
RAG_RERANK_THRESHOLD: float | None = _optional_float_from_env(
    "RAG_RERANK_THRESHOLD", minimum=0.0, maximum=1.0
)
RAG_FUSION_METHOD: Literal["dense", "equal_rrf", "weighted_rrf", "score"] = (
    _choice_from_env(
        "RAG_FUSION_METHOD",
        "dense",
        ("dense", "equal_rrf", "weighted_rrf", "score"),
    )
)
# 正式部署冻结为 dense-only；实验配置仍可通过环境变量显式覆盖。
RAG_DENSE_WEIGHT: float = _float_from_env(
    "RAG_DENSE_WEIGHT", 1.0, minimum=0.0, maximum=1.0
)
RAG_LEXICAL_BODY_WEIGHT: float = _float_from_env(
    "RAG_LEXICAL_BODY_WEIGHT", 0.75, minimum=0.0, maximum=1.0
)
RAG_LEXICAL_GATE_ENABLED: bool = _bool_from_env("RAG_LEXICAL_GATE_ENABLED", True)
# prior_weight 是融合排序先验的权重；其余权重交给 Reranker 分数。
RAG_RERANKER_PRIOR_WEIGHT: float = _float_from_env(
    "RAG_RERANKER_PRIOR_WEIGHT", 0.90, minimum=0.0, maximum=1.0
)

if RAG_RERANKER_ENABLED and RAG_RERANKER_BACKEND == "none":
    raise ValueError(
        "RAG_RERANKER_BACKEND cannot be 'none' when RAG_RERANKER_ENABLED=true"
    )
if RAG_EMBEDDING_BACKEND == "vllm" and not RAG_EMBEDDING_BASE_URL:
    raise ValueError("RAG_EMBEDDING_BASE_URL is required for the vllm backend")
if RAG_RERANKER_BACKEND == "vllm" and not RAG_RERANKER_BASE_URL:
    raise ValueError("RAG_RERANKER_BASE_URL is required for the vllm backend")
if RAG_FINAL_LIMIT > RAG_RERANK_LIMIT:
    raise ValueError("RAG_FINAL_LIMIT cannot exceed RAG_RERANK_LIMIT")
if RAG_RERANK_LIMIT > RAG_RRF_LIMIT:
    raise ValueError("RAG_RERANK_LIMIT cannot exceed RAG_RRF_LIMIT")

RAG_INDEX_DEPLOYMENT_MANIFEST_PATH: Path = _path_from_env(
    "RAG_INDEX_DEPLOYMENT_MANIFEST_PATH",
    RAG_INDEX_DEPLOYMENT_ROOT / RAG_DEPLOYMENT_ID / "manifest.json",
)


def validate_startup_config() -> None:
    """Fail early for enabled optional subsystems and local model paths."""

    for name, value in (
        ("ESA_MODEL_PATH", MODEL_PATH),
        ("ESA_AUXILIARY_MODEL_PATH", AUXILIARY_MODEL_PATH),
    ):
        candidate = Path(value).expanduser()
        if candidate.is_absolute() and not candidate.exists():
            raise RuntimeError(f"{name} points to a missing local path: {candidate}")
    if EMAIL_PROVIDER == "service":
        if not EMAIL_SERVICE_URL or not EMAIL_SERVICE_URL.startswith("https://"):
            raise RuntimeError("EMAIL_SERVICE_URL must be an https URL")
        if not EMAIL_SERVICE_TOKEN or len(EMAIL_SERVICE_TOKEN) < 32:
            raise RuntimeError(
                "EMAIL_SERVICE_TOKEN in config.py must contain at least 32 characters"
            )
        if not EMAIL_VERIFICATION_SECRET or len(EMAIL_VERIFICATION_SECRET) < 32:
            raise RuntimeError(
                "EMAIL_VERIFICATION_SECRET in config.py must contain at least 32 characters"
            )
        numeric_email_settings = {
            "EMAIL_CODE_TTL_SECONDS": EMAIL_CODE_TTL_SECONDS,
            "EMAIL_CODE_COOLDOWN_SECONDS": EMAIL_CODE_COOLDOWN_SECONDS,
            "EMAIL_CODE_MAX_ATTEMPTS": EMAIL_CODE_MAX_ATTEMPTS,
            "EMAIL_CODE_EMAIL_HOURLY_LIMIT": EMAIL_CODE_EMAIL_HOURLY_LIMIT,
            "EMAIL_CODE_IP_HOURLY_LIMIT": EMAIL_CODE_IP_HOURLY_LIMIT,
        }
        invalid = [name for name, value in numeric_email_settings.items() if value <= 0]
        if invalid:
            raise RuntimeError(f"{', '.join(invalid)} must be greater than zero")
    if not RAG_ENABLED:
        return
    missing = [
        path
        for path in (
            RAG_COLLECTION_MANIFEST_PATH,
            RAG_INDEX_DEPLOYMENT_MANIFEST_PATH,
        )
        if not path.is_file()
    ]
    if missing:
        values = ", ".join(str(path) for path in missing)
        raise RuntimeError(f"RAG_ENABLED=true but manifest files are missing: {values}")
