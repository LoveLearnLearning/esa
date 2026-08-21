#!/usr/bin/env bash
# Read-only host/Slurm verification for the personal knowledge-base deployment.

set -u

personal_root="${PERSONAL_KB_ROOT:-/persist_data/home/chenxuzhao/esa-personal-knowledge-base}"
snapshot_root="${PERSONAL_KB_SNAPSHOT_ROOT:-${personal_root}/qdrant-snapshots}"
database_path="${USER_DB_PATH:-}"
qdrant_url="${RAG_QDRANT_BASE_URL:-http://127.0.0.1:6333}"
shared_node="${ESA_SHARED_COMPUTE_NODE:-false}"
failures=0

report_command() {
    label="$1"
    shift
    echo "[$label]"
    "$@" 2>&1 || failures=$((failures + 1))
}

check_path_access() {
    label="$1"
    path="$2"
    echo "[$label] path=$path"
    if [ ! -e "$path" ]; then
        echo "MISSING"
        failures=$((failures + 1))
        return
    fi
    [ -d "$path" ] && echo "directory=yes" || echo "directory=no"
    [ -r "$path" ] && echo "readable=yes" || { echo "readable=no"; failures=$((failures + 1)); }
    [ -w "$path" ] && echo "writable=yes" || { echo "writable=no"; failures=$((failures + 1)); }
    stat -c 'owner=%U uid=%u group=%G gid=%g mode=%a type=%F' "$path"
}

echo "personal-kb host verification (read-only)"
echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "hostname=$(hostname) uid=$(id -u) user=$(id -un) slurm_job_id=${SLURM_JOB_ID:-unset}"

mount_target="$personal_root"
if [ ! -e "$mount_target" ]; then
    mount_target="$(dirname "$personal_root")"
fi
report_command "mount" findmnt -T "$mount_target" -o TARGET,SOURCE,FSTYPE,OPTIONS
report_command "capacity" df -hT "$mount_target"
check_path_access "personal-root" "$personal_root"
check_path_access "snapshot-root" "$snapshot_root"

if [ -n "$database_path" ]; then
    check_path_access "user-db" "$database_path"
else
    echo "[user-db] USER_DB_PATH is unset; cannot verify cross-Job database location"
    failures=$((failures + 1))
fi

if [ -d "$personal_root" ]; then
    echo "[private-modes]"
    bad_directory="$(find "$personal_root" -xdev -type d ! -perm 0700 -print -quit 2>/dev/null)"
    bad_file="$(find "$personal_root" -xdev -type f ! -perm 0600 -print -quit 2>/dev/null)"
    if [ -n "$bad_directory" ]; then
        echo "directory_mode_violation=$bad_directory"
        failures=$((failures + 1))
    else
        echo "directories_0700=yes"
    fi
    if [ -n "$bad_file" ]; then
        echo "file_mode_violation=$bad_file"
        failures=$((failures + 1))
    else
        echo "files_0600=yes"
    fi
    foreign_owner="$(find "$personal_root" -xdev ! -uid "$(id -u)" -print -quit 2>/dev/null)"
    if [ -n "$foreign_owner" ]; then
        echo "owner_violation=$foreign_owner"
        failures=$((failures + 1))
    else
        echo "owner_matches_service_account=yes"
    fi
fi

echo "[qdrant-endpoint] url=$qdrant_url shared_node=$shared_node"
qdrant_port="$(
    QDRANT_URL_VALUE="$qdrant_url" python3 -c \
        'import os, urllib.parse; print(urllib.parse.urlparse(os.environ["QDRANT_URL_VALUE"]).port or 6333)' \
        2>/dev/null
)"
if [ -z "$qdrant_port" ]; then
    echo "qdrant_port_parse=failed"
    failures=$((failures + 1))
else
    echo "qdrant_port=$qdrant_port"
    if [ "$shared_node" = "true" ] && [ "$qdrant_port" = "6333" ]; then
        echo "dynamic_port=no"
        failures=$((failures + 1))
    else
        echo "dynamic_port_policy=yes"
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "sport = :$qdrant_port" 2>&1 || failures=$((failures + 1))
    else
        echo "ss=unavailable"
        failures=$((failures + 1))
    fi
fi

echo "[qdrant-auth]"
if command -v curl >/dev/null 2>&1; then
    unauthenticated_status="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' \
        --max-time 5 "${qdrant_url%/}/collections" 2>/dev/null || true)"
    echo "without_key_http_status=${unauthenticated_status:-request_failed}"
    case "$unauthenticated_status" in
        401|403) ;;
        *) failures=$((failures + 1)) ;;
    esac
    if [ -n "${QDRANT_API_KEY:-}" ]; then
        authenticated_status="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' \
            --max-time 5 -H "api-key: ${QDRANT_API_KEY}" \
            "${qdrant_url%/}/collections" 2>/dev/null || true)"
        echo "with_key_http_status=${authenticated_status:-request_failed}"
        [ "$authenticated_status" = "200" ] || failures=$((failures + 1))
    else
        echo "with_key_http_status=not_checked_key_unset"
        failures=$((failures + 1))
    fi
else
    echo "curl=unavailable"
    failures=$((failures + 1))
fi

echo "[qdrant-processes]"
pgrep -a -u "$(id -u)" qdrant 2>&1 || {
    echo "owned_qdrant_process=not_found"
    failures=$((failures + 1))
}

if [ "$failures" -eq 0 ]; then
    echo "RESULT=PASS"
    exit 0
fi
echo "RESULT=FAIL failures=$failures"
exit 1
