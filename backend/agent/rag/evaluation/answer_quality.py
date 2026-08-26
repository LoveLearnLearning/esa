"""Answer-centric retrieval judgments and metrics.

Source-specific gold remains useful for provenance diagnostics, but the primary
metrics in this module ask whether retrieved chunks contain enough evidence to
answer the question.  Rankings with unjudged Top-K chunks fail closed by
default, so a newly expanded candidate pool cannot silently turn into false
negatives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class AnswerFacet:
    """One independently checkable fact required by the reference answer."""

    facet_id: str
    description: str

    def __post_init__(self) -> None:
        if not self.facet_id.strip() or not self.description.strip():
            raise ValueError("answer facets require a non-empty ID and description")


@dataclass(frozen=True)
class EvidenceJudgment:
    """Human-auditable relevance judgment for one concrete Chunk."""

    chunk_id: str
    relevance: int
    covered_facet_ids: frozenset[str]
    rationale: str

    def __post_init__(self) -> None:
        if not self.chunk_id.strip() or not self.rationale.strip():
            raise ValueError("evidence judgments require a Chunk ID and rationale")
        if self.relevance not in (0, 1, 2, 3):
            raise ValueError("evidence relevance must be 0, 1, 2, or 3")
        if self.relevance < 2 and self.covered_facet_ids:
            raise ValueError("non-answer-bearing evidence cannot cover answer facets")
        if self.relevance >= 2 and not self.covered_facet_ids:
            raise ValueError("answer-bearing evidence must cover at least one facet")


@dataclass(frozen=True)
class AnswerQualityCase:
    """A question, reference answer facets, source gold, and pooled judgments."""

    case_id: str
    query: str
    reference_answer: str
    facets: tuple[AnswerFacet, ...]
    source_gold_document_ids: frozenset[str]
    judgments: tuple[EvidenceJudgment, ...]
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.query.strip():
            raise ValueError("answer-quality cases require an ID and query")
        if not self.reference_answer.strip():
            raise ValueError("answer-quality cases require a reference answer")
        facet_ids = [facet.facet_id for facet in self.facets]
        if not facet_ids or len(facet_ids) != len(set(facet_ids)):
            raise ValueError("answer facet IDs must be non-empty and unique")
        if not self.source_gold_document_ids:
            raise ValueError("source diagnostics require at least one gold document")
        chunk_ids = [judgment.chunk_id for judgment in self.judgments]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("each Chunk may have only one evidence judgment per case")
        allowed_facets = set(facet_ids)
        for judgment in self.judgments:
            unknown = judgment.covered_facet_ids - allowed_facets
            if unknown:
                raise ValueError(
                    f"unknown facets in {self.case_id}/{judgment.chunk_id}: "
                    f"{sorted(unknown)}"
                )
            if judgment.relevance == 3 and judgment.covered_facet_ids != allowed_facets:
                raise ValueError("relevance=3 must cover every required answer facet")

    @property
    def judgments_by_chunk_id(self) -> Mapping[str, EvidenceJudgment]:
        return {judgment.chunk_id: judgment for judgment in self.judgments}


@dataclass(frozen=True)
class AnswerQualityBenchmark:
    """Validated benchmark metadata and cases.

    ``annotation_status`` is deliberately carried into every generated report.
    This prevents model-proposed labels from being mistaken for audited ground
    truth merely because they can be parsed by the evaluator.
    """

    collection_id: str
    annotation_status: str
    annotation: Mapping[str, Any]
    cases: tuple[AnswerQualityCase, ...]


@dataclass(frozen=True)
class AnswerQualityMetrics:
    """Primary answer-evidence metrics plus source-only diagnostics."""

    query_count: int
    judgment_coverage_at_5: float
    direct_answer_hit_at_1: float
    direct_answer_hit_at_3: float
    direct_answer_hit_at_5: float
    answer_bearing_hit_at_1: float
    answer_bearing_hit_at_3: float
    answer_bearing_hit_at_5: float
    answer_mrr_at_5: float
    graded_ndcg_at_5: float
    facet_coverage_at_5: float
    complete_answer_rate_at_5: float
    source_hit_at_1: float
    source_hit_at_3: float
    source_hit_at_5: float


class UnjudgedRankingError(ValueError):
    """Raised when a primary metric would treat an unseen candidate as irrelevant."""


def load_answer_quality_cases(
    path: Path,
    *,
    known_chunk_ids: set[str] | None = None,
    known_document_ids: set[str] | None = None,
    expected_collection_id: str | None = None,
    require_audited: bool = True,
) -> tuple[AnswerQualityCase, ...]:
    """Load benchmark cases, rejecting provisional labels by default."""

    return load_answer_quality_benchmark(
        path,
        known_chunk_ids=known_chunk_ids,
        known_document_ids=known_document_ids,
        expected_collection_id=expected_collection_id,
        require_audited=require_audited,
    ).cases


def load_answer_quality_benchmark(
    path: Path,
    *,
    known_chunk_ids: set[str] | None = None,
    known_document_ids: set[str] | None = None,
    expected_collection_id: str | None = None,
    require_audited: bool = True,
) -> AnswerQualityBenchmark:
    """Load and validate the versioned answer-centric benchmark schema.

    An official report requires a complete audit declaration. Callers may set
    ``require_audited=False`` for label-development runs, but the resulting
    benchmark retains its provisional status and the report exposes it.
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "esa-answer-quality-benchmark-1.0":
        raise ValueError("unsupported answer-quality benchmark schema")
    collection_id = str(raw.get("collection_id", "")).strip()
    if not collection_id:
        raise ValueError("answer-quality benchmark requires a collection_id")
    if expected_collection_id is not None and collection_id != expected_collection_id:
        raise ValueError(
            "benchmark collection_id does not match the frozen candidate pool"
        )
    annotation = raw.get("annotation")
    if not isinstance(annotation, Mapping):
        raise ValueError("answer-quality benchmark requires annotation metadata")
    annotation_status = str(annotation.get("status", "")).strip()
    if not annotation_status:
        raise ValueError("answer-quality benchmark requires annotation.status")
    cases = tuple(_case_from_json(item) for item in raw.get("cases", ()))
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("benchmark case IDs must be non-empty and unique")
    if require_audited:
        _validate_audit_declaration(annotation, cases)
    if known_chunk_ids is not None:
        unknown_chunks = {
            judgment.chunk_id
            for case in cases
            for judgment in case.judgments
            if judgment.chunk_id not in known_chunk_ids
        }
        if unknown_chunks:
            raise ValueError(f"unknown judged Chunk IDs: {sorted(unknown_chunks)}")
    if known_document_ids is not None:
        unknown_documents = {
            document_id
            for case in cases
            for document_id in case.source_gold_document_ids
            if document_id not in known_document_ids
        }
        if unknown_documents:
            raise ValueError(
                f"unknown source gold document IDs: {sorted(unknown_documents)}"
            )
    return AnswerQualityBenchmark(
        collection_id=collection_id,
        annotation_status=annotation_status,
        annotation=dict(annotation),
        cases=cases,
    )


def _validate_audit_declaration(
    annotation: Mapping[str, Any],
    cases: Sequence[AnswerQualityCase],
) -> None:
    if annotation.get("status") != "audited":
        raise ValueError(
            "official answer-quality metrics require annotation.status='audited'; "
            "use require_audited=False only for explicitly provisional analysis"
        )
    missing = [
        field
        for field in ("reviewer", "reviewed_at", "rubric_version")
        if not str(annotation.get(field, "")).strip()
    ]
    if missing:
        raise ValueError(f"audited annotation metadata is missing: {missing}")
    judgment_count = sum(len(case.judgments) for case in cases)
    if annotation.get("audited_case_count") != len(cases):
        raise ValueError("audited_case_count does not match benchmark cases")
    if annotation.get("audited_judgment_count") != judgment_count:
        raise ValueError("audited_judgment_count does not match benchmark judgments")


def _case_from_json(item: Mapping[str, Any]) -> AnswerQualityCase:
    facets = tuple(
        AnswerFacet(str(value["facet_id"]), str(value["description"]))
        for value in item.get("facets", ())
    )
    judgments = tuple(
        EvidenceJudgment(
            chunk_id=str(value["chunk_id"]),
            relevance=int(value["relevance"]),
            covered_facet_ids=frozenset(
                str(facet_id) for facet_id in value.get("covered_facet_ids", ())
            ),
            rationale=str(value["rationale"]),
        )
        for value in item.get("judgments", ())
    )
    return AnswerQualityCase(
        case_id=str(item.get("case_id", "")),
        query=str(item.get("query", "")),
        reference_answer=str(item.get("reference_answer", "")),
        facets=facets,
        source_gold_document_ids=frozenset(
            str(value) for value in item.get("source_gold_document_ids", ())
        ),
        judgments=judgments,
        tags=tuple(str(value) for value in item.get("tags", ())),
    )


def evaluate_answer_quality(
    cases: Sequence[AnswerQualityCase],
    rankings: Mapping[str, Sequence[str]],
    chunk_document_ids: Mapping[str, str],
    *,
    strict: bool = True,
) -> AnswerQualityMetrics:
    """Evaluate answer-bearing evidence first and source identity second."""

    if not cases:
        raise ValueError("at least one answer-quality case is required")
    if set(rankings) != {case.case_id for case in cases}:
        raise ValueError("ranking case IDs must exactly match benchmark case IDs")

    coverage_values: list[float] = []
    direct_hits = {cutoff: [] for cutoff in (1, 3, 5)}
    answer_hits = {cutoff: [] for cutoff in (1, 3, 5)}
    source_hits = {cutoff: [] for cutoff in (1, 3, 5)}
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    facet_coverages: list[float] = []
    complete_answers: list[float] = []

    for case in cases:
        ranking = list(dict.fromkeys(rankings[case.case_id]))
        top_5 = ranking[:5]
        judgments = case.judgments_by_chunk_id
        judged_count = sum(chunk_id in judgments for chunk_id in top_5)
        coverage = judged_count / len(top_5) if top_5 else 1.0
        coverage_values.append(coverage)
        unjudged = [chunk_id for chunk_id in top_5 if chunk_id not in judgments]
        if strict and unjudged:
            raise UnjudgedRankingError(
                f"unjudged Top-5 chunks in {case.case_id}: {unjudged}"
            )

        relevance = {
            chunk_id: judgments[chunk_id].relevance if chunk_id in judgments else 0
            for chunk_id in top_5
        }
        for cutoff in (1, 3, 5):
            selected = top_5[:cutoff]
            direct_hits[cutoff].append(
                float(any(relevance[chunk_id] == 3 for chunk_id in selected))
            )
            answer_hits[cutoff].append(
                float(any(relevance[chunk_id] >= 2 for chunk_id in selected))
            )
            source_hits[cutoff].append(
                float(
                    any(
                        chunk_document_ids.get(chunk_id)
                        in case.source_gold_document_ids
                        for chunk_id in selected
                    )
                )
            )

        answer_rank = next(
            (
                rank
                for rank, chunk_id in enumerate(top_5, start=1)
                if relevance[chunk_id] >= 2
            ),
            None,
        )
        reciprocal_ranks.append(1.0 / answer_rank if answer_rank else 0.0)
        # A merely topical Chunk (grade 1) is still unable to support an
        # answer. Giving it positive DCG gain would reward plausible-looking
        # context noise, so only partial and complete answer evidence count.
        gains = [_answer_gain(relevance[chunk_id]) for chunk_id in top_5]
        dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, 1))
        ideal_gains = sorted(
            (_answer_gain(judgment.relevance) for judgment in case.judgments),
            reverse=True,
        )[:5]
        ideal = sum(
            gain / math.log2(rank + 1)
            for rank, gain in enumerate(ideal_gains, start=1)
        )
        ndcgs.append(dcg / ideal if ideal else 0.0)

        covered = {
            facet_id
            for chunk_id in top_5
            if chunk_id in judgments and judgments[chunk_id].relevance >= 2
            for facet_id in judgments[chunk_id].covered_facet_ids
        }
        required = {facet.facet_id for facet in case.facets}
        facet_coverages.append(len(covered) / len(required))
        complete_answers.append(float(required <= covered))

    return AnswerQualityMetrics(
        query_count=len(cases),
        judgment_coverage_at_5=mean(coverage_values),
        direct_answer_hit_at_1=mean(direct_hits[1]),
        direct_answer_hit_at_3=mean(direct_hits[3]),
        direct_answer_hit_at_5=mean(direct_hits[5]),
        answer_bearing_hit_at_1=mean(answer_hits[1]),
        answer_bearing_hit_at_3=mean(answer_hits[3]),
        answer_bearing_hit_at_5=mean(answer_hits[5]),
        answer_mrr_at_5=mean(reciprocal_ranks),
        graded_ndcg_at_5=mean(ndcgs),
        facet_coverage_at_5=mean(facet_coverages),
        complete_answer_rate_at_5=mean(complete_answers),
        source_hit_at_1=mean(source_hits[1]),
        source_hit_at_3=mean(source_hits[3]),
        source_hit_at_5=mean(source_hits[5]),
    )


def _answer_gain(relevance: int) -> int:
    return {0: 0, 1: 0, 2: 1, 3: 3}[relevance]


def evaluate_frozen_pool(
    benchmark_path: Path,
    pool_path: Path,
    *,
    require_audited: bool = True,
) -> dict[str, Any]:
    """Replay every profile in a frozen candidate pool against one benchmark."""

    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    if pool.get("schema_version") != "esa-dense-ablation-pool-1.0":
        raise ValueError("unsupported answer-quality candidate-pool schema")
    collection_id = str(pool.get("collection_id", "")).strip()
    chunks = pool.get("chunks")
    profiles = pool.get("profiles")
    raw_cases = pool.get("cases")
    if not collection_id or not isinstance(chunks, Mapping):
        raise ValueError("candidate pool requires collection_id and chunks")
    if not isinstance(profiles, Mapping) or not profiles:
        raise ValueError("candidate pool requires at least one profile")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("candidate pool requires cases")

    benchmark = load_answer_quality_benchmark(
        benchmark_path,
        known_chunk_ids=set(chunks),
        expected_collection_id=collection_id,
        require_audited=require_audited,
    )
    pool_cases: dict[str, Mapping[str, Any]] = {}
    for item in raw_cases:
        if not isinstance(item, Mapping):
            raise ValueError("candidate-pool cases must be objects")
        case_id = str(item.get("case_id", ""))
        if not case_id or case_id in pool_cases:
            raise ValueError("candidate-pool case IDs must be non-empty and unique")
        pool_cases[case_id] = item
    benchmark_case_ids = {case.case_id for case in benchmark.cases}
    if set(pool_cases) != benchmark_case_ids:
        raise ValueError("candidate-pool case IDs must match benchmark case IDs")

    chunk_document_ids = {
        str(chunk_id): str(value["document_id"])
        for chunk_id, value in chunks.items()
        if isinstance(value, Mapping) and value.get("document_id")
    }
    profile_reports: dict[str, Any] = {}
    for profile_name, profile in profiles.items():
        if not isinstance(profile, Mapping):
            raise ValueError(f"profile {profile_name!r} must be an object")
        if profile.get("fusion_method") != "dense":
            raise ValueError(
                f"profile {profile_name!r} enables a non-Dense fusion method"
            )
        rankings: dict[str, list[str]] = {}
        for case_id, item in pool_cases.items():
            raw_rankings = item.get("rankings")
            if not isinstance(raw_rankings, Mapping) or profile_name not in raw_rankings:
                raise ValueError(
                    f"case {case_id!r} is missing profile {profile_name!r}"
                )
            ranking = [str(chunk_id) for chunk_id in raw_rankings[profile_name]]
            unknown = [chunk_id for chunk_id in ranking if chunk_id not in chunks]
            if unknown:
                raise ValueError(
                    f"profile {profile_name!r}/{case_id!r} has unknown chunks: {unknown}"
                )
            rankings[case_id] = ranking
        metrics = evaluate_answer_quality(
            benchmark.cases,
            rankings,
            chunk_document_ids,
            strict=True,
        )
        profile_reports[str(profile_name)] = {
            "configuration": dict(profile),
            "metrics": asdict(metrics),
        }

    official = benchmark.annotation_status == "audited" and require_audited
    return {
        "schema_version": "esa-answer-quality-report-1.0",
        "status": "official" if official else "provisional_not_for_decisions",
        "collection_id": collection_id,
        "benchmark_sha256": _sha256(benchmark_path),
        "pool_sha256": _sha256(pool_path),
        "annotation": dict(benchmark.annotation),
        "metric_roles": {
            "primary": [
                "answer_bearing_hit_at_1",
                "answer_bearing_hit_at_3",
                "answer_bearing_hit_at_5",
                "answer_mrr_at_5",
                "facet_coverage_at_5",
                "complete_answer_rate_at_5",
                "graded_ndcg_at_5",
            ],
            "diagnostic": [
                "direct_answer_hit_at_1",
                "direct_answer_hit_at_3",
                "direct_answer_hit_at_5",
                "source_hit_at_1",
                "source_hit_at_3",
                "source_hit_at_5",
                "judgment_coverage_at_5",
            ],
        },
        "profiles": profile_reports,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate frozen Dense-only retrieval profiles with answer evidence"
    )
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-provisional",
        action="store_true",
        help="allow unaudited labels and mark the report non-decisional",
    )
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    report = evaluate_frozen_pool(
        arguments.benchmark,
        arguments.pool,
        require_audited=not arguments.allow_provisional,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output is None:
        print(payload, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
