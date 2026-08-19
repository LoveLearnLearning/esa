#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/../.." && pwd)"
package_dir="$(mktemp -d "${TMPDIR:-/tmp}/esa-lsp-package.XXXXXX")"
trap 'rm -rf "$package_dir"' EXIT

files=(
  backend/core/services/lsp_service.py
  backend/core/utils/config.py
  backend/core/web/routers/lsp.py
  backend/core/web/webAPI.py
  backend/scripts/check_lsp_servers.py
  backend/tests/test_lsp_service.py
  deploy/LSP.md
  deploy/nginx/esa-web.conf.example
)

for relative_path in "${files[@]}"; do
  mkdir -p "$package_dir/esa/$(dirname "$relative_path")"
  cp "$repo_dir/$relative_path" "$package_dir/esa/$relative_path"
done

tar -czf "$repo_dir/backend-lsp-patch.tar.gz" -C "$package_dir" esa
echo "Built $repo_dir/backend-lsp-patch.tar.gz"
shasum -a 256 "$repo_dir/backend-lsp-patch.tar.gz"
