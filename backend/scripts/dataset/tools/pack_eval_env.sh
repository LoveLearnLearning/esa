#!/usr/bin/env bash

set -Eeuo pipefail

source_env="${1:-/persist_data/home/chenxuzhao/.conda/envs~/lf}"
output="${2:-/remote_dir/home/chenxuzhao/esa-runtime/lf-eval-env.tar.zst}"
zstd_bin="${ZSTD_BIN:-/persist_data/apps/miniconda3/bin/zstd}"

if [[ ! -x "$source_env/bin/python" ]]; then
    echo "ERROR: Python environment not found: $source_env" >&2
    exit 1
fi
if [[ ! -x "$zstd_bin" ]]; then
    echo "ERROR: zstd not found: $zstd_bin" >&2
    exit 1
fi

mkdir -p "$(dirname "$output")"
tmp="${output}.tmp.$$"
trap 'rm -f "$tmp"' EXIT

echo "Packing $source_env -> $output"
tar -I "$zstd_bin -1 -T0" -cf "$tmp" \
    -C "$(dirname "$source_env")" "$(basename "$source_env")"
mv "$tmp" "$output"
sha256sum "$output" > "${output}.sha256"
trap - EXIT

ls -lh "$output" "${output}.sha256"
