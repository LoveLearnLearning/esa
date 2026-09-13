from __future__ import annotations
import argparse
import json
import statistics
from .common import dump_json, run_dir

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    out = run_dir(args.run_id)
    results_path = out / "judge_blinded_results.json"
    if not results_path.exists():
        raise RuntimeError(
            "judge_blinded_results.json missing. Fill it from judge_blinded_input.json first."
        )
    judged = json.loads(results_path.read_text(encoding="utf-8"))
    key = json.loads((out / "judge_blind_key.json").read_text(encoding="utf-8"))
    rows = []
    for item in judged:
        sid = item["student_id"]
        mapping = key[sid]
        a_total = item["response_a"]["total"]
        b_total = item["response_b"]["total"]
        full = a_total if mapping["A"] == "full" else b_total
        base = a_total if mapping["A"] == "baseline" else b_total
        rows.append({"student_id": sid, "full": full, "baseline": base, "diff": full-base})
    fulls = [r["full"] for r in rows]
    bases = [r["baseline"] for r in rows]
    diffs = [r["diff"] for r in rows]
    metrics = {
        "n": len(rows),
        "full_mean": round(statistics.mean(fulls), 3) if rows else None,
        "baseline_mean": round(statistics.mean(bases), 3) if rows else None,
        "paired_mean_difference": round(statistics.mean(diffs), 3) if rows else None,
        "full_median": statistics.median(fulls) if rows else None,
        "baseline_median": statistics.median(bases) if rows else None,
        "full_wins": sum(d > 0 for d in diffs),
        "ties": sum(d == 0 for d in diffs),
        "baseline_wins": sum(d < 0 for d in diffs),
        "per_student": rows,
    }
    dump_json(out / "ablation_metrics.json", metrics)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
