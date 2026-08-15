"""临时调试脚本：验证聊天中做完练习后 record 工具的写入链路。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.agent.tools.learning.runtime import execute_learning_tool
from backend.agent.workspaces.capability_runtime import CapabilityRuntime
from backend.core.router.basic_router import route_workspace
from backend.core.router.context import ConversationContext, RoutingContext
from backend.core.router.models import TrustedIdentity


async def main() -> None:
    register_builtin_tools()
    tmp = Path(sys.argv[1] if len(sys.argv) > 1 else "data/debug")
    kg = KnowledgeGraphStore(tmp / "kg.db")
    kg.add_point("hash_table", "哈希表", "数据结构", 0.8)
    kg.add_alias("哈希表", "hash_table")
    mastery = MasteryStore(tmp / "mastery.db")
    evidence = LearningEvidenceStore(tmp / "evidence.db")
    service = LearningStateService(
        kg_store=kg, mastery_store=mastery, evidence_store=evidence
    )

    route = route_workspace(
        TrustedIdentity("u1", "alice", "student"),
        RoutingContext(ConversationContext("c1", "u1", "learning")),
    )
    deps = AgentRuntimeDependencies(
        knowledge_graph_store=kg,
        mastery_store=mastery,
        learning_evidence_store=evidence,
        learning_state_service=service,
    )
    ctx = ToolExecutionContext(
        user_id="u1",
        username="alice",
        conversation_id="c1",
        workspace_route=route,
        authorized_resources=route.resource_scope,
        conversation_mode="normal",
        runtime_dependencies=deps,
        request_id="req-1",
    )

    # 模拟模型以两种方式调用 record_answer
    cases = [
        ("record_answer", {"kp_id": "hash_table", "correct": True, "confidence": 0.9}),
        ("record_learning_evidence", {
            "kp_id": "哈希表", "activity_type": "practice",
            "correct": True, "evidence_reliability": 0.9, "independent": True,
        }),
    ]
    for name, args in cases:
        try:
            result = execute_learning_tool(ctx, name, args)
            print(f"[{name}] args={args} -> {result}")
        except Exception as exc:
            print(f"[{name}] args={args} -> EXC {type(exc).__name__}: {exc}")

    # 通过完整 CapabilityRuntime 链路（模拟 agent 真实调用路径）
    caps = CapabilityRuntime().compile(
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}),
        profile_fingerprint="learning.default.v1:1",
        policy_versions=("learning.v1",),
        conversation_mode="normal",
    )
    bound = caps.bind(ctx)
    for name, args in cases:
        result = await bound.execute(name, args)
        print(f"[bound:{name}] -> {result}")

    print("--- mastery state ---")
    print(mastery.get_state("alice", "hash_table"))


if __name__ == "__main__":
    asyncio.run(main())
