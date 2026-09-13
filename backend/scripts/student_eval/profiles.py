from __future__ import annotations
import argparse
import random
from .common import config, dump_json, run_dir

LEVEL_COUNTS = {
    "weak": {"weak": 3, "partial": 2, "mastered": 1},
    "medium": {"weak": 2, "partial": 2, "mastered": 2},
    "strong": {"weak": 1, "partial": 2, "mastered": 3},
}

MISCONCEPTIONS = {
    "线性表": "把逻辑上的线性关系误认为物理存储必须连续。",
    "栈": "把栈误认为先进先出的队列。",
    "队列": "把队列误认为后进先出的栈。",
    "图": "认为一个图必须整体连通。",
    "深度优先搜索": "误认为 DFS 能保证无权图最短路径。",
    "广度优先搜索": "不知道 BFS 依赖队列并可保证无权图最少边数路径。",
}

def build_profiles(seed: int = 20260913) -> list[dict]:
    cfg = config()
    kps = list(cfg["knowledge_points"])
    rng = random.Random(seed)
    profiles = []
    idx = 1
    for group, count in cfg["diagnosis"]["groups"].items():
        counts = LEVEL_COUNTS[group]
        for _ in range(count):
            shuffled = kps[:]
            rng.shuffle(shuffled)
            state = {}
            cursor = 0
            for level in ("weak", "partial", "mastered"):
                for kp in shuffled[cursor: cursor + counts[level]]:
                    entry = {"level": level}
                    if level == "weak":
                        entry["misconception"] = MISCONCEPTIONS[kp]
                    state[kp] = entry
                cursor += counts[level]
            weak_kps = [kp for kp in kps if state[kp]["level"] == "weak"]
            profiles.append({
                "student_id": f"S{idx:03d}",
                "ability_group": group,
                "knowledge_state": state,
                "ground_truth_weak_kps": weak_kps,
            })
            idx += 1
    return profiles

def ensure_profiles(run_id: str, seed: int = 20260913) -> list[dict]:
    path = run_dir(run_id) / "profiles.json"
    if path.exists():
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    profiles = build_profiles(seed)
    dump_json(path, profiles)
    return profiles

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, default=20260913)
    args = ap.parse_args()
    profiles = ensure_profiles(args.run_id, args.seed)
    print(f"wrote {len(profiles)} profiles -> {run_dir(args.run_id) / 'profiles.json'}")

if __name__ == "__main__":
    main()
