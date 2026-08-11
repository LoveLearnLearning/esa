from backend.agent.learning.pedagogy_router import PedagogyRouter
from backend.agent.memories.memory_models import (
    ProfileField,
    ProfileOrigin,
    ProfileSnapshot,
)


def _profile(
    mastery,
    *,
    has_record=True,
    prerequisite_status="known",
    avg_hint_level=None,
    independent_rate=None,
):
    return ProfileSnapshot(
        user_id="u1",
        profile_version=1,
        relevant_learning_state=[
            ProfileField(
                field="knowledge.二叉树遍历",
                value={
                    "kp_id": "二叉树遍历",
                    "mastery": {
                        "has_record": has_record,
                        "level": mastery,
                        "practice_count": 1 if has_record else 0,
                    },
                    "evidence": {
                        "avg_hint_level": avg_hint_level,
                        "independent_rate": independent_rate,
                        "recent_misconceptions": [],
                    },
                    "prerequisites": [
                        {"kp_id": "递归", "status": prerequisite_status}
                    ],
                },
                origin=ProfileOrigin.DERIVED_LEARNING_STATE,
            )
        ],
    )


def test_low_mastery_selects_foundation_depth():
    decision = PedagogyRouter.route(
        "什么是二叉树遍历？", profile=_profile(25)
    )
    assert decision.teaching_depth == "foundation"


def test_mid_mastery_selects_standard_depth():
    decision = PedagogyRouter.route(
        "什么是二叉树遍历？", profile=_profile(60)
    )
    assert decision.teaching_depth == "standard"


def test_high_mastery_selects_advanced_depth():
    decision = PedagogyRouter.route(
        "什么是二叉树遍历？", profile=_profile(90)
    )
    assert decision.teaching_depth == "advanced"


def test_weak_prerequisite_is_routed_before_current_point():
    decision = PedagogyRouter.route(
        "什么是二叉树遍历？",
        profile=_profile(60, prerequisite_status="weak"),
    )
    assert decision.prerequisite_first is True


def test_unknown_mastery_uses_standard_depth_without_claiming_weakness():
    decision = PedagogyRouter.route(
        "什么是二叉树遍历？",
        profile=_profile(50, has_record=False, prerequisite_status="unknown"),
    )
    assert decision.teaching_depth == "standard"
    assert decision.prerequisite_first is False


def test_prompt_context_turns_evidence_into_behavioral_guidance():
    decision = PedagogyRouter.route(
        "什么是二叉树遍历？",
        profile=_profile(
            25,
            prerequisite_status="weak",
            avg_hint_level=2.5,
            independent_rate=0.3,
        ),
    )
    prompt = decision.to_prompt_context()

    assert "当前知识点：二叉树遍历" in prompt
    assert "教学深度：foundation" in prompt
    assert "先补前置" in prompt
    assert "避免直接泄露完整答案" in prompt
    assert "主动回忆与独立尝试" in prompt


def test_resolved_point_makes_plain_teaching_request_a_learning_task():
    decision = PedagogyRouter.route("给我讲讲二叉树", profile=_profile(25))

    assert decision.task_type == "learning"
    assert decision.teaching_depth == "foundation"
    assert "教学深度：foundation" in decision.to_prompt_context()


def test_resolved_point_keeps_follow_up_explanation_in_learning_mode():
    decision = PedagogyRouter.route(
        "二叉树遍历我还是不太懂，你再给我讲一下",
        profile=_profile(60, prerequisite_status="weak"),
    )

    assert decision.task_type == "learning"
    assert decision.prerequisite_first is True


def test_ambiguous_dependency_word_does_not_override_resolved_learning_point():
    decision = PedagogyRouter.route(
        "递归是二叉树的前置依赖吗？",
        profile=_profile(60, prerequisite_status="weak"),
    )

    assert decision.task_type == "learning"


def test_strong_engineering_signal_still_overrides_resolved_point():
    decision = PedagogyRouter.route(
        "二叉树代码在 CUDA 部署时报错",
        profile=_profile(60),
    )

    assert decision.task_type == "engineering"
