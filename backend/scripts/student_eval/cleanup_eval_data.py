from __future__ import annotations
import argparse
import json
import sqlite3

from backend.agent.memories.paths import USER_DB_PATH, MASTERY_DB_PATH, LEARNING_EVIDENCE_DB_PATH
from backend.core.stores.sqlite_connection import connect_sqlite
from .common import run_dir

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    state_path = run_dir(args.run_id) / "ablation_accounts.json"
    if not state_path.exists():
        print("no ablation_accounts.json; nothing to cleanup")
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    prefix = state["prefix"]
    if not args.yes:
        raise SystemExit(f"Refusing cleanup without --yes. Prefix would be: {prefix}")

    # Separate stores: cleanup only the exact evaluation prefix.
    with connect_sqlite(MASTERY_DB_PATH) as c:
        n_mastery = c.execute("DELETE FROM user_mastery WHERE user_name LIKE ?", (prefix + "%",)).rowcount
    with connect_sqlite(LEARNING_EVIDENCE_DB_PATH) as c:
        n_evidence = c.execute("DELETE FROM learning_evidence WHERE user_name LIKE ?", (prefix + "%",)).rowcount

    # The main user DB may contain conversations/messages. Resolve IDs first.
    with connect_sqlite(USER_DB_PATH) as c:
        ids = [r["id"] for r in c.execute(
            "SELECT id FROM users WHERE username LIKE ?", (prefix + "%",)
        ).fetchall()]
        n_users = 0
        if ids:
            marks = ",".join("?" for _ in ids)
            # Delete conversations explicitly if table exists; dependent message rows use FK/cascade
            # in the production schema. If a deployment differs, the exception is surfaced rather
            # than broadening deletion scope.
            tables = {r["name"] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "sessions" in tables:
                c.execute(f"DELETE FROM sessions WHERE user_id IN ({marks})", ids)
            if "conversations" in tables:
                c.execute(f"DELETE FROM conversations WHERE user_id IN ({marks})", ids)
            n_users = c.execute(f"DELETE FROM users WHERE id IN ({marks})", ids).rowcount
    print({"prefix": prefix, "mastery_rows": n_mastery, "evidence_rows": n_evidence, "users": n_users})

if __name__ == "__main__":
    main()
