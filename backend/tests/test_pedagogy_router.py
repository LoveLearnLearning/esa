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


def test_concept_question_routes_to_grounded_explanation():
    """概念问题路由到本轮直接回答且使用知识库的 Skill。"""
    decision = PedagogyRouter.route(
        "解释一下为什么二叉树遍历会用到递归",
        resolved_kp_ids=("二叉树遍历",),
    )
    assert decision.skill_name == "grounded_explanation"


def test_plain_teaching_phrases_route_to_grounded_explanation():
    """口语化的讲解请求也应进入有依据的讲解流程。"""
    decision = PedagogyRouter.route(
        "给我讲一下二叉树的基础知识",
        resolved_kp_ids=("二叉树",),
    )

    assert decision.skill_name == "grounded_explanation"
    assert decision.task_type == "learning"


def test_ambiguous_engineering_term_can_still_be_a_learning_concept():
    """接口、依赖、异常等歧义词不应压过明确的概念提问。"""
    decision = PedagogyRouter.route(
        "解释一下 Java 接口的原理",
        resolved_kp_ids=("Java 接口",),
    )

    assert decision.skill_name == "grounded_explanation"
    assert decision.task_type == "learning"


def test_software_framework_explanation_does_not_force_course_rag():
    decision = PedagogyRouter.route("解释一下 Raylib 的窗口循环原理")

    assert decision.skill_name is None
    assert decision.task_type == "general"
    assert "不强制课程库检索" in decision.reason


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


def test_short_answer_uses_trusted_pending_practice_without_text_marker():
    """服务端已绑定练习时，回答不依赖模型输出中的文本标记。"""
    decision = PedagogyRouter.route(
        "B",
        history=[
            {
                "role": "assistant",
                "content": "判断链表头结点的下一跳是否为空。",
            },
        ],
        pending_practice_kp_id="链表",
        resolved_kp_ids=("链表",),
    )

    assert decision.skill_name == "adaptive_practice"
    assert decision.primary_kp_id == "链表"
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
