#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
frontend_dir="$(cd "$script_dir/.." && pwd)"
repo_dir="$(cd "$frontend_dir/.." && pwd)"

cd "$frontend_dir"
flutter build web \
  --release \
  --pwa-strategy=none \
  --base-href=/esa/ \
  --dart-define=ESA_API_BASE=/api

# `--pwa-strategy=none` leaves a zero-byte compatibility worker. That is not
# enough to retire a previously installed Flutter cache worker: the old worker
# can remain active and keep serving an earlier blue-themed release. Replace it
# with a skipWaiting, cache-clearing, network-only worker so existing tabs move
# to the new release immediately.
cp web/esa_cleanup_service_worker.js build/web/flutter_service_worker.js

# Stable Flutter filenames are easily retained by an older browser or a
# previously installed Flutter service worker. Attach content hashes to the
# two entrypoint requests so every release necessarily loads its new bundle.
main_hash="$(shasum -a 256 build/web/main.dart.js | awk '{print substr($1, 1, 16)}')"
perl -0pi -e \
  "s/\"mainJsPath\":\"main\\.dart\\.js\"/\"mainJsPath\":\"main.dart.js?v=$main_hash\"/g" \
  build/web/flutter_bootstrap.js
bootstrap_hash="$(shasum -a 256 build/web/flutter_bootstrap.js | awk '{print substr($1, 1, 16)}')"
perl -0pi -e \
  "s#href=\"main\\.dart\\.js(?:\\?[^\"]*)?\"#href=\"main.dart.js?v=$main_hash\"#g; s#src=\"flutter_bootstrap\\.js(?:\\?[^\"]*)?\"#src=\"flutter_bootstrap.js?v=$bootstrap_hash\"#g" \
  build/web/index.html

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
