"""Live personal-only versus global+personal retrieval evaluation.

This command never fabricates a personal corpus.  It requires an existing
ready tenant, a mapping from that tenant's real filenames to canonical source
references, the frozen global deployment, and live Qdrant services.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.agent.memories.paths import USER_DB_PATH
from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.agent.rag.personal import PersonalKnowledgeRetrievalService
from backend.agent.rag.runtime import create_retrieval_service
from backend.core.stores.personal_knowledge_base_store import PersonalKnowledgeBaseStore
from backend.core.utils import config


@dataclass(frozen=True, slots=True)
class RankedSource:
    source_ref: str
    scope: str
    rank: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    values = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"evaluation line {line_number} is not an object")
            values.append(value)
    case_ids = [str(item.get("case_id", "")) for item in values]
    if not values or any(not item for item in case_ids):
        raise ValueError("evaluation cases require non-empty case_id values")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case_id values must be unique")
    for item in values:
        if not str(item.get("query", "")).strip():
            raise ValueError(f"case {item['case_id']} has no query")
        expected = item.get("expected_source_refs")
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"case {item['case_id']} has no expected_source_refs")
    return values


def _load_source_map(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict) or not value:
        raise ValueError("personal source map must be a non-empty JSON object")
    mapping = {str(name).strip(): str(ref).strip() for name, ref in value.items()}
    if any(not name or not ref for name, ref in mapping.items()):
        raise ValueError("personal source map cannot contain blank names or refs")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("each personal filename must map to a distinct source_ref")
    return mapping


def fuse_sources(
    global_sources: Iterable[str],
    personal_sources: Iterable[str],
    *,
    limit: int = 5,
    rrf_k: int = 60,
) -> list[RankedSource]:
    """Fuse source identities while retaining the contributing scope."""

    scores: dict[str, float] = {}
    scopes: dict[str, set[str]] = {}
    for scope, sources in (
        ("global", global_sources),
        ("personal", personal_sources),
    ):
        for rank, source_ref in enumerate(dict.fromkeys(sources), start=1):
            scores[source_ref] = scores.get(source_ref, 0.0) + 1 / (rrf_k + rank)
            scopes.setdefault(source_ref, set()).add(scope)
    ordered = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
    return [
        RankedSource(
            source_ref=source_ref,
            scope="+".join(sorted(scopes[source_ref])),
            rank=rank,
        )
        for rank, source_ref in enumerate(ordered, start=1)
    ]


def retrieval_metrics(
    cases: Iterable[dict[str, Any]],
    rankings: dict[str, list[str]],
    *,
    limit: int = 5,
) -> dict[str, float | int]:
    hits = 0
    reciprocal = 0.0
    ndcg = 0.0
    count = 0
    for case in cases:
        count += 1
        expected = set(case["expected_source_refs"])
        ranking = rankings.get(str(case["case_id"]), [])[:limit]
        relevant_ranks = [
            rank for rank, source in enumerate(ranking, start=1) if source in expected
        ]
        if relevant_ranks:
            hits += 1
            reciprocal += 1 / relevant_ranks[0]
            dcg = sum(1 / math.log2(rank + 1) for rank in relevant_ranks)
            ideal_count = min(len(expected), limit)
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
            ndcg += dcg / ideal
    if count == 0:
        raise ValueError("at least one eligible evaluation case is required")
    return {
        "case_count": count,
        f"hit@{limit}": hits / count,
        "mrr": reciprocal / count,
        f"ndcg@{limit}": ndcg / count,
    }


def _global_sources(response: Any, source_map: dict[str, str]) -> list[str]:
    values = []
    for hit in response.hits:
        if hit.evidence:
            document_id = hit.evidence[0].document_id
            if document_id in source_map:
                values.append(source_map[document_id])
    return values


async def run_live_evaluation(
    *,
    user_id: str,
    database: Path,
    cases_path: Path,
    source_map_path: Path,
    global_source_map_path: Path,
    output: Path,
    top_k: int,
) -> dict[str, Any]:
    cases = _load_jsonl(cases_path)
    source_map = _load_source_map(source_map_path)
    global_source_map = _load_source_map(global_source_map_path)
    store = PersonalKnowledgeBaseStore(database)
    state = store.get_retrieval_state(user_id)
    if not state["collection_ready"] or state["generation_id"] is None:
        raise RuntimeError("personal collection is not ready for live evaluation")
    live_names = set(state["files"].values())
    unknown = sorted(set(source_map) - live_names)
    if unknown:
        raise RuntimeError(
            "source map contains filenames absent from the live tenant: "
            + ", ".join(unknown)
        )
    eligible = [
        case
        for case in cases
        if set(case["expected_source_refs"]) & set(source_map.values())
    ]
    if not eligible:
        raise RuntimeError("no real cases are covered by the mapped personal corpus")

    global_service = await asyncio.to_thread(
        create_retrieval_service, config.RAG_INDEX_DEPLOYMENT_MANIFEST_PATH
    )
    global_document_ids = set(global_service.collection.document_names)
    missing_global = sorted(global_document_ids - set(global_source_map))
    if missing_global:
        raise RuntimeError(
            "global source map is missing live document IDs: "
            + ", ".join(missing_global)
        )
    personal_index = PersonalQdrantIndex(
        base_url=config.RAG_QDRANT_BASE_URL,
        collection=config.PERSONAL_KB_QDRANT_COLLECTION,
        api_key=os.environ.get("QDRANT_API_KEY"),
        timeout=config.RAG_QDRANT_TIMEOUT,
        upsert_batch_size=config.RAG_QDRANT_UPSERT_BATCH_SIZE,
    )
    personal_service = PersonalKnowledgeRetrievalService(
        store=store,
        index=personal_index,
        embedding=global_service.embedding,
        embedding_semaphore=asyncio.Semaphore(
            config.PERSONAL_KB_EMBEDDING_CONCURRENCY
        ),
    )
    personal_rankings: dict[str, list[str]] = {}
    federated_rankings: dict[str, list[str]] = {}
    rows = []
    for case in eligible:
        case_id = str(case["case_id"])
        query = str(case["query"])
        global_response, personal_response = await asyncio.gather(
            asyncio.to_thread(global_service.search, query),
            personal_service.search(user_id=user_id, query=query, top_k=top_k),
        )
        global_sources = _global_sources(global_response, global_source_map)[:top_k]
        personal_sources = [
            source_map[result["source"]]
            for result in personal_response["results"]
            if result["source"] in source_map
        ][:top_k]
        fused = fuse_sources(global_sources, personal_sources, limit=top_k)
        personal_rankings[case_id] = personal_sources
        federated_rankings[case_id] = [item.source_ref for item in fused]
        rows.append(
            {
                "case_id": case_id,
                "expected_source_refs": case["expected_source_refs"],
                "personal": personal_sources,
                "global": global_sources,
                "federated": [asdict(item) for item in fused],
                "personal_degraded": personal_response["degraded"],
                "global_degraded": list(global_response.trace.degraded),
            }
        )

    personal_metrics = retrieval_metrics(eligible, personal_rankings, limit=top_k)
    federated_metrics = retrieval_metrics(eligible, federated_rankings, limit=top_k)
    hit_key = f"hit@{top_k}"
    hit_delta = float(federated_metrics[hit_key]) - float(personal_metrics[hit_key])
    mrr_delta = float(federated_metrics["mrr"]) - float(personal_metrics["mrr"])
    recommendation = (
        "candidate_for_merged_tool"
        if hit_delta >= 0.02 and mrr_delta >= -0.01
        else "keep_tools_separate"
    )
    report = {
        "schema_version": "personal-federation-live-eval-0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "case_file_sha256": _sha256(cases_path),
        "source_map_sha256": _sha256(source_map_path),
        "global_source_map_sha256": _sha256(global_source_map_path),
        "database_path": str(database.resolve()),
        "global_deployment": str(config.RAG_INDEX_DEPLOYMENT_MANIFEST_PATH),
        "personal_collection": config.PERSONAL_KB_QDRANT_COLLECTION,
        "personal_generation_id": state["generation_id"],
        "top_k": top_k,
        "eligible_case_count": len(eligible),
        "personal_only": personal_metrics,
        "federated": federated_metrics,
        "delta": {hit_key: hit_delta, "mrr": mrr_delta},
        "recommendation": recommendation,
        "recommendation_rule": (
            f"candidate only if federated {hit_key} delta >= 0.02 and MRR delta >= -0.01"
        ),
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_name(f".{output.name}.partial")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-federation-eval")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--database", type=Path, default=USER_DB_PATH)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--personal-source-map", type=Path, required=True)
    parser.add_argument("--global-source-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 21))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = asyncio.run(
        run_live_evaluation(
            user_id=args.user_id,
            database=args.database,
            cases_path=args.cases,
            source_map_path=args.personal_source_map,
            global_source_map_path=args.global_source_map,
            output=args.output,
            top_k=args.top_k,
        )
    )
    print(json.dumps({key: report[key] for key in ("eligible_case_count", "personal_only", "federated", "delta", "recommendation")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
