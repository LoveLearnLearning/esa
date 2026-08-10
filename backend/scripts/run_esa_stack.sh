#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

if type module >/dev/null 2>&1; then
    module load cuda/13.0 || true
fi

source /persist_data/apps/miniconda3/etc/profile.d/conda.sh
conda activate /persist_data/home/chenxuzhao/.conda/envs~/esa

export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
unset PYTHONPATH

export CUDA_HOME=/persist_data/apps/cuda-13.0
export CUDA_PATH="$CUDA_HOME"
export CUDACXX="$CUDA_HOME/bin/nvcc"
export PATH="$CUDA_HOME/bin:$CONDA_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/lib/python3.10/site-packages/torch/lib:$CONDA_PREFIX/lib/python3.10/site-packages/nvidia/cu13/cccl/lib:$CONDA_PREFIX/lib/python3.10/site-packages/nvidia/cu13/lib:$CONDA_PREFIX/lib/python3.10/site-packages/nvidia/cudnn/lib:$CONDA_PREFIX/lib/python3.10/site-packages/nvidia/cusparselt/lib:$CONDA_PREFIX/lib/python3.10/site-packages/nvidia/nccl/lib:$CONDA_PREFIX/lib/python3.10/site-packages/nvidia/nvshmem/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TORCH_CUDA_ARCH_LIST='8.0'
export CMAKE_CUDA_ARCHITECTURES='80'
export VLLM_TARGET_DEVICE='cuda'

read -r \
    main_model main_tp \
    auxiliary_model auxiliary_name auxiliary_port auxiliary_dtype \
    auxiliary_gpu_memory auxiliary_max_length auxiliary_max_num_seqs < <(
    python - <<'PY'
from backend.core.utils.config import (
    AUXILIARY_MODEL_DTYPE,
    AUXILIARY_MODEL_GPU_MEMORY_UTILIZATION,
    AUXILIARY_MODEL_MAX_MODEL_LENGTH,
    AUXILIARY_MODEL_MAX_NUM_SEQS,
    AUXILIARY_MODEL_NAME,
    AUXILIARY_MODEL_PATH,
    AUXILIARY_MODEL_PORT,
    MODEL_PATH,
    MODEL_TENSOR_PARALLEL_SIZE,
)

print(
    MODEL_PATH,
    MODEL_TENSOR_PARALLEL_SIZE,
    AUXILIARY_MODEL_PATH,
    AUXILIARY_MODEL_NAME,
    AUXILIARY_MODEL_PORT,
    AUXILIARY_MODEL_DTYPE,
    AUXILIARY_MODEL_GPU_MEMORY_UTILIZATION,
    AUXILIARY_MODEL_MAX_MODEL_LENGTH,
    AUXILIARY_MODEL_MAX_NUM_SEQS,
)
PY
)

if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
    IFS=',' read -r -a allocated_gpus <<< "$CUDA_VISIBLE_DEVICES"
else
    mapfile -t allocated_gpus < <(
        nvidia-smi --query-gpu=index --format=csv,noheader
    )
fi

required_gpu_count=$((main_tp + 1))
if (( ${#allocated_gpus[@]} < required_gpu_count )); then
    echo "ERROR: 主模型 TP=${main_tp} 加辅助模型需要 ${required_gpu_count} 张 GPU，当前只有 ${#allocated_gpus[@]} 张。" >&2
    exit 1
fi

main_devices="$(IFS=,; echo "${allocated_gpus[*]:0:main_tp}")"
auxiliary_device="${allocated_gpus[main_tp]}"
runtime_root="${SLURM_TMPDIR:-/tmp}/esa-${SLURM_JOB_ID:-$$}"
auxiliary_cache="$runtime_root/triton-auxiliary"
main_cache="$runtime_root/triton-main"
mkdir -p "$auxiliary_cache" "$main_cache" logs

auxiliary_pid=''
backend_pid=''
cleanup_started=0
cleanup() {
    local pid
    if (( cleanup_started == 1 )); then
        return
    fi
    cleanup_started=1
    for pid in "$backend_pid" "$auxiliary_pid"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$backend_pid" "$auxiliary_pid"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT INT TERM

echo "Node=$(hostname)"
echo "AllocatedGPUs=${CUDA_VISIBLE_DEVICES:-all}"
echo "MainModel=$main_model MainGPUs=$main_devices TP=$main_tp"
echo "AuxiliaryModel=$auxiliary_model AuxiliaryGPU=$auxiliary_device"
echo "AuxiliaryEndpoint=http://127.0.0.1:${auxiliary_port}/v1"

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
    --generation-config vllm \
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

echo "===== Starting ESA backend ====="
CUDA_VISIBLE_DEVICES="$main_devices" \
TRITON_CACHE_DIR="$main_cache" \
python -m backend.main &
backend_pid=$!

set +e
wait -n "$auxiliary_pid" "$backend_pid"
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
fi
exit "$status"
