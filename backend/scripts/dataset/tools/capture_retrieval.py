"""抓 `retrieve_knowledge` **模型真正看得见的那一层**（第八份缓存）。

    python3 dataset/tools/capture_retrieval.py

为什么必须新写一份
------------------
2026-08-27 上游 `b3eac70`「添加RAG召回内容后处理模块」在召回结果和模型之间
插了一层投影（`backend/agent/rag/context_projection.py`）。实测同一份返回：

    投影前（我们 `fixtures.retrieve_knowledge()` 现在抄的那份）
        {"contract_version": "...", "results": [], "execution": {"degraded": [...]}, ...}
    投影后（模型实际看见的，MINIMAL profile）
        {"profile": "MINIMAL", "results": []}

**`degraded` 标记整段没了。** 而我们那 12 条检索样本教的正是
「看到 degraded → 知道检索没成功 → 降级回答」—— 那个信号模型已经看不见了。
这是 5.18 / 5.47 同一个形状的第五次，区别只在于这次是在写数据**之前**发现的。

投影不是边角情况，是**无条件**发生的：
  - `capability_runtime.py` 在 `knowledge_sources` 为空时把 `retrieve_knowledge`
    整个移出工具表，所以模型能调它的每一轮，`knowledge_sources` 必然非空；
  - `chat.py` 把 `metadata_projection_mode` 设成 `RAG_METADATA_PROJECTION_MODE`，
    其 config 默认是 `"rule"`（`"off"` 只是回滚开关）。
  ⚠️ `AgentRuntimeDependencies` 那个 dataclass 的默认值是 `"off"`，
    **别拿它当生产默认值** —— 生产走的是 config 那个。

模型看见的形状由一个规则路由决定（`context_routing.py`），四种：

    MINIMAL   {ref, content, citation_mode}                 ← 默认
    SOURCE    + source, author                              ← 问「出处/来源/谁提出的」
    LOCATION  + section, page（无 page 才给 location）        ← 问「第几页/哪一章」
    FULL      + metadata + retrieval_metadata               ← 问「chunk/检索分数/元数据」

所以**同一次召回能有四种模型视图**，样本必须分别覆盖，不能只写一种。

抓在哪一层：只能是 BoundToolExecutor
------------------------------------
不许自己拼「调 `retrieve_selected_knowledge` + 调 `MetadataProjectionMiddleware`」
那两步 —— 那是在第二个地方重写一遍 `BoundToolExecutor.execute`，正是 5.54
（两个地方各自算同一个键 = 没有键）那个形状。本脚本一律走

    CapabilityRuntime.compile(knowledge_sources=...).bind(ctx).execute("retrieve_knowledge", ...)

投影上下文也用后端自己的 `WorkspaceRuntime._retrieval_projection_context(turn)`，
不自己 new 一个 `RuleBasedContextRouter`。它是私有方法，上游改名我们会**当场炸**
—— 那正是我们要的失效方向（fail-closed），而不是安静地分叉两天（5.64）。

「投影前」那一份怎么来的：**不是另写一条路径**，而是把同一个执行器的
`metadata_projection_mode` 设成后端自己提供的回滚值 `"off"` 再跑一遍。
两份都出自真实执行器。

真实内容需要什么
----------------
公共侧检索要 `RAGApplicationLifecycle().start()`，它只建服务 + warmup + 设全局，
`close()` 只重置全局 —— **不写任何持久状态**。会 flush 快照、重建 personal 分片的
是 `PERSONAL_KB_ENABLED` 那一支，本脚本**不碰它**。

没有活服务时本脚本照样能跑，但产出的是降级/报错路径，`has_live_service: false`。
⚠️ **那种产物不能用来写「检索成功」的样本** —— 成功返回必须来自真实服务，
编一套就是重蹈 `fixtures.py` 抬头记的那次覆辙（220 条样本消费线上不存在的结构，
而所有校验全绿），也违反《02》「不伪造」承诺。

⚠️ 需要后端依赖（pydantic 等）。真跑检索还需要 GPU（Qwen3-Embedding-8B），
那一步在超算上做。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_repo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dataset/data/cache/retrieval_real.json"

WORKSPACE = "learning"
SCOPES = frozenset({"common", WORKSPACE})

# 每条都带**预期 profile**，而且由真实路由当场判定并断言。
# 这道闸门防的不是后端，是我自己 —— 挑 query 的时候很容易想当然地
# 以为某句话会命中某条规则（实测「不用给我来源」就不命中 SOURCE）。
# 上游哪天改了路由词表，这里会当场红，而不是安静地产出一批标错 profile 的样本。
CASES: tuple[dict, ...] = (
    {
        "query": "什么是递归",
        "sources": ("public",),
        "expect": "MINIMAL",
        "why": "最常见的概念题，走默认档",
    },
    {
        "query": "什么是递归",
        "sources": ("personal",),
        "expect": "MINIMAL",
        "why": "只选了个人库 —— 服务缺失时这一支返回降级载荷而不是报错",
    },
    {
        "query": "页面置换算法这段出自哪份文档",
        "sources": ("public",),
        "expect": "SOURCE",
        "why": "问出处 → 模型需要 source/author",
    },
    {
        "query": "死锁的四个必要条件在第几页提到的",
        "sources": ("public",),
        "expect": "LOCATION",
        "why": "问页码 → 模型需要 section/page",
    },
    {
        "query": "把检索到的 chunk 和它们的检索分数都给我看看",
        "sources": ("public",),
        "expect": "FULL",
        "why": "显式要元数据 → 整份放行，含 retrieval_metadata",
    },
    {
        "query": "讲讲 TCP 拥塞控制，不用给我来源",
        "sources": ("public",),
        "expect": "MINIMAL",
        "why": "否定判别：带「来源」但被「不用」否定，仍应落 MINIMAL",
    },
)


def build_route(repo: Path):
    """接线抄自 backend/tests/test_memory_mode_guards.py:9-24（与记忆那份一致）。"""
    from backend.core.router.models import ResourceScope, WorkspaceRoute  # noqa: PLC0415

    scope = ResourceScope(metadata={"conversation_id": "retrieval-capture"})
    route = WorkspaceRoute(
        workspace_type=WORKSPACE,
        agent_profile_id="learning.v1",
        skill_scopes=SCOPES,
        tool_scopes=SCOPES,
        prompt_key="learning.v1",
        profile_policy="learning.profile.v1",
        memory_policy_id="learning.memory.v1",
        resource_scope=scope,
        action_policy="learning.actions.v1",
    )
    return route, scope


async def capture(repo: Path, *, want_live: bool) -> dict:
    sys.path.insert(0, str(repo))
    from backend.agent.rag.lifecycle import RAGApplicationLifecycle  # noqa: PLC0415
    from backend.agent.tools.bootstrap import register_builtin_tools  # noqa: PLC0415
    from backend.agent.tools.context import (  # noqa: PLC0415
        AgentRuntimeDependencies,
        ToolExecutionContext,
    )
    from backend.agent.workspaces.capability_runtime import CapabilityRuntime  # noqa: PLC0415
    from backend.agent.workspaces.models import AgentTurnInput  # noqa: PLC0415
    from backend.agent.workspaces.routing import TrustedIdentity  # noqa: PLC0415
    from backend.agent.workspaces.runtime import WorkspaceRuntime  # noqa: PLC0415
    from backend.core.utils import config  # noqa: PLC0415

    # 工具注册不再是 import 副作用，要显式调用，否则 ScopedToolView 编出来是空的。
    register_builtin_tools()

    route, scope = build_route(repo)
    runtime_caps = CapabilityRuntime()

    # 公共侧检索服务。RAG_ENABLED=false 时 start() 返回 None —— 那不是错误，
    # 是「没有活服务」，产物会如实标记。personal 那一支刻意不碰（见抬头）。
    lifecycle = RAGApplicationLifecycle()
    public_service = lifecycle.start()
    if want_live and public_service is None:
        raise SystemExit(
            "❌ --live 要求真实检索服务，但 RAGApplicationLifecycle.start() 返回 None。\n"
            f"   RAG_ENABLED={getattr(config, 'RAG_ENABLED', None)}；"
            "请在加载过 deploy/rag/*.env 的环境里跑（并保证 Qdrant 已就绪）。"
        )

    identity = TrustedIdentity(
        user_id="stu_demo", username="stu_demo", account_role="student"
    )

    def projection_context(mode: str, query: str, sources: tuple[str, ...]):
        """用**后端自己的**那段路由逻辑产出投影上下文，不自己 new 路由器。

        `mode="off"` 走的是后端提供的回滚开关，于是执行器返回投影前那份 ——
        「投影前/投影后」两份都出自同一条真实路径。
        """
        deps = AgentRuntimeDependencies(
            rag_service=public_service,
            personal_knowledge_retrieval_service=None,
            metadata_projection_mode=mode,
        )
        turn = AgentTurnInput(
            route=route,
            identity=identity,
            conversation_id="retrieval-capture",
            current_message=query,
            knowledge_sources=sources,
        )
        return deps, WorkspaceRuntime(deps)._retrieval_projection_context(turn)

    async def run(mode: str, case: dict):
        sources = tuple(case["sources"])
        deps, proj = projection_context(mode, case["query"], sources)
        view = runtime_caps.compile(
            skill_scopes=SCOPES,
            tool_scopes=SCOPES,
            profile_fingerprint="capture.retrieval",
            policy_versions=("capture.v1",),
            has_research_project=False,
            has_attachments=False,
            knowledge_sources=sources,
        )
        ctx = ToolExecutionContext(
            user_id="stu_demo",
            conversation_id="retrieval-capture",
            workspace_route=route,
            authorized_resources=scope,
            conversation_mode="normal",
            runtime_dependencies=deps,
            request_id="capture",
            username="stu_demo",
            knowledge_sources=sources,
            retrieval_projection_context=proj,
        )
        executor = view.bind(ctx)
        if not executor.names or "retrieve_knowledge" not in executor.names:
            raise SystemExit(
                "❌ 工具表里没有 retrieve_knowledge —— 编出来的视图不对，别信这次产物。\n"
                f"   knowledge_sources={sources}　工具数={len(executor.names)}"
            )
        try:
            result = await executor.execute(
                "retrieve_knowledge", {"query": case["query"], "top_k": 5}
            )
        except Exception as error:  # noqa: BLE001 - 报错本身就是要抓的一种形态
            return {"raised": f"{type(error).__name__}: {error}"}, None, proj
        model_content = getattr(result, "model_content", result)
        audit = getattr(result, "audit_metadata", None)
        return model_content, audit, proj

    def classify(model_content, audit) -> tuple[str, dict | None]:
        """这一次调用走到了哪一层。

        两种返回都是模型真会看见的东西，不能用同一条闸门一刀切：

        - `ToolExecutionResult` → 投影**必须**已生效，否则我们抓的就是错的那一层；
        - plain dict（`{"ok": false, "error": "tool_execution_error", ...}`）
          → 工具在到达投影之前就失败了（例如没配公共检索服务）。
          这是真实的报错形态，值得抓，但它证明不了投影那一层。
        """
        if not isinstance(audit, dict):
            return "not_reached", None
        block = audit.get("metadata_projection")
        if not isinstance(block, dict) or block.get("status") != "applied":
            return "broken", block if isinstance(block, dict) else None
        return "applied", block

    cases: list[dict] = []
    try:
        for case in CASES:
            projected, audit, proj = await run("rule", case)
            unprojected, _, _ = await run("off", case)

            # 闸门①：路由判成了什么，必须和我挑 query 时的预期一致。
            got = proj.decision.profile.value if proj and proj.decision else None
            if got != case["expect"]:
                raise SystemExit(
                    f"❌ 闸门：query「{case['query']}」预期 profile {case['expect']}，"
                    f"实际 {got}。\n"
                    "   要么是我挑错了 query，要么是上游改了路由词表 —— "
                    "两种都得人来看，别让它静默产出标错 profile 的样本。"
                )

            # 闸门②：走到了投影那一层的，投影就**必须**真的生效。
            # 看的是审计里那一段，不是 model_content 长什么样 ——
            # 空结果时投影前后长得很像，拿形状判会漏。
            status, block = classify(projected, audit)
            if status == "broken":
                raise SystemExit(
                    f"❌ 闸门：query「{case['query']}」拿到了 ToolExecutionResult，"
                    f"但投影没生效（metadata_projection={block!r}）。\n"
                    "   抓到的就不是模型看见的那一层，这份产物不能用。"
                )
            if status == "not_reached" and want_live:
                raise SystemExit(
                    f"❌ 闸门：--live 模式下 query「{case['query']}」"
                    f"（sources={list(case['sources'])}）在到达投影前就失败了：\n"
                    f"   {json.dumps(projected, ensure_ascii=False)[:200]}"
                )

            cases.append(
                {
                    "query": case["query"],
                    "knowledge_sources": list(case["sources"]),
                    "why": case["why"],
                    "profile": got,
                    "reason_code": proj.decision.reason_code,
                    "matched_rule": proj.decision.matched_rule,
                    "router_version": proj.decision.router_version,
                    "projection": status,
                    "model_content": projected,
                    "model_content_projection_off": unprojected,
                    "audit_metadata_projection": block,
                }
            )
    finally:
        lifecycle.close()

    from backend.agent.rag.context_projection import ContextSerializer  # noqa: PLC0415

    # 闸门③：整批里一个都没走到投影那一层，说明这次抓取根本没碰到
    # 我们要钉的东西。产物看起来会很正常（全是 error dict），
    # 而那正是本项目栽过十五次的「数据是错的，仪表盘是绿的」。
    if not any(c["projection"] == "applied" for c in cases):
        raise SystemExit(
            "❌ 闸门：没有任何一个用例走到投影那一层，这次抓取钉不住任何东西。\n"
            "   全部停在工具报错上 —— 去看 knowledge_sources 与服务配置。"
        )

    return {
        "has_live_service": public_service is not None,
        "projection_mode": "rule",
        "serializer": ContextSerializer.mode,
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="抓 retrieve_knowledge 投影后（模型可见）的真实返回"
    )
    ap.add_argument("--repo")
    ap.add_argument("--out")
    ap.add_argument("--download", action="store_true")
    ap.add_argument(
        "--live",
        action="store_true",
        help="要求真实检索服务在位；拿不到就报错退出，而不是安静地产出降级路径",
    )
    args = ap.parse_args()

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        captured = asyncio.run(capture(backend.path, want_live=args.live))
        out_path = Path(args.out) if args.out else OUT
        payload = {
            "_meta": {
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "workspace": WORKSPACE,
                "layer": "BoundToolExecutor.execute（已过 MetadataProjectionMiddleware）",
                "note": (
                    "由 dataset/tools/capture_retrieval.py 跑真实 "
                    "CapabilityRuntime.compile().bind().execute() 产出，禁止手改。"
                    "`model_content` 是**模型看得见的那一层**；"
                    "`model_content_projection_off` 只是投影前的对照，"
                    "**不许拿它写样本**（它比模型看见的多一批字段，"
                    "包括 degraded / contract_version / budget）。"
                    "has_live_service=false 时全部是降级或报错路径，"
                    "不能用来写「检索成功」的样本。"
                ),
            },
            **captured,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        live = captured["has_live_service"]
        print(f"\n抓到 {len(captured['cases'])} 个用例 → {backend_repo.display_path(out_path, ROOT)}")
        print(f"  来源：{backend.describe()}")
        print(f"  真实检索服务：{'✅ 在位' if live else '❌ 不在（产物只有降级/报错路径）'}")
        print(f"  序列化器：{captured['serializer']}")
        print("\n每个用例模型实际看见的：")
        for c in captured["cases"]:
            a = c["audit_metadata_projection"] or {}
            body = json.dumps(c["model_content"], ensure_ascii=False, default=str)
            mark = "投影后" if c["projection"] == "applied" else "未到投影层"
            saved = a.get("saved_tokens")
            saved = f"省 {saved} token" if saved is not None else "—"
            print(
                f"  [{c['profile']:8}] {mark:5} {saved:<12} {c['query'][:24]:<26}"
                f" {body[:58]}"
            )
        if not live:
            print(
                "\n⚠️ 没有活服务，这份产物**只能**用来钉降级/报错路径的结构。"
                "\n   「检索成功 → 用证据讲清楚」那批样本必须等真服务，不许编。"
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
