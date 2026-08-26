"""Read-only audit and explicit recovery commands for personal knowledge bases."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.agent.memories.paths import USER_DB_PATH
from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.core.services.personal_knowledge_base_service import (
    PersonalKnowledgeBaseFileStorage,
)
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseStore,
)
from backend.core.utils.config import (
    PERSONAL_KB_AUDIT_RETENTION_DAYS,
    PERSONAL_KB_MAX_BATCH_BYTES,
    PERSONAL_KB_MAX_BATCH_FILES,
    PERSONAL_KB_MAX_EXPANDED_BYTES,
    PERSONAL_KB_MAX_FILE_BYTES,
    PERSONAL_KB_MAX_IMAGE_PIXELS,
    PERSONAL_KB_MAX_PAGES,
    PERSONAL_KB_ORPHAN_RETENTION_SECONDS,
    RAG_QDRANT_COLLECTION,
    PERSONAL_KB_ROOT,
    RAG_QDRANT_BASE_URL,
    RAG_QDRANT_TIMEOUT,
    RAG_QDRANT_UPSERT_BATCH_SIZE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-kb")
    parser.add_argument("--database", type=Path, default=USER_DB_PATH)
    subcommands = parser.add_subparsers(dest="command", required=True)
    retry = subcommands.add_parser("retry-job")
    retry.add_argument("--user-id", required=True)
    retry.add_argument("--job-id", required=True)
    cleanup = subcommands.add_parser("retry-generation-cleanup")
    cleanup.add_argument("--user-id", required=True)
    cleanup.add_argument("--generation-id", required=True)
    audit = subcommands.add_parser("audit-user")
    audit.add_argument("--user-id", required=True)
    subcommands.add_parser("cleanup-orphans")
    audit_cleanup = subcommands.add_parser("cleanup-audit")
    audit_cleanup.add_argument(
        "--retention-days", type=int, default=PERSONAL_KB_AUDIT_RETENTION_DAYS
    )
    return parser


def _index() -> PersonalQdrantIndex:
    return PersonalQdrantIndex(
        base_url=RAG_QDRANT_BASE_URL,
        collection=RAG_QDRANT_COLLECTION,
        api_key=os.environ.get("QDRANT_API_KEY"),
        timeout=RAG_QDRANT_TIMEOUT,
        upsert_batch_size=RAG_QDRANT_UPSERT_BATCH_SIZE,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = PersonalKnowledgeBaseStore(args.database)
    if args.command == "retry-job":
        changed = store.retry_failed_job(user_id=args.user_id, job_id=args.job_id)
        print(json.dumps({"requeued": changed, "job_id": args.job_id}))
        return 0 if changed else 2
    if args.command == "retry-generation-cleanup":
        job_id = store.retry_failed_generation_cleanup(
            user_id=args.user_id,
            generation_id=args.generation_id,
        )
        print(json.dumps({"requeued": job_id is not None, "job_id": job_id}))
        return 0 if job_id is not None else 2
    if args.command == "audit-user":
        snapshot = store.get_snapshot(args.user_id)
        retrieval = store.get_retrieval_state(args.user_id)
        generation_id = retrieval["generation_id"]
        qdrant_count = None
        if generation_id is not None and retrieval["collection_ready"]:
            qdrant_count = _index().count(
                user_id=args.user_id,
                generation_id=generation_id,
                visible=True,
            )
        print(
            json.dumps(
                {
                    "user_id": args.user_id,
                    "file_count": snapshot["file_count"],
                    "sqlite_chunk_count": snapshot["chunk_count"],
                    "sqlite_index_count": snapshot["index_count"],
                    "active_generation_id": generation_id,
                    "qdrant_visible_count": qdrant_count,
                    "consistent": (
                        qdrant_count is None
                        or qdrant_count == snapshot["index_count"]
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "cleanup-audit":
        if args.retention_days <= 0:
            raise SystemExit("--retention-days must be positive")
        boundary = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
        removed = store.cleanup_audit_records(
            completed_before=boundary.isoformat()
        )
        print(json.dumps(removed, sort_keys=True))
        return 0
    storage = PersonalKnowledgeBaseFileStorage(
        PERSONAL_KB_ROOT,
        max_file_bytes=PERSONAL_KB_MAX_FILE_BYTES,
        max_batch_files=PERSONAL_KB_MAX_BATCH_FILES,
        max_batch_bytes=PERSONAL_KB_MAX_BATCH_BYTES,
        max_expanded_bytes=PERSONAL_KB_MAX_EXPANDED_BYTES,
        max_pages=PERSONAL_KB_MAX_PAGES,
        max_image_pixels=PERSONAL_KB_MAX_IMAGE_PIXELS,
    )
    removed = storage.cleanup_orphans(
        retained_file_ids=store.list_retained_file_ids(),
        retention_seconds=PERSONAL_KB_ORPHAN_RETENTION_SECONDS,
    )
    print(json.dumps(removed, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
