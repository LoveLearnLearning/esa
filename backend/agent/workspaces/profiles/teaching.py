from backend.agent.workspaces.models import LoopPolicy, WorkspaceRuntimeProfile

PROFILE = WorkspaceRuntimeProfile(
    profile_id="teaching.default.v1",
    workspace_type="teaching",
    prompt_key="teaching.v1",
    skill_scopes=frozenset({"common", "teaching"}),
    tool_scopes=frozenset({"common", "teaching"}),
    context_policy=frozenset({"style", "profile", "group", "summary", "attachments", "resource"}),
    profile_policy="teaching.v1",
    memory_policy_id="teaching.v1",
    action_policy="teaching.v1",
    loop_policy=LoopPolicy(),
)

