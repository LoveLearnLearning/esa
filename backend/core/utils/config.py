# backend/core/utils/config.py

"""集中管理运行配置。"""

from __future__ import annotations

import importlib
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from backend.agent.rag.paths import workspace_root

try:
    _private_config = importlib.import_module("backend.core.utils.config_private")
except ModuleNotFoundError as exc:
    if exc.name != "backend.core.utils.config_private":
        raise
    _private_config = None

if TYPE_CHECKING:
    # debug
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods


def _bool_from_env(name: str, default: bool) -> bool:
    """Read a strict boolean environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


DEBUG_MODE: bool = _bool_from_env("ESA_DEBUG", False)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

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
MODEL_ENFORCE_EAGER: bool = _bool_from_env("ESA_MODEL_ENFORCE_EAGER", False)
MODEL_PERFORMANCE_MODE: Literal["balanced", "interactivity", "throughput"] = cast(
    Literal["balanced", "interactivity", "throughput"],
    os.environ.get("ESA_MODEL_PERFORMANCE_MODE", "interactivity").strip().lower(),
)
if MODEL_PERFORMANCE_MODE not in {"balanced", "interactivity", "throughput"}:
    raise ValueError(
        "ESA_MODEL_PERFORMANCE_MODE must be balanced, interactivity, or throughput"
    )
MODEL_LORA_PATH: str | None = (
    os.environ.get("ESA_MODEL_LORA_PATH", "").strip() or None
)
MODEL_LORA_NAME: str = os.environ.get("ESA_MODEL_LORA_NAME", "esa-agent").strip()
if not MODEL_LORA_NAME:
    raise ValueError("ESA_MODEL_LORA_NAME cannot be blank")
try:
    MODEL_LORA_MAX_RANK: int = int(
        os.environ.get("ESA_MODEL_LORA_MAX_RANK", "16")
    )
except ValueError as exc:
    raise ValueError("ESA_MODEL_LORA_MAX_RANK must be an integer") from exc
if MODEL_LORA_MAX_RANK <= 0:
    raise ValueError("ESA_MODEL_LORA_MAX_RANK must be greater than zero")
MODEL_LORA_FULLY_SHARDED: bool = _bool_from_env(
    "ESA_MODEL_LORA_FULLY_SHARDED", False
)
MODEL_LORA_SPECIALIZE_ACTIVE: bool = _bool_from_env(
    "ESA_MODEL_LORA_SPECIALIZE_ACTIVE", True
)

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
AGENT_STREAM_HEARTBEAT_SECONDS: float = 15.0

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

# Generate one concise history title from the first user question. This shares
# the local auxiliary model sidecar and never delays the start of the main run.
CONVERSATION_TITLE_ENABLED: bool = True
CONVERSATION_TITLE_MAX_INPUT_CHARS: int = 4000
CONVERSATION_TITLE_MAX_OUTPUT_TOKENS: int = 48
CONVERSATION_TITLE_REQUEST_TIMEOUT: float = 15.0
CONVERSATION_TITLE_MAX_CHARS: int = 24

# ------------- rag ---------------

RAG_WORKSPACE_ROOT = workspace_root()

_T = TypeVar("_T")


def _path_from_env(name: str, default: Path) -> Path:
    """Return an absolute, expanded path while keeping deployment configurable."""

    return Path(os.environ.get(name, default)).expanduser().resolve()


def _str_from_env(name: str, default: str) -> str:
    """处理 `_str_from_env` 相关逻辑。"""
    value = os.environ.get(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be blank")
    return value


def _optional_str_from_env(name: str, default: str | None = None) -> str | None:
    """处理 `_optional_str_from_env` 相关逻辑。"""
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or None


def _int_from_env(name: str, default: int, *, minimum: int = 1) -> int:
    """处理 `_int_from_env` 相关逻辑。"""
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
    """处理 `_float_from_env` 相关逻辑。"""
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
    """处理 `_optional_float_from_env` 相关逻辑。"""
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
    """处理 `_choice_from_env` 相关逻辑。"""
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


# Agent command sandbox. It is opt-in until Bubblewrap is installed and the
# persistent root has been reviewed for the deployment host.
SANDBOX_ENABLED: bool = _bool_from_env("ESA_SANDBOX_ENABLED", False)
SANDBOX_ROOT: Path = _path_from_env(
    "ESA_SANDBOX_ROOT", RAG_WORKSPACE_ROOT / "data" / "sandbox"
)
SANDBOX_RUNTIME: str = _str_from_env("ESA_SANDBOX_RUNTIME", "bwrap")
SANDBOX_MAX_TIMEOUT_SECONDS: float = _float_from_env(
    "ESA_SANDBOX_MAX_TIMEOUT_SECONDS", 30.0, minimum=0.1, maximum=300.0
)
SANDBOX_MAX_OUTPUT_CHARS: int = _int_from_env(
    "ESA_SANDBOX_MAX_OUTPUT_CHARS", 50_000, minimum=1024
)
SANDBOX_MAX_COMMAND_CHARS: int = _int_from_env(
    "ESA_SANDBOX_MAX_COMMAND_CHARS", 12_000, minimum=128
)
SANDBOX_CPU_SECONDS: int = _int_from_env("ESA_SANDBOX_CPU_SECONDS", 20)
SANDBOX_MEMORY_BYTES: int = _int_from_env(
    "ESA_SANDBOX_MEMORY_BYTES", 1_024 * 1_024 * 1_024
)
SANDBOX_FILE_SIZE_BYTES: int = _int_from_env(
    "ESA_SANDBOX_FILE_SIZE_BYTES", 128 * 1_024 * 1_024
)
SANDBOX_PROCESS_COUNT: int = _int_from_env("ESA_SANDBOX_PROCESS_COUNT", 64)
SANDBOX_PACKAGE_INSTALL_ENABLED: bool = _bool_from_env(
    "ESA_SANDBOX_PACKAGE_INSTALL_ENABLED", False
)
SANDBOX_PYTHON_PACKAGE_ALLOWLIST: tuple[str, ...] = _csv_from_env(
    "ESA_SANDBOX_PYTHON_PACKAGE_ALLOWLIST",
    "numpy,pandas,matplotlib,scipy,sympy,requests,pillow,"
    "opencv-python-headless,scikit-learn,seaborn",
)


# MCP child processes. The ESA backend is the MCP client and owns the complete
# subprocess lifetime. Only the audited You.com search tool is exposed.
MCP_ENABLED: bool = True
MCP_YOU_SERVER_NAME: str = "you"
MCP_YOU_COMMAND: str = "npx"
MCP_YOU_ARGS: tuple[str, ...] = (
    "--yes",
    "@youdotcom-oss/mcp@3.5.0",
)
MCP_YOU_ALLOWED_TOOLS: frozenset[str] = frozenset({"you-search"})
MCP_YOU_API_KEY: str | None = _optional_str_from_env("YDC_API_KEY")
MCP_STARTUP_TIMEOUT_SECONDS: float = 45.0
MCP_CALL_TIMEOUT_SECONDS: float = 20.0
MCP_MAX_RESULT_CHARS: int = 120_000


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
WORKSPACE_ROUTER_SHADOW_ENABLED: bool = _bool_from_env(
    "ESA_WORKSPACE_ROUTER_SHADOW_ENABLED", True
)
WORKSPACE_RUNTIME_ENABLED: bool = _bool_from_env("ESA_WORKSPACE_RUNTIME_ENABLED", True)
WORKSPACE_RUNTIME_LEARNING_ENABLED: bool = _bool_from_env(
    "ESA_WORKSPACE_RUNTIME_LEARNING_ENABLED", True
)
WORKSPACE_RUNTIME_TEACHING_ENABLED: bool = _bool_from_env(
    "ESA_WORKSPACE_RUNTIME_TEACHING_ENABLED", True
)
WORKSPACE_RUNTIME_RESEARCH_ENABLED: bool = _bool_from_env(
    "ESA_WORKSPACE_RUNTIME_RESEARCH_ENABLED", True
)
CORE_MEMORY_V2_ENABLED: bool = _bool_from_env("ESA_CORE_MEMORY_V2_ENABLED", True)
RESEARCH_WORKFLOW_TOOLS_ENABLED: bool = _bool_from_env(
    "ESA_RESEARCH_WORKFLOW_TOOLS_ENABLED", True
)

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

# Personal knowledge bases are an independently deployable RAG subsystem.  Its
# durable root must live across Slurm jobs; only transient work belongs under
# SLURM_TMPDIR.
PERSONAL_KB_ENABLED: bool = _bool_from_env("PERSONAL_KB_ENABLED", False)
PERSONAL_KB_ROOT: Path = _path_from_env(
    "PERSONAL_KB_ROOT",
    Path("/persist_data/home/chenxuzhao/esa-personal-knowledge-base"),
)
_personal_kb_temp_override = _optional_str_from_env("PERSONAL_KB_TEMP_ROOT")
PERSONAL_KB_TEMP_ROOT: Path = Path(
    _personal_kb_temp_override
    or (Path(os.environ.get("SLURM_TMPDIR", "/tmp")) / "esa-personal-kb")
).expanduser().resolve()
PERSONAL_KB_SNAPSHOT_ROOT: Path = _path_from_env(
    "PERSONAL_KB_SNAPSHOT_ROOT",
    PERSONAL_KB_ROOT / "qdrant-snapshots",
)
PERSONAL_KB_MAX_FILE_BYTES: int = _int_from_env(
    "PERSONAL_KB_MAX_FILE_BYTES", 200 * 1024 * 1024
)
PERSONAL_KB_MAX_BATCH_FILES: int = _int_from_env(
    "PERSONAL_KB_MAX_BATCH_FILES", 20
)
PERSONAL_KB_MAX_BATCH_BYTES: int = _int_from_env(
    "PERSONAL_KB_MAX_BATCH_BYTES", 1024 * 1024 * 1024
)
PERSONAL_KB_MAX_REQUEST_BYTES: int = _int_from_env(
    "PERSONAL_KB_MAX_REQUEST_BYTES",
    PERSONAL_KB_MAX_BATCH_BYTES + 16 * 1024 * 1024,
)
PERSONAL_KB_MAX_USER_BYTES: int = _int_from_env(
    "PERSONAL_KB_MAX_USER_BYTES", 10 * 1024 * 1024 * 1024
)
PERSONAL_KB_MAX_USER_FILES: int = _int_from_env(
    "PERSONAL_KB_MAX_USER_FILES", 1000
)
PERSONAL_KB_QDRANT_COLLECTION: str = _str_from_env(
    "PERSONAL_KB_QDRANT_COLLECTION", "esa_personal_kb_qwen3_4b"
)
PERSONAL_KB_SNAPSHOT_MAX_DELAY_SECONDS: int = _int_from_env(
    "PERSONAL_KB_SNAPSHOT_MAX_DELAY_SECONDS", 600
)
PERSONAL_KB_SNAPSHOT_RETENTION: int = _int_from_env(
    "PERSONAL_KB_SNAPSHOT_RETENTION", 3
)
PERSONAL_KB_RESTORE_ON_STARTUP: bool = _bool_from_env(
    "PERSONAL_KB_RESTORE_ON_STARTUP", True
)
PERSONAL_KB_MINERU_API_URL: str = _str_from_env(
    "PERSONAL_KB_MINERU_API_URL", "http://127.0.0.1:51026"
)
PERSONAL_KB_MINERU_COMMAND: Path = _path_from_env(
    "PERSONAL_KB_MINERU_COMMAND", RAG_WORKSPACE_ROOT / "bin/run-mineru"
)
PERSONAL_KB_MINERU_TIMEOUT_SECONDS: int = _int_from_env(
    "PERSONAL_KB_MINERU_TIMEOUT_SECONDS", 7200
)
PERSONAL_KB_MINERU_ATTEMPTS: int = _int_from_env(
    "PERSONAL_KB_MINERU_ATTEMPTS", 2
)
_personal_kb_libreoffice_value = os.environ.get(
    "PERSONAL_KB_LIBREOFFICE_BIN", ""
).strip()
PERSONAL_KB_LIBREOFFICE_BIN: Path | None = (
    Path(_personal_kb_libreoffice_value).expanduser().resolve()
    if _personal_kb_libreoffice_value
    else None
)
PERSONAL_KB_OFFICE_PREVIEW_TIMEOUT_SECONDS: int = _int_from_env(
    "PERSONAL_KB_OFFICE_PREVIEW_TIMEOUT_SECONDS", 120
)
PERSONAL_KB_OFFICE_PREVIEW_MAX_BYTES: int = _int_from_env(
    "PERSONAL_KB_OFFICE_PREVIEW_MAX_BYTES", 64 * 1024 * 1024
)
PERSONAL_KB_VISION_ENABLED: bool = _bool_from_env(
    "PERSONAL_KB_VISION_ENABLED", False
)
PERSONAL_KB_WORKERS: int = _int_from_env("PERSONAL_KB_WORKERS", 2)
PERSONAL_KB_EMBEDDING_CONCURRENCY: int = _int_from_env(
    "PERSONAL_KB_EMBEDDING_CONCURRENCY", 1
)
PERSONAL_KB_JOB_TIMEOUT_SECONDS: int = _int_from_env(
    "PERSONAL_KB_JOB_TIMEOUT_SECONDS", 3600
)
PERSONAL_KB_MAX_RETRIES: int = _int_from_env(
    "PERSONAL_KB_MAX_RETRIES", 3, minimum=0
)
PERSONAL_KB_MAX_EXPANDED_BYTES: int = _int_from_env(
    "PERSONAL_KB_MAX_EXPANDED_BYTES", 1024 * 1024 * 1024
)
PERSONAL_KB_MAX_PAGES: int = _int_from_env("PERSONAL_KB_MAX_PAGES", 5000)
PERSONAL_KB_MAX_IMAGES: int = _int_from_env("PERSONAL_KB_MAX_IMAGES", 10000)
PERSONAL_KB_MAX_IMAGE_PIXELS: int = _int_from_env(
    "PERSONAL_KB_MAX_IMAGE_PIXELS", 100_000_000
)
PERSONAL_KB_MIN_FREE_BYTES: int = _int_from_env(
    "PERSONAL_KB_MIN_FREE_BYTES", 1024 * 1024 * 1024, minimum=0
)
PERSONAL_KB_ORPHAN_RETENTION_SECONDS: int = _int_from_env(
    "PERSONAL_KB_ORPHAN_RETENTION_SECONDS", 86400, minimum=0
)
PERSONAL_KB_AUDIT_RETENTION_DAYS: int = _int_from_env(
    "PERSONAL_KB_AUDIT_RETENTION_DAYS", 90, minimum=1
)

# Email verification on the supercomputer. Secrets live in the ignored
# config_private.py module, so deployments do not need a .env file and Git
# never becomes the credential store. ESA_* environment values remain useful
# for container deployments and take precedence when present.
EMAIL_PROVIDER: Literal["disabled", "service"] = cast(
    Literal["disabled", "service"],
    os.environ.get(
        "ESA_EMAIL_PROVIDER",
        getattr(_private_config, "EMAIL_PROVIDER", "service"),
    ).strip(),
)
EMAIL_SERVICE_URL: str = os.environ.get(
    "ESA_EMAIL_SERVICE_URL",
    getattr(
        _private_config,
        "EMAIL_SERVICE_URL",
        "https://mail-api.lovelearnlearning.cn",
    ),
).strip()
EMAIL_SERVICE_TOKEN: str = os.environ.get(
    "ESA_EMAIL_SERVICE_TOKEN",
    getattr(
        _private_config,
        "EMAIL_SERVICE_TOKEN",
        "e9493dca7a911f60226ec698e90678add37d8d28eb3f02271706026d7ba491d5",
    ),
).strip()
EMAIL_VERIFICATION_SECRET: str = os.environ.get(
    "ESA_EMAIL_VERIFICATION_SECRET",
    getattr(
        _private_config,
        "EMAIL_VERIFICATION_SECRET",
        "22d6394ed15a7dec1b3bac78e3f5cf2739386483aeca3c88d4cafad40e4d0da2",
    ),
).strip()
EMAIL_CODE_TTL_SECONDS: int = 600
EMAIL_CODE_COOLDOWN_SECONDS: int = 60
EMAIL_CODE_MAX_ATTEMPTS: int = 5
EMAIL_CODE_EMAIL_HOURLY_LIMIT: int = 5
EMAIL_CODE_IP_HOURLY_LIMIT: int = 20

# Language Server Protocol. The backend proxies authenticated WebSocket
# sessions to local stdio language servers. Missing executables only disable
# that language; Monaco keeps its local completion fallback.
LSP_ENABLED: bool = True
LSP_MAX_SESSIONS: int = 24
LSP_MAX_SESSIONS_PER_USER: int = 2
LSP_AUTH_TIMEOUT_SECONDS: float = 8.0
LSP_MAX_MESSAGE_BYTES: int = 2 * 1024 * 1024
LSP_ALLOWED_ORIGINS: tuple[str, ...] = (
    "https://www.lovelearnlearning.cn",
    "https://esa.lovelearnlearning.cn",
)
LSP_SERVER_COMMANDS: dict[str, tuple[str, ...]] = {
    "c": ("clangd",),
    "cpp": ("clangd",),
    "python": ("pyright-langserver", "--stdio"),
    "javascript": ("typescript-language-server", "--stdio"),
    "typescript": ("typescript-language-server", "--stdio"),
    "dart": ("dart", "language-server", "--protocol=lsp"),
    "java": ("jdtls",),
    "go": ("gopls",),
    "rust": ("rust-analyzer",),
}
LSP_DOCUMENT_FILENAMES: dict[str, str] = {
    "c": "main.c",
    "cpp": "main.cpp",
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "dart": "main.dart",
    "java": "Main.java",
    "go": "main.go",
    "rust": "main.rs",
}


# collection and deployment
RAG_ENABLED: bool = _bool_from_env("RAG_ENABLED", False)
RAG_COLLECTION_ID = "collection_f645d539e0ae078ba11d7e88"
RAG_DEPLOYMENT_ID = "deployment_57fdb5e345322c2181e16ee1"
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
    "RAG_QDRANT_COLLECTION", "cs_textbooks_qwen3_20260822"
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
RAG_RERANKER_ENABLED: bool = _bool_from_env("RAG_RERANKER_ENABLED", True)
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
# Keep a wider recall pool so relevant chunks beyond the old top-20 are
# available to fusion/reranking without increasing the final response size.
RAG_DENSE_LIMIT: int = _int_from_env("RAG_DENSE_LIMIT", 50)
RAG_BM25_BODY_LIMIT: int = _int_from_env("RAG_BM25_BODY_LIMIT", 50)
RAG_BM25_HEADING_LIMIT: int = _int_from_env("RAG_BM25_HEADING_LIMIT", 50)
RAG_RRF_LIMIT: int = _int_from_env("RAG_RRF_LIMIT", 50)
RAG_RERANK_LIMIT: int = _int_from_env("RAG_RERANK_LIMIT", 50)
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
# 保留旧环境项以兼容部署配置；串行 Reranker 不再使用该权重。
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


def validate_private_storage_capacity(
    name: str, path: Path, required_bytes: int
) -> None:
    """Validate one private persistent or multipart-spool directory."""

    if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(f"{name} is not an accessible directory: {path}")
    stat = path.stat()
    if stat.st_uid != os.geteuid():
        raise RuntimeError(f"{name} is not owned by the ESA service account")
    if stat.st_mode & 0o077:
        raise RuntimeError(f"{name} permissions must not allow group/other access")
    if shutil.disk_usage(path).free < required_bytes:
        raise RuntimeError(f"{name} does not have the configured safe free space")


def validate_durable_path(name: str, path: Path) -> None:
    """Reject authority or sole-backup paths inside Job-local temporary trees."""

    resolved = path.expanduser().resolve()
    temporary_roots = {Path("/tmp").resolve()}
    slurm_temp = os.environ.get("SLURM_TMPDIR")
    if slurm_temp:
        temporary_roots.add(Path(slurm_temp).expanduser().resolve())
    for temporary in temporary_roots:
        if resolved == temporary or resolved.is_relative_to(temporary):
            raise RuntimeError(f"{name} must not be stored under {temporary}")


def validate_startup_config() -> None:
    """Fail early for enabled optional subsystems and local model paths."""

    for name, value in (
        ("ESA_MODEL_PATH", MODEL_PATH),
        ("ESA_AUXILIARY_MODEL_PATH", AUXILIARY_MODEL_PATH),
    ):
        candidate = Path(value).expanduser()
        if candidate.is_absolute() and not candidate.exists():
            raise RuntimeError(f"{name} points to a missing local path: {candidate}")
    if MODEL_LORA_PATH:
        lora_path = Path(MODEL_LORA_PATH).expanduser()
        if not lora_path.is_dir():
            raise RuntimeError(
                f"ESA_MODEL_LORA_PATH points to a missing directory: {lora_path}"
            )
        required_lora_files = (
            lora_path / "adapter_config.json",
            lora_path / "adapter_model.safetensors",
        )
        missing_lora_files = [path for path in required_lora_files if not path.is_file()]
        if missing_lora_files:
            values = ", ".join(str(path) for path in missing_lora_files)
            raise RuntimeError(f"LoRA adapter files are missing: {values}")
        try:
            adapter_config = json.loads(required_lora_files[0].read_text("utf-8"))
            adapter_rank = int(adapter_config["r"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Invalid LoRA adapter config: {required_lora_files[0]}"
            ) from exc
        if adapter_rank > MODEL_LORA_MAX_RANK:
            raise RuntimeError(
                f"LoRA rank {adapter_rank} exceeds ESA_MODEL_LORA_MAX_RANK "
                f"{MODEL_LORA_MAX_RANK}"
            )
        adapter_base = adapter_config.get("base_model_name_or_path")
        configured_base = Path(MODEL_PATH).expanduser()
        if (
            isinstance(adapter_base, str)
            and Path(adapter_base).is_absolute()
            and configured_base.is_absolute()
            and Path(adapter_base).resolve() != configured_base.resolve()
        ):
            raise RuntimeError(
                f"LoRA base model {adapter_base} does not match "
                f"ESA_MODEL_PATH {configured_base}"
            )
    if PERSONAL_KB_ENABLED:
        if PERSONAL_KB_QDRANT_COLLECTION == RAG_QDRANT_COLLECTION:
            raise RuntimeError(
                "PERSONAL_KB_QDRANT_COLLECTION must not reuse the global RAG collection"
            )
        if not PERSONAL_KB_ROOT.is_dir():
            raise RuntimeError(
                f"PERSONAL_KB_ROOT is not an existing directory: {PERSONAL_KB_ROOT}"
            )
        if not os.access(PERSONAL_KB_ROOT, os.R_OK | os.W_OK | os.X_OK):
            raise RuntimeError(
                f"PERSONAL_KB_ROOT is not readable and writable: {PERSONAL_KB_ROOT}"
            )
        validate_durable_path("PERSONAL_KB_ROOT", PERSONAL_KB_ROOT)
        validate_durable_path(
            "PERSONAL_KB_SNAPSHOT_ROOT", PERSONAL_KB_SNAPSHOT_ROOT
        )
        try:
            PERSONAL_KB_SNAPSHOT_ROOT.relative_to(PERSONAL_KB_ROOT)
        except ValueError as exc:
            raise RuntimeError(
                "PERSONAL_KB_SNAPSHOT_ROOT must be inside PERSONAL_KB_ROOT"
            ) from exc
        if PERSONAL_KB_MAX_BATCH_BYTES < PERSONAL_KB_MAX_FILE_BYTES:
            raise RuntimeError(
                "PERSONAL_KB_MAX_BATCH_BYTES must be at least PERSONAL_KB_MAX_FILE_BYTES"
            )
        for name, path, required in (
            (
                "PERSONAL_KB_ROOT",
                PERSONAL_KB_ROOT,
                PERSONAL_KB_MAX_BATCH_BYTES + PERSONAL_KB_MIN_FREE_BYTES,
            ),
            (
                "PERSONAL_KB_TEMP_ROOT",
                PERSONAL_KB_TEMP_ROOT,
                PERSONAL_KB_MAX_REQUEST_BYTES + PERSONAL_KB_MIN_FREE_BYTES,
            ),
        ):
            validate_private_storage_capacity(name, path, required)
    if MCP_ENABLED:
        if not MCP_YOU_API_KEY:
            raise RuntimeError(
                "YDC_API_KEY must be set in the supercomputer environment"
            )
        if shutil.which(MCP_YOU_COMMAND) is None:
            raise RuntimeError(
                f"MCP command {MCP_YOU_COMMAND!r} was not found on PATH; "
                "install Node.js 18 or newer"
            )
    if EMAIL_PROVIDER == "service":
        if not EMAIL_SERVICE_URL or not EMAIL_SERVICE_URL.startswith("https://"):
            raise RuntimeError("EMAIL_SERVICE_URL must be an https URL")
        if not EMAIL_SERVICE_TOKEN or len(EMAIL_SERVICE_TOKEN) < 32:
            raise RuntimeError(
                "EMAIL_SERVICE_TOKEN in config_private.py must contain at least 32 characters"
            )
        if not EMAIL_VERIFICATION_SECRET or len(EMAIL_VERIFICATION_SECRET) < 32:
            raise RuntimeError(
                "EMAIL_VERIFICATION_SECRET in config_private.py must contain at least 32 characters"
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
