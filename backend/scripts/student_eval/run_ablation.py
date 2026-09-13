from __future__ import annotations
import argparse
import json
import random
import time
from pathlib import Path

from .common import config, dump_json, run_dir
from .http_client import EsaHttp, conversation_id, extract_answer

PROMPT = """我刚才做关于“{kp}”的题一直出错，我还是没太搞懂。
请根据我之前的学习情况来讲，不要只给通用定义：
1. 先判断我最可能卡在哪里；
2. 如果存在更基础的前置薄弱点，先指出并补一下；
3. 再针对当前问题分步讲解；
4. 最后告诉我下一步最应该练什么。
请尽量简洁。"""

def run_one(base_url: str, session_id: str, title: str, prompt: str, knowledge_sources: list[str]):
    client = EsaHttp(base_url, session_id)
    health = client.health()
    conv_resp = client.create_learning_conversation(title)
    cid = conversation_id(conv_resp)
    started = time.time()
    response = client.send(cid, prompt, knowledge_sources)
    elapsed = round(time.time() - started, 3)
    return {
        "health": health,
        "conversation_create_raw": conv_resp,
        "conversation_id": cid,
        "message_raw": response,
        "answer": extract_answer(response),
        "elapsed_seconds": elapsed,
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--cooldown", type=float, default=None)
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    cfg = config()
    out = run_dir(args.run_id)
    account_file = out / "ablation_accounts.json"
    if not account_file.exists():
        raise RuntimeError("run eval_accounts.py first")
    state = json.loads(account_file.read_text(encoding="utf-8"))
    accounts = state["accounts"][:args.limit]
    base_url = args.base_url or cfg["ablation"]["base_url"]
    cooldown = cfg["ablation"]["cooldown_seconds"] if args.cooldown is None else args.cooldown
    knowledge_sources = cfg["ablation"]["knowledge_sources"]

    raw_path = out / "ablation_raw.jsonl"
    if raw_path.exists():
        raw_path.unlink()

    rows = []
    for i, pair in enumerate(accounts, 1):
        prompt = PROMPT.format(kp=pair["target_kp"])
        # Randomize execution order too, but label raw records truthfully.
        conditions = ["full", "baseline"]
        random.Random(f"{args.run_id}:{pair['student_id']}").shuffle(conditions)
        results = {}
        for condition in conditions:
            acc = pair[condition]
            try:
                results[condition] = run_one(
                    base_url, acc["session_id"],
                    f"student-eval-{pair['student_id']}-{condition}",
                    prompt, knowledge_sources
                )
            except Exception as exc:
                results[condition] = {"error": repr(exc), "answer": ""}
            time.sleep(cooldown)

        row = {
            "student_id": pair["student_id"],
            "ability_group": pair["ability_group"],
            "target_kp": pair["target_kp"],
            "hidden_profile": pair["hidden_profile"],
            "prompt": prompt,
            "full": results["full"],
            "baseline": results["baseline"],
        }
        rows.append(row)
        with raw_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(accounts)}] {pair['student_id']} "
              f"full={bool(results['full'].get('answer'))} "
              f"base={bool(results['baseline'].get('answer'))}")

    dump_json(out / "ablation_run_summary.json", {
        "run_id": args.run_id,
        "expected_pairs": len(accounts),
        "completed_full": sum(bool(r["full"].get("answer")) for r in rows),
        "completed_baseline": sum(bool(r["baseline"].get("answer")) for r in rows),
        "esa_calls_attempted": len(accounts) * 2,
        "concurrency": 1,
        "cooldown_seconds": cooldown,
        "base_url": base_url,
    })

if __name__ == "__main__":
    main()
