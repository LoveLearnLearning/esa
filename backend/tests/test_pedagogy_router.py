from backend.agent.learning.pedagogy_router import PedagogyRouter


def test_task_mode_has_highest_intent_priority():
    decision = PedagogyRouter.route(
        "任务模式：批改作业。区分题目与学生作答。\n\n用户提供的内容：我的答案是 B"
    )
    assert decision.skill_name == "homework_review"
    assert decision.confidence == 1.0


def test_engineering_request_does_not_force_tutoring():
    decision = PedagogyRouter.route(
        "帮我修 GitHub 仓库里的 CUDA 部署报错，并直接告诉我改哪个文件"
    )
    assert decision.skill_name is None
    assert decision.task_type == "engineering"


def test_stuck_student_routes_to_progressive_hint():
    decision = PedagogyRouter.route("这道递归题我卡住了，给我提示一下")
    assert decision.skill_name == "progressive_hint"


def test_concept_question_routes_to_retrieve_first():
    decision = PedagogyRouter.route("解释一下为什么二叉树遍历会用到递归")
    assert decision.skill_name == "retrieve_first"
