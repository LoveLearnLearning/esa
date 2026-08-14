from backend.agent.workspaces.models import LoopPolicy, WorkspaceRuntimeProfile
from backend.core.utils.config import AGENT_LOOP_TIME, AGENT_TOOL_TIMEOUT_SECONDS

PROFILE = WorkspaceRuntimeProfile(
    profile_id="learning.default.v1",
    workspace_type="learning",
    prompt_key="learning.v1",
    skill_scopes=frozenset({"common", "learning"}),
    tool_scopes=frozenset({"common", "learning"}),
    context_policy=frozenset({"style", "profile", "group", "summary", "attachments", "strategy"}),
    profile_policy="learning.v1",
    memory_policy_id="learning.v1",
    action_policy="learning.v1",
    loop_policy=LoopPolicy(
        max_iterations=AGENT_LOOP_TIME,
        tool_timeout_seconds=AGENT_TOOL_TIMEOUT_SECONDS,
    ),
)

