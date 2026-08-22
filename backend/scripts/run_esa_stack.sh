#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

esa_env_override="${ESA_ENV_FILE:-}"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
fi
if [[ -n "$esa_env_override" ]]; then
    if [[ ! -f "$esa_env_override" ]]; then
        echo "ERROR: ESA_ENV_FILE 不存在：$esa_env_override" >&2
        exit 1
    fi
    set -a
    # shellcheck disable=SC1090
    source "$esa_env_override"
    set +a
fi

if type module >/dev/null 2>&1; then
    module load cuda/13.0 || true
fi

if [[ -n "${ESA_CONDA_SH:-}" ]]; then
    source "$ESA_CONDA_SH"
fi
if [[ -n "${ESA_CONDA_ENV:-}" ]]; then
    if ! type conda >/dev/null 2>&1; then
        echo "ERROR: ESA_CONDA_ENV is set but conda is unavailable; set ESA_CONDA_SH." >&2
        exit 1
    fi
    conda activate "$ESA_CONDA_ENV"
fi

export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
unset PYTHONPATH
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
export no_proxy="$NO_PROXY"

if [[ -n "${ESA_CUDA_HOME:-}" ]]; then
    export CUDA_HOME="$ESA_CUDA_HOME"
    export CUDA_PATH="$CUDA_HOME"
    export CUDACXX="$CUDA_HOME/bin/nvcc"
    export PATH="$CUDA_HOME/bin:$PATH"
fi
if [[ -n "${CONDA_PREFIX:-}" ]]; then
    export PATH="$CONDA_PREFIX/bin:$PATH"
    export LD_LIBRARY_PATH="$CONDA_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
export TORCH_CUDA_ARCH_LIST='8.0'
export CMAKE_CUDA_ARCHITECTURES='80'
export VLLM_TARGET_DEVICE='cuda'

case "${MM_ENABLED:-false}" in
    1|true|TRUE|yes|YES|on|ON) mm_enabled=1 ;;
    *) mm_enabled=0 ;;
esac

case "${PERSONAL_KB_ENABLED:-false}" in
    1|true|TRUE|yes|YES|on|ON) personal_kb_enabled=1 ;;
    *) personal_kb_enabled=0 ;;
esac

case "${ESA_SHARED_COMPUTE_NODE:-false}" in
    1|true|TRUE|yes|YES|on|ON) shared_compute_node=1 ;;
    *) shared_compute_node=0 ;;
esac
if (( shared_compute_node == 1 )) && {
    [[ -z "${RAG_QDRANT_BASE_URL:-}" ]] ||
    [[ "${RAG_QDRANT_BASE_URL}" == "http://127.0.0.1:6333" ]] ||
    [[ "${RAG_QDRANT_BASE_URL}" == "http://localhost:6333" ]];
}; then
    if [[ -z "${ESA_QDRANT_HTTP_PORT:-}" ]]; then
        ESA_QDRANT_HTTP_PORT="$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
        export ESA_QDRANT_HTTP_PORT
    fi
    export RAG_QDRANT_BASE_URL="http://127.0.0.1:${ESA_QDRANT_HTTP_PORT}"
fi

read -r \
    main_model main_tp main_lora main_lora_name \
    auxiliary_model auxiliary_name auxiliary_port auxiliary_dtype \
    auxiliary_gpu_memory auxiliary_max_length auxiliary_max_num_seqs \
    auxiliary_max_images rag_enabled rag_embedding_backend \
    rag_embedding_device rag_qdrant_url rag_qdrant_collection \
    mcp_enabled personal_kb_config_enabled < <(
    python - <<'PY'
from backend.core.utils.config import (
    AUXILIARY_MODEL_DTYPE,
    AUXILIARY_MODEL_GPU_MEMORY_UTILIZATION,
    AUXILIARY_MODEL_MAX_MODEL_LENGTH,
    AUXILIARY_MODEL_MAX_IMAGES_PER_PROMPT,
    AUXILIARY_MODEL_MAX_NUM_SEQS,
    AUXILIARY_MODEL_NAME,
    AUXILIARY_MODEL_PATH,
    AUXILIARY_MODEL_PORT,
    MODEL_PATH,
    MODEL_LORA_NAME,
    MODEL_LORA_PATH,
    MODEL_TENSOR_PARALLEL_SIZE,
    MCP_ENABLED,
    PERSONAL_KB_ENABLED,
    RAG_EMBEDDING_BACKEND,
    RAG_EMBEDDING_DEVICE,
    RAG_ENABLED,
    RAG_QDRANT_BASE_URL,
    RAG_QDRANT_COLLECTION,
)

print(
    MODEL_PATH,
    MODEL_TENSOR_PARALLEL_SIZE,
    MODEL_LORA_PATH or "disabled",
    MODEL_LORA_NAME,
    AUXILIARY_MODEL_PATH,
    AUXILIARY_MODEL_NAME,
    AUXILIARY_MODEL_PORT,
    AUXILIARY_MODEL_DTYPE,
    AUXILIARY_MODEL_GPU_MEMORY_UTILIZATION,
    AUXILIARY_MODEL_MAX_MODEL_LENGTH,
    AUXILIARY_MODEL_MAX_NUM_SEQS,
    AUXILIARY_MODEL_MAX_IMAGES_PER_PROMPT,
    "1" if RAG_ENABLED else "0",
    RAG_EMBEDDING_BACKEND,
    RAG_EMBEDDING_DEVICE,
    RAG_QDRANT_BASE_URL,
    RAG_QDRANT_COLLECTION,
    "1" if MCP_ENABLED else "0",
    "1" if PERSONAL_KB_ENABLED else "0",
)
PY
)

# The environment switch and parsed application config must agree. This catches
# misspelled boolean values before allocating model/Qdrant processes.
if [[ "$personal_kb_enabled" != "$personal_kb_config_enabled" ]]; then
    echo "ERROR: PERSONAL_KB_ENABLED could not be parsed consistently." >&2
    exit 1
fi

if [[ "$mcp_enabled" == "1" ]]; then
    if [[ -z "${YDC_API_KEY:-}" ]]; then
        echo "ERROR: MCP 已启用，但超算环境中没有 YDC_API_KEY。" >&2
        exit 1
    fi
    if ! command -v node >/dev/null 2>&1 || ! command -v npx >/dev/null 2>&1; then
        echo "ERROR: You.com MCP 需要 Node.js >= 18 和 npx。" >&2
        exit 1
    fi
    node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
    if (( node_major < 18 )); then
        echo "ERROR: You.com MCP 需要 Node.js >= 18，当前为 $(node --version)。" >&2
        exit 1
    fi
    if ! python -c 'import mcp' >/dev/null 2>&1; then
        echo "ERROR: Python MCP SDK 未安装，请先执行 python -m pip install -r requirements.txt。" >&2
        exit 1
    fi
fi

if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
    IFS=',' read -r -a allocated_gpus <<< "$CUDA_VISIBLE_DEVICES"
else
    mapfile -t allocated_gpus < <(
        nvidia-smi --query-gpu=index --format=csv,noheader
    )
fi

retrieval_enabled=0
if [[ "$rag_enabled" == "1" || "$personal_kb_enabled" == "1" ]]; then
    retrieval_enabled=1
fi
rag_gpu_count=0
if [[ "$retrieval_enabled" == "1" && "$rag_embedding_backend" == "transformers" && "$rag_embedding_device" == cuda* ]]; then
    rag_gpu_count=1
fi

required_gpu_count=$((main_tp + 1 + rag_gpu_count))
if (( ${#allocated_gpus[@]} < required_gpu_count )); then
    echo "ERROR: 当前配置需要 ${required_gpu_count} 张 GPU（主模型 TP=${main_tp}、辅助模型 1、RAG Embedding ${rag_gpu_count}），当前只有 ${#allocated_gpus[@]} 张。" >&2
    exit 1
fi

main_devices="$(IFS=,; echo "${allocated_gpus[*]:0:main_tp}")"
auxiliary_device="${allocated_gpus[main_tp]}"
backend_devices="$main_devices"
rag_device=''
if (( rag_gpu_count == 1 )); then
    rag_device="${allocated_gpus[main_tp + 1]}"
    backend_devices="${main_devices},${rag_device}"
    export RAG_EMBEDDING_RUNTIME_DEVICE="${RAG_EMBEDDING_RUNTIME_DEVICE:-cuda:${main_tp}}"
fi
runtime_root="${SLURM_TMPDIR:-/tmp}/esa-${SLURM_JOB_ID:-$$}"
auxiliary_cache="$runtime_root/triton-auxiliary"
main_cache="$runtime_root/triton-main"
mkdir -p "$auxiliary_cache" "$main_cache" logs

mineru_api_port="${MM_MINERU_API_PORT:-51026}"
mineru_api_url="${MM_MINERU_API_URL:-http://127.0.0.1:${mineru_api_port}}"
mineru_api_bin="${MINERU_API_BIN:-$PROJECT_ROOT/runtime/mineru-env/bin/mineru-api}"
mineru_library_path="${MINERU_LIBRARY_PATH:-}"
mineru_output_root="${MINERU_API_OUTPUT_ROOT:-$runtime_root/mineru-output}"
mineru_task_retention_seconds="${MINERU_API_TASK_RETENTION_SECONDS:-300}"
mineru_api_pid=''

auxiliary_pid=''
backend_pid=''
qdrant_pid=''
cleanup_started=0
cleanup() {
    local pid
    if (( cleanup_started == 1 )); then
        return
    fi
    cleanup_started=1
    # Qdrant must outlive the backend's graceful shutdown so the personal
    # snapshot manager can flush its final dirty sequence.
    if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
        kill "$backend_pid" 2>/dev/null || true
        for _ in $(seq 1 "${ESA_BACKEND_SHUTDOWN_GRACE_SECONDS:-120}"); do
            kill -0 "$backend_pid" 2>/dev/null || break
            sleep 1
        done
    fi
    for pid in "$auxiliary_pid" "$mineru_api_pid" "$qdrant_pid"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$backend_pid" "$auxiliary_pid" "$mineru_api_pid" "$qdrant_pid"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT INT TERM

echo "Node=$(hostname)"
echo "AllocatedGPUs=${CUDA_VISIBLE_DEVICES:-all}"
echo "MainModel=$main_model MainGPUs=$main_devices TP=$main_tp"
echo "MainLoRA=$main_lora LoRAName=$main_lora_name"
echo "AuxiliaryModel=$auxiliary_model AuxiliaryGPU=$auxiliary_device"
echo "AuxiliaryEndpoint=http://127.0.0.1:${auxiliary_port}/v1"
echo "MinerUEndpoint=$mineru_api_url"
if (( rag_gpu_count == 1 )); then
    echo "RAGEmbeddingGPU=$rag_device RuntimeDevice=$RAG_EMBEDDING_RUNTIME_DEVICE"
fi

if [[ "$retrieval_enabled" == "1" ]]; then
    qdrant_binary="${ESA_QDRANT_BINARY:-$PROJECT_ROOT/runtime/qdrant/bin/qdrant}"
    qdrant_storage="${ESA_QDRANT_STORAGE_PATH:-$runtime_root/qdrant-storage}"
    qdrant_snapshots="${ESA_QDRANT_SNAPSHOTS_PATH:-$runtime_root/qdrant-snapshots}"
    qdrant_temp="${ESA_QDRANT_TEMP_PATH:-$runtime_root/qdrant-temp}"
    qdrant_http_port="${ESA_QDRANT_HTTP_PORT:-6333}"
    qdrant_grpc_port="${ESA_QDRANT_GRPC_PORT:-$((qdrant_http_port + 1))}"
    qdrant_auth_args=()
    if [[ -n "${QDRANT_API_KEY:-}" ]]; then
        qdrant_auth_args=(--header "api-key: ${QDRANT_API_KEY}")
    fi
    qdrant_reachable=0
    if curl -q --noproxy '*' --silent --show-error --fail "${qdrant_auth_args[@]}" \
        --max-time 2 "${rag_qdrant_url%/}/healthz" >/dev/null 2>&1; then
        qdrant_reachable=1
    fi
    is_local_qdrant=0
    if [[ "$rag_qdrant_url" == "http://127.0.0.1:${qdrant_http_port}" || "$rag_qdrant_url" == "http://localhost:${qdrant_http_port}" ]]; then
        is_local_qdrant=1
    fi
    if (( qdrant_reachable == 1 && is_local_qdrant == 1 && personal_kb_enabled == 1 )); then
        echo "ERROR: 本地 Qdrant 已在运行，无法证明它属于当前 Slurm Job。" >&2
        exit 1
    fi
    if (( qdrant_reachable == 0 )); then
        if (( is_local_qdrant == 0 )); then
            echo "ERROR: 外部 Qdrant 不可用：$rag_qdrant_url" >&2
            exit 1
        fi
        if [[ ! -x "$qdrant_binary" ]]; then
            echo "ERROR: RAG 已启用但找不到 Qdrant：$qdrant_binary" >&2
            exit 1
        fi
        mkdir -p "$qdrant_storage" "$qdrant_snapshots" "$qdrant_temp"
        for qdrant_local_path in "$qdrant_storage" "$qdrant_snapshots" "$qdrant_temp"; do
            qdrant_path_type="$(stat -f -c '%T' "$qdrant_local_path" 2>/dev/null || true)"
            if [[ "$qdrant_path_type" == nfs* ]]; then
                echo "ERROR: Qdrant 活动目录不能位于 NFS：$qdrant_local_path" >&2
                exit 1
            fi
        done
        expected_qdrant_url="http://127.0.0.1:${qdrant_http_port}"
        if [[ "$rag_qdrant_url" != "$expected_qdrant_url" && "$rag_qdrant_url" != "http://localhost:${qdrant_http_port}" ]]; then
            echo "ERROR: 本地 Qdrant 端口与 RAG_QDRANT_BASE_URL 不一致。" >&2
            exit 1
        fi
        export QDRANT_API_KEY
        QDRANT_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
        qdrant_auth_args=(--header "api-key: ${QDRANT_API_KEY}")
        echo "===== Starting authenticated local Qdrant ====="
        (
            cd "$(dirname "$qdrant_binary")/.."
            export QDRANT__SERVICE__HOST=127.0.0.1
            export QDRANT__SERVICE__HTTP_PORT="$qdrant_http_port"
            export QDRANT__SERVICE__GRPC_PORT="$qdrant_grpc_port"
            export QDRANT__SERVICE__API_KEY="$QDRANT_API_KEY"
            export QDRANT__STORAGE__STORAGE_PATH="$qdrant_storage"
            export QDRANT__STORAGE__SNAPSHOTS_PATH="$qdrant_snapshots"
            export QDRANT__STORAGE__TEMP_PATH="$qdrant_temp"
            exec "$qdrant_binary" --disable-telemetry
        ) >logs/qdrant.log 2>&1 &
        qdrant_pid=$!
        for _ in $(seq 1 120); do
            if ! kill -0 "$qdrant_pid" 2>/dev/null; then
                echo "ERROR: Qdrant 启动失败，最后日志如下：" >&2
                tail -n 80 logs/qdrant.log >&2 || true
                exit 1
            fi
            if curl -q --noproxy '*' --silent --show-error --fail "${qdrant_auth_args[@]}" \
                --max-time 2 "${rag_qdrant_url%/}/healthz" >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
    fi
    qdrant_auth_args=()
    if [[ -n "${QDRANT_API_KEY:-}" ]]; then
        qdrant_auth_args=(--header "api-key: ${QDRANT_API_KEY}")
    fi
    if ! curl -q --noproxy '*' --silent --show-error --fail "${qdrant_auth_args[@]}" \
        --max-time 2 "${rag_qdrant_url%/}/healthz" >/dev/null 2>&1; then
        echo "ERROR: Qdrant 在等待期内未就绪：$rag_qdrant_url" >&2
        exit 1
    fi
    qdrant_snapshot="${ESA_QDRANT_SNAPSHOT_PATH:-}"
    if [[ "$rag_enabled" == "1" ]] && ! curl -q --noproxy '*' --silent --show-error --fail "${qdrant_auth_args[@]}" \
        --max-time 5 "${rag_qdrant_url%/}/collections/${rag_qdrant_collection}" \
        >/dev/null 2>&1; then
        if [[ -z "$qdrant_snapshot" ]]; then
            echo "ERROR: Qdrant Collection 不存在，且未设置 ESA_QDRANT_SNAPSHOT_PATH：${rag_qdrant_collection}" >&2
            exit 1
        fi
        if [[ ! -f "$qdrant_snapshot" ]]; then
            echo "ERROR: Qdrant snapshot 不存在：$qdrant_snapshot" >&2
            exit 1
        fi
        if [[ -n "$qdrant_pid" ]]; then
            mkdir -p "$qdrant_snapshots/$rag_qdrant_collection"
        fi
        qdrant_restore_helper="$PROJECT_ROOT/bin/restore-qdrant-snapshot"
        if [[ ! -x "$qdrant_restore_helper" ]]; then
            echo "ERROR: Qdrant 恢复脚本不存在或不可执行：$qdrant_restore_helper" >&2
            exit 1
        fi
        if ! "$qdrant_restore_helper" --help 2>&1 | \
            grep -q -- '--snapshot PATH'; then
            echo "ERROR: Qdrant 恢复脚本版本不兼容，请同步 bin/restore-qdrant-snapshot" >&2
            exit 1
        fi
        echo "===== Restoring and verifying Qdrant snapshot ====="
        PYTHON_BIN="${PYTHON_BIN:-python}" \
        "$qdrant_restore_helper" \
            --snapshot "$qdrant_snapshot" \
            --collection "$rag_qdrant_collection" \
            --qdrant-url "$rag_qdrant_url" \
            --timeout "${ESA_QDRANT_RESTORE_TIMEOUT:-1800}" \
            --wait-seconds "${ESA_QDRANT_RESTORE_WAIT_SECONDS:-300}"
        if ! curl -q --noproxy '*' --silent --show-error --fail "${qdrant_auth_args[@]}" \
            --max-time 10 "${rag_qdrant_url%/}/collections/${rag_qdrant_collection}" \
            >/dev/null 2>&1; then
            echo "ERROR: 恢复脚本返回成功，但目标 Collection 仍不存在：$rag_qdrant_collection" >&2
            exit 1
        fi
    fi
fi

echo "===== Starting auxiliary Qwen3.5-9B service ====="
CUDA_VISIBLE_DEVICES="$auxiliary_device" \
TRITON_CACHE_DIR="$auxiliary_cache" \
python -m vllm.entrypoints.openai.api_server \
    --model "$auxiliary_model" \
    --served-model-name "$auxiliary_name" \
    --host 127.0.0.1 \
    --port "$auxiliary_port" \
    --tensor-parallel-size 1 \
    --dtype "$auxiliary_dtype" \
    --gpu-memory-utilization "$auxiliary_gpu_memory" \
    --max-model-len "$auxiliary_max_length" \
    --max-num-seqs "$auxiliary_max_num_seqs" \
    --limit-mm-per-prompt "{\"image\": ${auxiliary_max_images}}" \
    --generation-config vllm \
    --default-chat-template-kwargs '{"enable_thinking":false}' \
    --enable-prefix-caching \
    --disable-log-stats \
    >logs/auxiliary-model.log 2>&1 &
auxiliary_pid=$!

auxiliary_ready=0
for _ in $(seq 1 900); do
    if ! kill -0 "$auxiliary_pid" 2>/dev/null; then
        echo "ERROR: 辅助模型启动失败，最后日志如下：" >&2
        tail -n 80 logs/auxiliary-model.log >&2 || true
        exit 1
    fi
    if curl -q --noproxy '*' --silent --show-error --fail \
        --max-time 2 "http://127.0.0.1:${auxiliary_port}/v1/models" \
        >/dev/null 2>&1; then
        auxiliary_ready=1
        break
    fi
    sleep 1
done

if (( auxiliary_ready == 0 )); then
    echo "ERROR: 辅助模型在 900 秒内未就绪。" >&2
    tail -n 80 logs/auxiliary-model.log >&2 || true
    exit 1
fi

if [[ "$mm_enabled" == "1" || "$personal_kb_enabled" == "1" ]]; then
    if [[ ! -x "$mineru_api_bin" ]]; then
        echo "ERROR: MM enabled but MinerU API executable not found: $mineru_api_bin" >&2
        exit 1
    fi
    if (( rag_gpu_count == 1 )); then
        mineru_device="${MINERU_API_DEVICE_MODE:-cuda:0}"
        mineru_visible_device="$rag_device"
    else
        mineru_device="${MINERU_API_DEVICE_MODE:-${MINERU_DEVICE_MODE:-cpu}}"
        mineru_visible_device="${CUDA_VISIBLE_DEVICES:-0}"
    fi
    echo "===== Starting resident MinerU API ====="
    mkdir -p "$mineru_output_root"
    CUDA_VISIBLE_DEVICES="$mineru_visible_device" \
    MINERU_DEVICE_MODE="$mineru_device" \
    MINERU_API_OUTPUT_ROOT="$mineru_output_root" \
    MINERU_API_TASK_RETENTION_SECONDS="$mineru_task_retention_seconds" \
    LD_LIBRARY_PATH="${mineru_library_path}${mineru_library_path:+${LD_LIBRARY_PATH:+:}}${LD_LIBRARY_PATH:-}" \
    "$mineru_api_bin" --host 127.0.0.1 --port "$mineru_api_port" \
        >logs/mineru-api.log 2>&1 &
    mineru_api_pid=$!
    mineru_ready=0
    for _ in $(seq 1 180); do
        if ! kill -0 "$mineru_api_pid" 2>/dev/null; then
            echo "ERROR: MinerU API 启动失败，最后日志如下：" >&2
            tail -n 80 logs/mineru-api.log >&2 || true
            exit 1
        fi
        if curl -q --noproxy '*' --silent --show-error --fail \
            --max-time 2 "${mineru_api_url%/}/health" >/dev/null 2>&1; then
            mineru_ready=1
            break
        fi
        sleep 1
    done
    if (( mineru_ready == 0 )); then
        echo "ERROR: MinerU API 在 180 秒内未就绪。" >&2
        tail -n 80 logs/mineru-api.log >&2 || true
        exit 1
    fi
    echo "===== Warming resident MinerU pipeline ====="
    if ! python -m backend.scripts.warmup_mineru \
        --api-url "$mineru_api_url" \
        --timeout-seconds "${MM_MINERU_TIMEOUT_SECONDS:-7200}"; then
        echo "ERROR: MinerU pipeline 预热失败，最后日志如下：" >&2
        tail -n 80 logs/mineru-api.log >&2 || true
        exit 1
    fi
    if ! kill -0 "$mineru_api_pid" 2>/dev/null; then
        echo "ERROR: MinerU API 在预热后退出。" >&2
        tail -n 80 logs/mineru-api.log >&2 || true
        exit 1
    fi
    echo "===== Resident MinerU pipeline ready ====="
    export MM_MINERU_API_URL="$mineru_api_url"
    export PERSONAL_KB_MINERU_API_URL="$mineru_api_url"
fi

echo "===== Starting ESA backend ====="
CUDA_VISIBLE_DEVICES="$backend_devices" \
TRITON_CACHE_DIR="$main_cache" \
python -m backend.main &
backend_pid=$!

wait_targets=("$auxiliary_pid" "$backend_pid")
if [[ -n "$mineru_api_pid" ]]; then
    wait_targets+=("$mineru_api_pid")
fi
if [[ -n "$qdrant_pid" ]]; then
    wait_targets+=("$qdrant_pid")
fi
set +e
wait -n "${wait_targets[@]}"
status=$?
set -e

if (( cleanup_started == 0 )); then
    if ! kill -0 "$auxiliary_pid" 2>/dev/null; then
        echo "ERROR: 辅助模型服务意外退出。" >&2
        tail -n 80 logs/auxiliary-model.log >&2 || true
    fi
    if ! kill -0 "$backend_pid" 2>/dev/null; then
        echo "ESA backend exited with status $status." >&2
    fi
    if [[ -n "$mineru_api_pid" ]] && ! kill -0 "$mineru_api_pid" 2>/dev/null; then
        echo "ERROR: MinerU API 服务意外退出。" >&2
        tail -n 80 logs/mineru-api.log >&2 || true
    fi
    if [[ -n "$qdrant_pid" ]] && ! kill -0 "$qdrant_pid" 2>/dev/null; then
        echo "ERROR: Qdrant 服务意外退出。" >&2
        tail -n 80 logs/qdrant.log >&2 || true
    fi
fi
exit "$status"
