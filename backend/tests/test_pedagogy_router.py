# backend/tests/test_pedagogy_router.py

"""验证 `pedagogy_router` 相关行为与回归场景。"""

from backend.agent.learning.pedagogy_router import PedagogyRouter


def test_task_mode_has_highest_intent_priority():
    """验证 `task_mode_has_highest_intent_priority` 场景。"""
    decision = PedagogyRouter.route(
        "任务模式：批改作业。区分题目与学生作答。\n\n用户提供的内容：我的答案是 B"
    )
    assert decision.skill_name == "homework_review"
    assert decision.confidence == 1.0


def test_engineering_request_does_not_force_tutoring():
    """验证 `engineering_request_does_not_force_tutoring` 场景。"""
    decision = PedagogyRouter.route(
        "帮我修 GitHub 仓库里的 CUDA 部署报错，并直接告诉我改哪个文件"
    )
    assert decision.skill_name is None
    assert decision.task_type == "engineering"


def test_stuck_student_routes_to_progressive_hint():
    """验证 `stuck_student_routes_to_progressive_hint` 场景。"""
    decision = PedagogyRouter.route("这道递归题我卡住了，给我提示一下")
    assert decision.skill_name == "progressive_hint"


def test_concept_question_routes_to_retrieve_first():
    """验证 `concept_question_routes_to_retrieve_first` 场景。"""
    decision = PedagogyRouter.route("解释一下为什么二叉树遍历会用到递归")
    assert decision.skill_name == "retrieve_first"


def test_start_practice_routes_to_adaptive_practice():
    """验证 `start_practice_routes_to_adaptive_practice` 场景。"""
    decision = PedagogyRouter.route("给我出一道二叉树遍历的题")
    assert decision.skill_name == "adaptive_practice"
    assert decision.confidence == 0.96


def test_short_answer_uses_pending_practice_from_history():
    """验证 `short_answer_uses_pending_practice_from_history` 场景。"""
    decision = PedagogyRouter.route(
        "B",
        history=[
            {"role": "user", "content": "给我出一道题"},
            {
                "role": "assistant",
                "content": "【练习题｜知识点：二叉树遍历】\n以下哪个顺序是前序遍历？",
            },
        ],
    )
    assert decision.skill_name == "adaptive_practice"
    assert decision.primary_kp_id == "二叉树遍历"
    assert decision.confidence == 1.0


def test_completed_feedback_does_not_reopen_older_practice():
    """验证 `completed_feedback_does_not_reopen_older_practice` 场景。"""
    decision = PedagogyRouter.route(
        "谢谢",
        history=[
            {
                "role": "assistant",
                "content": "【练习题｜知识点：二叉树遍历】\n请作答。",
            },
            {"role": "user", "content": "B"},
            {"role": "assistant", "content": "【结果】正确"},
        ],
    )
    assert decision.skill_name is None


def test_math_calculation_routes_to_math_skill():
    """验证 `math_calculation_routes_to_math_skill` 场景。"""
    decision = PedagogyRouter.route("帮我算一下 log2(65536) 等于多少")
    assert decision.skill_name == "math_problem_solving"


def test_loaded_skill_body_does_not_request_duplicate_load():
    """验证 `loaded_skill_body_does_not_request_duplicate_load` 场景。"""
    decision = PedagogyRouter.route("帮我算一下 2 的 10 次方")
    context = decision.to_prompt_context(loaded_skill_body="SKILL_BODY_SENTINEL")

    assert "SKILL_BODY_SENTINEL" in context
    assert "无需再调用 load_skill" in context
