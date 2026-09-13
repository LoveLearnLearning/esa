from __future__ import annotations
import argparse
import json
import tempfile
from pathlib import Path

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.kg_loader import load_into_store
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore

from .common import config, dump_json, questions, run_dir, sha256_json
from .profiles import ensure_profiles
from .response_policy import target_answer

def prf(gt: set[str], pred: set[str]) -> tuple[int, int, int]:
    return len(gt & pred), len(pred - gt), len(gt - pred)

def aggregate(rows: list[dict]) -> dict:
    def one(items: list[dict]) -> dict:
        tp = fp = fn = exact = 0
        for row in items:
            a, b, c = prf(set(row["ground_truth_weak_kps"]), set(row["esa_predicted_weak_kps"]))
            tp += a; fp += b; fn += c
            exact += int(set(row["ground_truth_weak_kps"]) == set(row["esa_predicted_weak_kps"]))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "n_students": len(items),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "exact_set_match_rate": round(exact / len(items), 4) if items else 0.0,
        }
    result = {"overall": one(rows)}
    for group in ("weak", "medium", "strong"):
        result[group] = one([r for r in rows if r["ability_group"] == group])
    return result

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--students", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20260913)
    args = ap.parse_args()

    cfg = config()
    qlist = questions()
    profiles = ensure_profiles(args.run_id, args.seed)[:args.students]
    out = run_dir(args.run_id)
    raw_path = out / "diagnosis_raw.jsonl"
    if raw_path.exists():
        raw_path.unlink()

    with tempfile.TemporaryDirectory(prefix="esa_student_eval_") as td:
        td = Path(td)
        kg = KnowledgeGraphStore(td / "knowledge_graph.db")
        load_into_store(kg)
        mastery = MasteryStore(td / "mastery.db")
        evidence = LearningEvidenceStore(td / "learning_evidence.db")
        service = LearningStateService(kg_store=kg, mastery_store=mastery, evidence_store=evidence)

        selected_kps = cfg["knowledge_points"]
        missing = [kp for kp in selected_kps if kg.resolve_kp_id(kp) is None]
        if missing:
            raise RuntimeError(f"selected KPs missing from real KG: {missing}")

        rows = []
        for profile in profiles:
            username = f"diag_{args.run_id}_{profile['student_id']}"
            kp_seen = {kp: 0 for kp in selected_kps}
            qrows = []
            for q in qlist:
                kp = q["kp_id"]
                qidx = kp_seen[kp]
                kp_seen[kp] += 1
                target = target_answer(profile, q, question_index_for_kp=qidx, seed=args.seed)
                event = service.record_event(
                    user_name=username,
                    kp_id=kp,
                    activity_type=cfg["diagnosis"]["activity_type"],
                    correct=target["correct"],
                    evidence_reliability=cfg["diagnosis"]["evidence_reliability"],
                    hint_level=cfg["diagnosis"]["hint_level"],
                    attempts=cfg["diagnosis"]["attempts"],
                    independent=cfg["diagnosis"]["independent"],
                    error_type=None if target["correct"] else "conceptual",
                    misconception=target["misconception"],
                    idempotency_key=f"{args.run_id}:{profile['student_id']}:{q['question_id']}",
                )
                qrows.append({
                    "question_id": q["question_id"],
                    "kp_id": kp,
                    "target_answer": target["answer"],
                    "correct": target["correct"],
                    "hidden_level": target["level"],
                    "misconception": target["misconception"],
                    "state_after": event["state"],
                })
            states = {kp: mastery.get_state(username, kp) for kp in selected_kps}
            predicted = [kp for kp, s in states.items() if s.get("status") == "weak"]
            row = {
                "student_id": profile["student_id"],
                "ability_group": profile["ability_group"],
                "ground_truth_weak_kps": profile["ground_truth_weak_kps"],
                "esa_predicted_weak_kps": predicted,
                "esa_states": states,
                "questions": qrows,
            }
            rows.append(row)
            with raw_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    metrics = aggregate(rows)
    dump_json(out / "diagnosis_metrics.json", metrics)
    dump_json(out / "manifest_diagnosis.json", {
        "run_id": args.run_id,
        "seed": args.seed,
        "students": len(rows),
        "knowledge_points": cfg["knowledge_points"],
        "profiles_sha256": sha256_json(profiles),
        "questions_sha256": sha256_json(qlist),
        "resource_mode": "CPU-only; temporary SQLite; zero ESA model calls",
    })
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
