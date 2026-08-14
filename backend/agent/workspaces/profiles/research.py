from backend.agent.workspaces.models import LoopPolicy, WorkspaceRuntimeProfile

PROFILE = WorkspaceRuntimeProfile(
    profile_id="research.default.v1",
    workspace_type="research",
    prompt_key="research.v1",
    skill_scopes=frozenset({"common", "research"}),
    tool_scopes=frozenset({"common", "research"}),
    context_policy=frozenset({"style", "profile", "group", "summary", "attachments", "workspace_profile", "resource"}),
    profile_policy="research.v1",
    memory_policy_id="research.v1",
    action_policy="research.v1",
    loop_policy=LoopPolicy(),
)

