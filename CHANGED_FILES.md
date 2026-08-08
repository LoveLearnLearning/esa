# Changed files — v2 fixed

## 修改现有文件

- `backend/agent/agent.py`
- `backend/agent/memories/core_memory.py`
- `backend/agent/memories/profile_builder.py`（由 `apply_source_refactors.py` 外科式 patch）
- `backend/agent/tools/__init__.py`
- `backend/agent/tools/mastery_tools.py`
- `backend/agent/tools/memory_tools.py`
- `backend/agent/tools/skills.py`
- `backend/core/message/build_prompt.py`
- `backend/core/web/webAPI.py`（由 `apply_source_refactors.py` 外科式 patch）
- `backend/core/utils/models.py`
- `backend/agent/skills/SKILLS.md`
- `backend/agent/skills/homework_review.md`
- `backend/agent/skills/mastery_report.md`
- `backend/agent/skills/practice_recommendation.md`
- `backend/agent/skills/profile_personalization.md`
- `backend/agent/skills/study_plan.md`
- `backend/tests/test_memory_mode_guards.py`
- `backend/tests/test_pedagogy_prompt.py`
- `backend/tests/test_profile_builder.py`（由 `apply_source_refactors.py` 外科式 patch）
- `backend/tests/test_profile_api.py`（由 `apply_source_refactors.py` 外科式 patch）

## 新增文件

- `backend/core/message/system.py`
- `backend/core/message/style_tone.py`
- `backend/agent/learning/__init__.py`
- `backend/agent/learning/evidence_store.py`
- `backend/agent/learning/pedagogy_router.py`
- `backend/agent/tools/learning_tools.py`
- `backend/agent/tools/export_schemas.py`
- `backend/agent/skills/error_diagnosis.md`
- `backend/agent/skills/progressive_hint.md`
- `backend/agent/skills/retrieve_first.md`
- `backend/agent/skills/teach_back.md`
- `backend/tests/test_learning_evidence_store.py`
- `backend/tests/test_mastery_runtime_semantics.py`
- `backend/tests/test_pedagogy_router.py`
- `backend/tests/test_skill_contracts.py`
- `backend/tests/test_memory_on_demand.py`
- `backend/tests/test_agent_memory_architecture.py`
- `backend/tests/test_profile_core_memory_separation.py`
- `apply_source_refactors.py`
- `FIXED_ISSUES.md`
- `OPTIMIZATION_NOTES.md`
- `APPLY_WINDOWS.ps1`
- `APPLY_LINUX.sh`
