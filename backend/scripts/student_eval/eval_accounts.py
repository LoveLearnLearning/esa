from __future__ import annotations
import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.kg_loader import ensure_knowledge_graph_seeded
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.memories.paths import (
    USER_DB_PATH, KNOWLEDGE_GRAPH_DB_PATH, MASTERY_DB_PATH, LEARNING_EVIDENCE_DB_PATH,
)
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord

from .common import config, dump_json, questions, run_dir
from .profiles import ensure_profiles
from .response_policy import target_answer

def selected_profiles(run_id: str) -> list[dict]:
    profiles = ensure_profiles(run_id)
    per_group = config()["ablation"]["per_group"]
    out = []
    for group in ("weak", "medium", "strong"):
        out.extend([p for p in profiles if p["ability_group"] == group][:per_group])
    return out

def _create_user_and_session(user_store: UserStore, session_store: SessionStore, username: str):
    user_id = uuid4().hex
    ok = user_store.create(UserRecord(
        id=user_id, username=username, password_hash="evaluation-no-login",
        status="active", account_role="student", display_name=username,
        major="cs", grade="本科生",
    ))
    if not ok:
        raise RuntimeError(f"user already exists: {username}; cleanup previous run first")
    now = datetime.now(timezone.utc)
    sid = "eval_" + uuid4().hex
    session_store.create(SessionPrincipal(
        session_id=sid, user_id=user_id, issued_at=now, expires_at=now + timedelta(hours=8)
    ))
    return user_id, sid

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, default=20260913)
    args = ap.parse_args()

    cfg = config()
    profiles = selected_profiles(args.run_id)
    qlist = questions()
    prefix = f"eval26_{args.run_id}_"

    user_store = UserStore(USER_DB_PATH)
    session_store = SessionStore(USER_DB_PATH)
    kg = KnowledgeGraphStore(KNOWLEDGE_GRAPH_DB_PATH)
    ensure_knowledge_graph_seeded(kg)
    mastery = MasteryStore(MASTERY_DB_PATH)
    evidence = LearningEvidenceStore(LEARNING_EVIDENCE_DB_PATH)
    service = LearningStateService(kg_store=kg, mastery_store=mastery, evidence_store=evidence)

    accounts = []
    for profile in profiles:
        sid = profile["student_id"].lower()
        full_name = f"{prefix}full_{sid}"
        base_name = f"{prefix}base_{sid}"
        full_uid, full_session = _create_user_and_session(user_store, session_store, full_name)
        base_uid, base_session = _create_user_and_session(user_store, session_store, base_name)

        kp_seen = {kp: 0 for kp in cfg["knowledge_points"]}
        for q in qlist:
            kp = q["kp_id"]
            qidx = kp_seen[kp]; kp_seen[kp] += 1
            target = target_answer(profile, q, question_index_for_kp=qidx, seed=args.seed)
            service.record_event(
                user_name=full_name, kp_id=kp, activity_type="practice",
                correct=target["correct"], evidence_reliability=1.0,
                hint_level=0, attempts=1, independent=True,
                error_type=None if target["correct"] else "conceptual",
                misconception=target["misconception"],
                idempotency_key=f"{args.run_id}:{profile['student_id']}:{q['question_id']}",
            )

        target_kp = profile["ground_truth_weak_kps"][0]
        accounts.append({
            "student_id": profile["student_id"],
            "ability_group": profile["ability_group"],
            "target_kp": target_kp,
            "hidden_profile": profile,
            "full": {"username": full_name, "user_id": full_uid, "session_id": full_session},
            "baseline": {"username": base_name, "user_id": base_uid, "session_id": base_session},
        })

    dump_json(run_dir(args.run_id) / "ablation_accounts.json", {
        "run_id": args.run_id, "prefix": prefix, "accounts": accounts
    })
    print(f"prepared {len(accounts)} paired students ({len(accounts)*2} eval accounts)")
    print("IMPORTANT: run cleanup_eval_data.py after the ablation.")

if __name__ == "__main__":
    main()
