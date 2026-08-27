"""Run the metadata projection replay and write a JSON benchmark report."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# Make the repository-local production estimator importable when this file is
# executed directly (Python otherwise sets sys.path[0] to ``rag/try``).
ROOT = HERE.parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projector import project_for_model  # noqa: E402
from router import Profile, RuleBasedRouter  # noqa: E402
from serializer import json_compact, text_compact, token_count  # noqa: E402


QUERIES = (
    "黑盒测试和白盒测试有什么区别？",
    "这个结论来自哪份文档？",
    "这段内容在哪一页？",
    "不用告诉我出处，直接解释黑盒测试和白盒测试的区别。",
    "把这个 chunk 的检索 score 和完整 metadata 给我。",
)

ROUTER_EVAL = (
    ("它来自哪本书？", Profile.SOURCE),  # intentionally uncovered keyword: bad case
    ("这个观点最早是谁提出的？", Profile.SOURCE),
)


def load_fixture() -> dict:
    with (HERE / "fixtures" / "sample_result.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def benchmark(fixture: dict, query: str, profile: Profile) -> dict:
    projected = project_for_model(fixture, profile)
    # This is the current v2 model projection baseline.  A deliberately naive
    # all-channel count is also reported to expose accidental stringify leaks.
    baseline = fixture["model_content"]
    all_channels = fixture
    model = projected["model_content"]
    baseline_tokens = token_count(baseline)
    projected_tokens = token_count(model)
    all_channel_tokens = token_count(all_channels)
    compact_tokens = token_count(text_compact(model["results"]))
    return {
        "query": query,
        "profile": profile.value,
        "baseline_tokens": baseline_tokens,
        "projected_tokens": projected_tokens,
        "saved_tokens": baseline_tokens - projected_tokens,
        "saving_ratio": round((baseline_tokens - projected_tokens) / baseline_tokens, 4) if baseline_tokens else 0.0,
        "naive_all_channel_tokens": all_channel_tokens,
        "all_channel_saved_vs_projected": all_channel_tokens - projected_tokens,
        "compact_text_tokens": compact_tokens,
        "ref_count": len(projected["audit_metadata"]["ref_registry"]),
        "audit_preserved": projected["audit_metadata"]["full_retrieval"] == fixture,
    }


def main() -> None:
    fixture = load_fixture()
    router = RuleBasedRouter()
    cases = []
    bad_cases = []
    expected = {
        QUERIES[0]: Profile.MINIMAL,
        QUERIES[1]: Profile.SOURCE,
        QUERIES[2]: Profile.LOCATION,
        QUERIES[3]: Profile.MINIMAL,
        QUERIES[4]: Profile.FULL,
    }
    for query in QUERIES:
        decision = router.route(query)
        row = benchmark(fixture, query, decision.profile)
        row["need_provenance"] = decision.need_provenance
        row["reason"] = decision.reason
        row["expected_profile"] = expected[query].value
        row["correct"] = decision.profile is expected[query]
        cases.append(row)
        if not row["correct"]:
            bad_cases.append({"query": query, "predicted": decision.profile.value, "expected": expected[query].value, "reason": decision.reason})
    for query, expected_profile in ROUTER_EVAL:
        decision = router.route(query)
        if decision.profile is not expected_profile:
            bad_cases.append({"query": query, "predicted": decision.profile.value, "expected": expected_profile.value, "reason": "router_rule_gap"})

    # Keep a literal before/after example for reviewers and future dataset work.
    before = copy.deepcopy(fixture["model_content"])
    after = project_for_model(fixture, Profile.MINIMAL)["model_content"]
    report = {
        "fixture": "fixtures/sample_result.json",
        "token_counter": "backend.core.utils.token_estimation.estimate_tokens when importable; local approximation otherwise",
        "cases": cases,
        "bad_cases": bad_cases,
        "router_eval": [
            {"query": query, "predicted": router.route(query).profile.value, "expected": expected_profile.value}
            for query, expected_profile in ROUTER_EVAL
        ],
        "before_after": {"before": before, "after_minimal": after},
        "ref_registry": project_for_model(fixture, Profile.LOCATION)["audit_metadata"]["ref_registry"],
    }
    out = HERE / "results" / "benchmark.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "cases": cases, "bad_cases": bad_cases}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
