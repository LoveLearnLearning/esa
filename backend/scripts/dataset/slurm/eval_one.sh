#!/usr/bin/env bash
#SBATCH --job-name=esa_eval
#SBATCH --partition=gre
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:4
#SBATCH --mem=240G
#SBATCH --time=05:00:00
#SBATCH --output=/persist_data/home/chenxuzhao/esa_eval_%x_%j.log
#SBATCH --error=/persist_data/home/chenxuzhao/esa_eval_%x_%j.err

set -Eeuo pipefail

TAG=${1:?Usage: sbatch eval_one.sh <infer-tag> [train-job] [adapter-dir]}
TRAIN_JOB=${2:-}
ADAPTER_DIR=${3:-}

PROJECT_ROOT="${ESA_PROJECT_ROOT:-/persist_data/home/chenxuzhao/esa}"
DATASET="$PROJECT_ROOT/backend/scripts/dataset"
LF="${ESA_LLAMAFACTORY_ROOT:-/persist_data/home/chenxuzhao/LlamaFactory}"
YAML="${ESA_INFER_YAML:-$LF/esa_infer_$TAG.yaml}"
RESULTS="${ESA_EVAL_RESULTS_DIR:-/persist_data/home/chenxuzhao/esa_results}"
OUTPUT_TAG="${ESA_EVAL_OUTPUT_TAG:-${TAG}_opt}"
MAX_TOKENS="${ESA_EVAL_MAX_TOKENS:-8192}"
EXPECTED_MAIN_FINGERPRINT="${ESA_EXPECT_MAIN_FINGERPRINT:-d441611fb5556b53}"
EXPECTED_SUPP_FINGERPRINT="${ESA_EXPECT_SUPP_FINGERPRINT:-46d55cde4d703fe6}"
ENV_SOURCE="${ESA_LF_ENV:-/persist_data/home/chenxuzhao/.conda/envs~/lf}"
ENV_ARCHIVE="${ESA_LF_ENV_ARCHIVE:-/remote_dir/home/chenxuzhao/esa-runtime/lf-eval-env.tar.zst}"
ZSTD_BIN="${ZSTD_BIN:-/persist_data/apps/miniconda3/bin/zstd}"
RUNTIME_ROOT="${SLURM_TMPDIR:-/tmp}/esa-eval-${SLURM_JOB_ID:-$$}"
API_LOG="${ESA_EVAL_API_LOG:-/persist_data/home/chenxuzhao/esa_api_${OUTPUT_TAG}_${SLURM_JOB_ID:-$$}.log}"
PORT=$((8000 + ${SLURM_JOB_ID:-0} % 1000))

SERVER_PID=""
cleanup() {
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

mkdir -p "$RESULTS" "$RUNTIME_ROOT"
echo "Job Start: $(date) node=$(hostname) tag=$TAG output_tag=$OUTPUT_TAG"

for path in "$YAML" "$DATASET/data/eval/eval.jsonl" "$DATASET/data/eval/eval_supp.jsonl"; do
    [[ -f "$path" ]] || { echo "ERROR: missing $path" >&2; exit 1; }
done

main_fingerprint=$(sha256sum "$DATASET/data/eval/eval.jsonl" | cut -c1-16)
supp_fingerprint=$(sha256sum "$DATASET/data/eval/eval_supp.jsonl" | cut -c1-16)
if [[ "$main_fingerprint" != "$EXPECTED_MAIN_FINGERPRINT" ||
      "$supp_fingerprint" != "$EXPECTED_SUPP_FINGERPRINT" ]]; then
    echo "ERROR: evaluation data changed; refusing to produce incomparable report evidence" >&2
    echo "  main: expected=$EXPECTED_MAIN_FINGERPRINT actual=$main_fingerprint" >&2
    echo "  supp: expected=$EXPECTED_SUPP_FINGERPRINT actual=$supp_fingerprint" >&2
    exit 1
fi

PYTHON_BIN=""
if [[ -f "$ENV_ARCHIVE" ]]; then
    echo "Staging Python environment from $ENV_ARCHIVE"
    stage_started=$SECONDS
    [[ -x "$ZSTD_BIN" ]] || { echo "ERROR: zstd not found: $ZSTD_BIN" >&2; exit 1; }
    tar -I "$ZSTD_BIN -d" -xf "$ENV_ARCHIVE" -C "$RUNTIME_ROOT"
    PYTHON_BIN="$RUNTIME_ROOT/$(basename "$ENV_SOURCE")/bin/python"
    [[ -x "$PYTHON_BIN" ]] || { echo "ERROR: staged Python is missing" >&2; exit 1; }
    echo "Environment ready in $((SECONDS - stage_started))s"
else
    echo "WARNING: environment archive missing; using shared environment: $ENV_SOURCE"
    PYTHON_BIN="$ENV_SOURCE/bin/python"
fi

export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$LF/src"
export XDG_CACHE_HOME="$RUNTIME_ROOT/cache"
export HF_HOME="$RUNTIME_ROOT/huggingface"
export TRITON_CACHE_DIR="$RUNTIME_ROOT/triton"
export TORCHINDUCTOR_CACHE_DIR="$RUNTIME_ROOT/torchinductor"
export API_VERBOSE=0
export API_MODEL_NAME="esa-$TAG"
export API_PORT="$PORT"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
export no_proxy="$NO_PROXY"

IFS='|' read -r yaml_model yaml_adapter yaml_thinking < <(
    "$PYTHON_BIN" - "$YAML" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
print("|".join((
    str(cfg.get("model_name_or_path", "")),
    str(cfg.get("adapter_name_or_path", "")),
    str(cfg.get("enable_thinking", "unset")).lower(),
)))
PY
)

if [[ "$TAG" == *nothink* && "$yaml_thinking" != "false" ]]; then
    echo "ERROR: $TAG must set enable_thinking: false in $YAML" >&2
    exit 1
fi
if [[ -n "$ADAPTER_DIR" && "${ADAPTER_DIR%/}" != "${yaml_adapter%/}" ]]; then
    echo "ERROR: adapter argument and YAML differ" >&2
    echo "  argument: $ADAPTER_DIR" >&2
    echo "  YAML:     $yaml_adapter" >&2
    exit 1
fi
if [[ -n "$yaml_adapter" ]]; then
    ADAPTER_DIR="$yaml_adapter"
    [[ -n "$TRAIN_JOB" ]] || { echo "ERROR: LoRA evaluation requires train-job" >&2; exit 1; }
    "$PYTHON_BIN" "$DATASET/tools/check_adapter_fresh.py" \
        --adapter "$ADAPTER_DIR/adapter_model.safetensors" --train-job "$TRAIN_JOB"
fi

# The model process stays isolated from user-site packages. The lightweight
# evaluator intentionally uses the existing user site because jsonschema is
# installed there rather than in the LlamaFactory environment.
if ! env -u PYTHONNOUSERSITE PYTHONPATH="$DATASET" "$PYTHON_BIN" -c \
    'import jsonschema; import esa.eval'; then
    echo "ERROR: evaluator dependencies are not importable" >&2
    exit 1
fi

run_fingerprint=$(
    {
        sha256sum "$YAML" "$DATASET/esa/eval.py"
        [[ -n "$ADAPTER_DIR" ]] && sha256sum "$ADAPTER_DIR/adapter_model.safetensors"
        for model_file in config.json generation_config.json tokenizer_config.json; do
            [[ -f "$yaml_model/$model_file" ]] && sha256sum "$yaml_model/$model_file"
        done
        [[ -f "${ENV_ARCHIVE}.sha256" ]] && cat "${ENV_ARCHIVE}.sha256"
        printf 'max_tokens=%s\n' "$MAX_TOKENS"
    } | sha256sum | cut -c1-20
)
echo "Run fingerprint: $run_fingerprint"

if [[ "${ESA_EVAL_PREFLIGHT_ONLY:-0}" == "1" ]]; then
    echo "Preflight complete; model API was not started."
    exit 0
fi

echo "Starting model API on port $PORT"
api_started=$SECONDS
cd "$LF"
"$PYTHON_BIN" -m llamafactory.cli api "$YAML" >"$API_LOG" 2>&1 &
SERVER_PID=$!

ready=0
for i in $(seq 1 1080); do
    if curl -sf --noproxy '*' "http://127.0.0.1:$PORT/v1/models" >/dev/null; then
        ready=1
        break
    fi
    kill -0 "$SERVER_PID" 2>/dev/null || {
        echo "ERROR: model API exited" >&2
        tail -n 80 "$API_LOG" >&2 || true
        exit 1
    }
    if (( i % 30 == 0 )); then
        echo "Waiting for API: $((i / 6))m log_bytes=$(wc -c < "$API_LOG")"
    fi
    sleep 10
done
(( ready == 1 )) || { echo "ERROR: API did not start within 180 minutes" >&2; exit 1; }
echo "API ready in $((SECONDS - api_started))s: $(date)"

cd "$DATASET"
predict_common=(
    --endpoint "http://127.0.0.1:$PORT/v1"
    --model "esa-$TAG"
    --tag "$OUTPUT_TAG"
    --resume
    --run-fingerprint "$run_fingerprint"
    --max-tokens "$MAX_TOKENS"
    --progress-every 10
)

env -u PYTHONNOUSERSITE PYTHONPATH="$DATASET" \
    "$PYTHON_BIN" -m esa.eval predict "${predict_common[@]}"
env -u PYTHONNOUSERSITE PYTHONPATH="$DATASET" \
    "$PYTHON_BIN" -m esa.eval --suite supp predict "${predict_common[@]}"

env -u PYTHONNOUSERSITE PYTHONPATH="$DATASET" "$PYTHON_BIN" -m esa.eval \
    --adjudication data/eval/refusal_adjudication.json score --tag "$OUTPUT_TAG"
env -u PYTHONNOUSERSITE PYTHONPATH="$DATASET" "$PYTHON_BIN" -m esa.eval \
    --adjudication data/eval/refusal_adjudication.json --suite supp score --tag "$OUTPUT_TAG"

for file in \
    "pred_${OUTPUT_TAG}.jsonl" "report_${OUTPUT_TAG}.json" \
    "pred_supp_${OUTPUT_TAG}.jsonl" "report_supp_${OUTPUT_TAG}.json"; do
    [[ -f "data/eval/$file" ]] && cp "data/eval/$file" \
        "$RESULTS/${file%.*}_${SLURM_JOB_ID:-manual}.${file##*.}"
done

echo "Job End: $(date) elapsed=$SECONDS seconds"
