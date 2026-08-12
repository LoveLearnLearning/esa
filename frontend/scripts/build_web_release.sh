#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
frontend_dir="$(cd "$script_dir/.." && pwd)"
repo_dir="$(cd "$frontend_dir/.." && pwd)"

cd "$frontend_dir"
flutter build web \
  --release \
  --pwa-strategy=none \
  --dart-define=ESA_API_BASE=/api

find build/web -type f \
  \( -name '*.js' -o -name '*.wasm' -o -name '*.json' -o \
     -name '*.svg' -o -name '*.css' -o -name '*.html' \) \
  -size +1k -exec gzip -9 -k -f {} \;

package_dir="$(mktemp -d "${TMPDIR:-/tmp}/esa-web-package.XXXXXX")"
trap 'rm -rf "$package_dir"' EXIT
mkdir -p "$package_dir/esa"
cp -R build/web/. "$package_dir/esa/"
tar -czf "$repo_dir/frontend-web.tar.gz" -C "$package_dir" esa

echo "Built $repo_dir/frontend-web.tar.gz"
shasum -a 256 "$repo_dir/frontend-web.tar.gz"
