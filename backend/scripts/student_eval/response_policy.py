from __future__ import annotations
import hashlib

def _partial_correct(student_id: str, question_id: str, seed: int) -> bool:
    raw = f"{seed}:{student_id}:{question_id}".encode()
    # For each KP, caller passes question index. We still make deterministic per question.
    return int(hashlib.sha256(raw).hexdigest()[:8], 16) % 2 == 0

def target_answer(profile: dict, question: dict, *, question_index_for_kp: int, seed: int) -> dict:
    kp = question["kp_id"]
    state = profile["knowledge_state"][kp]
    level = state["level"]

    if level == "mastered":
        correct = True
    elif level == "weak":
        correct = False
    else:
        # Guarantee exactly 1/2 for partial instead of trusting random chance.
        correct = (question_index_for_kp == (int(hashlib.sha256(
            f"{seed}:{profile['student_id']}:{kp}".encode()
        ).hexdigest()[:2], 16) % 2))

    answer = question["correct_answer"] if correct else question["misconception_answer"]
    misconception = None if correct else (
        state.get("misconception") or question.get("misconception")
    )
    return {
        "answer": answer,
        "correct": correct,
        "level": level,
        "misconception": misconception,
    }
