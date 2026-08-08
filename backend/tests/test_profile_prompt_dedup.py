import json

from backend.agent.memories.memory_models import (
    ProfileField,
    ProfileOrigin,
    ProfileSnapshot,
)


def test_response_preferences_are_kept_for_api_but_not_duplicated_into_prompt_json():
    snapshot = ProfileSnapshot(
        user_id="u1",
        profile_version=1,
        explicit_context=[
            ProfileField("major", "cs", ProfileOrigin.EXPLICIT_SETTING),
        ],
        response_preferences=[
            ProfileField("preferred_style", "concise", ProfileOrigin.EXPLICIT_SETTING),
            ProfileField("preferred_tone", "friendly", ProfileOrigin.EXPLICIT_SETTING),
            ProfileField("custom_instruction", "先给结论", ProfileOrigin.EXPLICIT_SETTING),
        ],
    )

    api_payload = snapshot.to_dict()
    prompt_payload = json.loads(snapshot.to_prompt_json())

    assert len(api_payload["response_preferences"]) == 3
    assert "response_preferences" not in prompt_payload
    assert "explicit_context" in prompt_payload
