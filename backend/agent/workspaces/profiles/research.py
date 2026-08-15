# backend/agent/workspaces/profiles/research.py

"""提供 `research` 相关功能。"""

from backend.agent.workspaces.models import LoopPolicy, WorkspaceRuntimeProfile
from backend.core.utils.config import AGENT_LOOP_TIME, AGENT_TOOL_TIMEOUT_SECONDS

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
    loop_policy=LoopPolicy(
        max_iterations=AGENT_LOOP_TIME,
        tool_timeout_seconds=AGENT_TOOL_TIMEOUT_SECONDS,
    ),
)
