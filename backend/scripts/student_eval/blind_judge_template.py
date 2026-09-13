"""Prepare blinded A/B material. Scoring can be filled by an external LLM API
or by the coding agent itself. No local model is started.
"""
from __future__ import annotations
import argparse
import json
import random
from .common import dump_json, read_jsonl, run_dir

RUBRIC = {
    "targeting": "薄弱点针对性 0-2",
    "prerequisite": "前置知识处理 0-2",
    "difficulty": "难度匹配 0-2",
    "scaffolding": "教学脚手架 0-2",
    "redundancy": "冗余控制 0-2",
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    out = run_dir(args.run_id)
    rows = read_jsonl(out / "ablation_raw.jsonl")
    blinded = []
    key = {}
    for row in rows:
        order = ["full", "baseline"]
        random.Random(f"judge:{args.run_id}:{row['student_id']}").shuffle(order)
        a, b = order
        blinded.append({
            "student_id": row["student_id"],
            "ability_group": row["ability_group"],
            "target_kp": row["target_kp"],
            "hidden_profile": row["hidden_profile"],
            "prompt": row["prompt"],
            "response_a": row[a].get("answer", ""),
            "response_b": row[b].get("answer", ""),
            "rubric": RUBRIC,
            "required_output": {
                "response_a": {"targeting":0,"prerequisite":0,"difficulty":0,"scaffolding":0,"redundancy":0,"total":0},
                "response_b": {"targeting":0,"prerequisite":0,"difficulty":0,"scaffolding":0,"redundancy":0,"total":0},
                "winner": "A|B|tie",
                "reason": "brief reason"
            }
        })
        key[row["student_id"]] = {"A": a, "B": b}
    dump_json(out / "judge_blinded_input.json", blinded)
    dump_json(out / "judge_blind_key.json", key)
    print(f"prepared {len(blinded)} blind pairs")
    print("Have the execution AI or an EXTERNAL model fill judge_blinded_results.json.")
    print("Do not open judge_blind_key.json until scoring is frozen.")

if __name__ == "__main__":
    main()
