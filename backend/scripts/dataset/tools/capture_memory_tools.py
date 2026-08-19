"""抓 CoreMemory 工具的**真实观测**，把最后一处"猜字段名"的地方变成跑出来的。

    python3 dataset/tools/capture_memory_tools.py

为什么值得单独写
----------------
`esa/fixtures.py` 是全项目**唯一**没有真实抓取来源的复刻。交接文档第二节写着
「下次出问题大概率在它身上」—— 2026-08-13 就应验了：后端把
`delete_core_memory` 的参数从 `memory_key` 改成 `memory_id`，返回值也从
`{"deleted":..., "memory_key":..., "profile_projection":...}` 缩成 `{"deleted": bool}`，
我们 8 条样本全错，而**所有校验都是绿的**。

抓在哪一层：只能是 BoundToolExecutor
------------------------------------
⚠️ 2026-08-15 修正：本脚本第一版调的是 `execute_memory_tool`，
那**比线上观测低一层**，抓出来的东西模型根本看不到。真实链路是

    Agent._run_loop
      └─ run_spec.tool_executor.execute(name, args)   ← BoundToolExecutor.execute
           └─ execute_memory_tool(...)                 ← 第一版抓的是这里
      └─ serialize_tool_result(result) = json.dumps(...)   ← 模型看见的字符串

差别不是细节，是**结论相反**：

1. `CapabilityRuntime.compile()` 会按会话模式**把工具整个移出工具表**
   （capability_runtime.py:245-250）：isolated 去掉全部 5 个记忆工具，
   no_write 去掉 3 个写工具。所以受限模式下模型的工具表里**根本没有**这些工具。
2. `BoundToolExecutor.execute` 把 `MemoryPolicyDenied` 接住转成 dict
   （capability_runtime.py:179-185），从不抛给 agent loop。

于是「记忆工具在 isolated 模式返回阻断载荷」这个我们演了 4 条样本的场景，
**线上不存在**：工具压根不在表里，真要硬调只会得到
`{"ok": false, "error": "tool_not_available", ...}`。

所以现在一律走真实 `CapabilityRuntime.compile(...).bind(ctx).execute(...)`，
并且把**每种模式下的工具表**也抓下来（`tool_availability`）——
样本的 `tool_names` 得照着它来，不能在 isolated 样本里摆一个模型看不见的工具。

接线方式抄后端自己的测试，不是自己编的组合：
  backend/tests/test_memory_mode_guards.py:9-24    Context / WorkspaceRoute 怎么构造
  backend/tests/test_profile_projection.py:156-162 建库顺序（先 UserStore 建用户再 migrations）

⚠️ 需要后端依赖（pydantic 等）。2026-08-15 实测本机系统 python3（3.13）已经够用，
缺了再建 venv 装 `~/esa/requirements-dev.txt`。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_repo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dataset/data/cache/memory_real.json"
SEEDS = ROOT / "dataset/seeds/new_tools.yaml"

WORKSPACE = "learning"
SCOPES = frozenset({"common", WORKSPACE})
MODES = ("normal", "no_write", "isolated")

# 初始记忆库。必须与 fixtures.CORE_MEMORIES 逐字对齐 ——
# 检索命中与否完全由 content/key 的字面决定，两边不一致就等于没抓。
# category 用 schema enum 里的值（profile/preference/learning/project/constraint/general）；
# 上一版这里写了 goal / schedule，不在 enum 里，模型永远不会产出那两个值。
SEED_MEMORIES = [
    ("learning_goal", "这学期把数据结构和算法吃透，准备考研", "learning"),
    ("response_style", "喜欢先看直观例子，再看公式推导", "preference"),
    ("major_info", "软件工程专业大三", "profile"),
    ("weak_topics", "图论相关的知识点普遍薄弱", "learning"),
    ("exam_schedule", "期末考试从第 16 周开始", "constraint"),
]

# save_core_memory 的三个分支（core_memory_service.py:196-234）。
# 上一版只抓到 created 一个，于是 fixtures 恒返回"存成功了"，
# 而线上**改已有 key 的内容不会直接覆盖**，要走用户确认。
SAVE_BRANCHES = [
    ("created", "study_time_preference", "倾向晚上学习", "preference"),
    ("unchanged", "response_style", "喜欢先看直观例子，再看公式推导", "preference"),
    ("confirmation_required", "response_style", "改成先看公式推导再看例子", "preference"),
]

# 会被策略/校验拦下的写入。这两条线上可达（normal 模式也会发生），
# 与"会话模式阻断"完全不同：模式阻断在工具表那层就没了，这两条才是真的观测。
REJECTED_SAVES = [
    ("sensitive", "api_cred", "我的 api_key 是 sk-abc123", "general"),
    ("empty_content", "blank_one", "   ", "general"),
]


def load_search_queries() -> list[str]:
    """检索词直接读种子库，保证 capture 抓的和生成器用的是同一批。

    ⚠️ 上一版读的是 `data/cache/_sample_search_queries.json`，注释说它由
    `tools/dump_sample_queries.py` 导出 —— **那个脚本不存在**，文件是手工产物，
    于是"抓的 query"和"生成器用的 query"没有任何东西保证一致。
    那个文件已删（2026-08-15），改成直接读种子。
    """
    import yaml  # noqa: PLC0415

    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    out: list[str] = []
    for item in cfg["search_core_memories"]["正例"]:
        if not isinstance(item, dict) or not item.get("query"):
            raise SystemExit(
                f"seeds/new_tools.yaml 的 search_core_memories 正例缺 query 字段：{item!r}\n"
                "每条必须显式写出 agent 该拿去检索的自然词，不要再拿知识点名当检索词。"
            )
        out.append(item["query"])
    return list(dict.fromkeys(out))


def build_route(repo: Path):
    """接线抄自 backend/tests/test_memory_mode_guards.py:9-24。"""
    from backend.core.router.models import ResourceScope, WorkspaceRoute  # noqa: PLC0415

    # conversation_id 用后端自己的哨兵 "memory-management"：
    # `_source_conversation`（core_memory_service.py:54-60）遇到它会返回 None，
    # 于是 source_conversation_id 存 NULL，不触发指向 conversations 表的外键。
    scope = ResourceScope(metadata={"conversation_id": "memory-management"})
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


async def capture(repo: Path) -> dict:
    sys.path.insert(0, str(repo))
    from backend.agent.memories.core_memory_service import CoreMemoryService  # noqa: PLC0415
    from backend.agent.tools.bootstrap import register_builtin_tools  # noqa: PLC0415
    from backend.agent.tools.context import (  # noqa: PLC0415
        AgentRuntimeDependencies,
        ToolExecutionContext,
    )
    from backend.agent.workspaces.capability_runtime import CapabilityRuntime  # noqa: PLC0415
    from backend.core.stores.core_memory_store import CoreMemoryStore  # noqa: PLC0415
    from backend.core.stores.group_store import GroupStore  # noqa: PLC0415
    from backend.core.stores.migrations import run_migrations  # noqa: PLC0415
    from backend.core.stores.user_store import UserRecord, UserStore  # noqa: PLC0415

    # 后端重构后工具注册不再是 import 副作用，要显式调用，
    # 否则 ScopedToolView 编出来是空的（f3b8c15 踩过一次）。
    register_builtin_tools()

    route, scope = build_route(repo)

    # 建库顺序抄自 backend/tests/test_profile_projection.py:156-162 ——
    # migrations 里的 _migrate_profile_tables 会去查 users 表，
    # 不先建用户会直接 "no such table: users"。
    tmp = Path(tempfile.mkdtemp(prefix="esa_mem_")) / "user.db"
    users = UserStore(tmp)
    users.create(
        UserRecord(id="stu_demo", username="stu_demo", password_hash="x", status="active")
    )
    GroupStore(tmp)
    run_migrations(tmp)

    service = CoreMemoryService(CoreMemoryStore(tmp))
    runtime = CapabilityRuntime()

    def bind(mode: str):
        """编一份该模式下的真实能力视图，再绑上下文 —— 与线上同一条路径。"""
        view = runtime.compile(
            skill_scopes=SCOPES,
            tool_scopes=SCOPES,
            profile_fingerprint="capture.memory",
            policy_versions=("capture.v1",),
            conversation_mode=mode,
            has_research_project=False,
            has_attachments=False,
        )
        ctx = ToolExecutionContext(
            user_id="stu_demo",
            conversation_id="memory-management",
            workspace_route=route,
            authorized_resources=scope,
            conversation_mode=mode,
            runtime_dependencies=AgentRuntimeDependencies(core_memory_service=service),
            request_id="capture",
            username="stu_demo",
        )
        return view, view.bind(ctx)

    calls: list[dict] = []

    async def run(mode: str, name: str, branch: str = "", **args):
        """跑一次真实调用；抛到 agent loop 的异常也如实记下来 —— 那是线上会崩的证据。"""
        _, ex = bind(mode)
        entry: dict = {"mode": mode, "tool": name, "arguments": args}
        if branch:
            entry["branch"] = branch
        try:
            entry["result"] = await ex.execute(name, args)
        except Exception as exc:  # noqa: BLE001
            entry["raises"] = {"type": type(exc).__name__, "message": str(exc)}
        calls.append(entry)
        return entry.get("result")

    # ---- 每种模式下模型能看见哪些工具（样本的 tool_names 得照这个来）----
    availability = {}
    for mode in MODES:
        view, _ = bind(mode)
        availability[mode] = sorted(view.tools.names)

    # ---- normal：先把初始记忆库建起来 ----
    for key, content, category in SEED_MEMORIES:
        await run("normal", "save_core_memory", branch="created",
                  memory_key=key, content=content, category=category)

    listed = await run("normal", "get_core_memories")

    # ---- 真实检索：命中与否由后端说了算 ----
    # 检索是纯词法的（字符二元组重叠 + 短语 + key 精确匹配，
    # core_memory_retrieval.py:42-75），所以结果稳定可复现，
    # 但也意味着抽象词（偏好 / 讲解方式 / 学习目标）**根本搜不到东西**
    # —— 这正是要抓的事实，不是要绕开的障碍。
    queries = load_search_queries()
    search_matrix: dict[str, list[dict]] = {}
    for q in queries:
        hits = await run("normal", "search_core_memories", query=q, limit=5)
        # 只留 memory_key + 检索派生字段：memory_id 和各时间戳每次抓取都变，
        # 写进语料会让数据每天都不一样；这几项由 query 和记忆内容唯一决定，
        # 只要 SEED_MEMORIES 不动就逐次可复现。取值由 fixtures 按 key 还原。
        search_matrix[q] = (
            [
                {
                    "memory_key": m["memory_key"],
                    "score": m["score"],
                    "estimated_tokens": m["estimated_tokens"],
                }
                for m in hits
            ]
            if isinstance(hits, list)
            else []
        )

    # ---- save 的三个分支 + 两种被拒 ----
    for branch, key, content, category in SAVE_BRANCHES:
        await run("normal", "save_core_memory", branch=branch,
                  memory_key=key, content=content, category=category)
    for branch, key, content, category in REJECTED_SAVES:
        await run("normal", "save_core_memory", branch=branch,
                  memory_key=key, content=content, category=category)

    # memory_key 会被 `_key()` 归一化（小写、非法字符转下划线、截断 64）——
    # 模型传什么、库里存什么可能不是一回事，回答里引用 key 要用返回值里的。
    await run("normal", "save_core_memory", branch="key_normalized",
              memory_key="Preferred Code Language", content="平时写 Python",
              category="preference")

    await run("normal", "propose_core_memory",
              memory_key="study_pace", content="倾向每天固定两小时", category="preference")

    real_id = listed[0]["memory_id"] if isinstance(listed, list) and listed else "nonexistent"
    await run("normal", "delete_core_memory", branch="ok", memory_id=real_id)
    # ⚠️ 这条会**抛穿 BoundToolExecutor**：execute 只接住 MemoryPolicyDenied /
    # PermissionError / ValueError / RuntimeError，而 `_require_visible_record`
    # 抛的是 KeyError（core_memory_service.py:167-170）。agent.py:216 那句
    # `await asyncio.wait_for(...)` 外面没有 try —— 也就是说模型删一个不存在的
    # memory_id 会让整轮 run 直接失败。已记入 docs/后端问题反馈.md。
    await run("normal", "delete_core_memory", branch="missing", memory_id="does-not-exist")

    # ---- isolated / no_write：模型真正会看到什么 ----
    for mode in ("no_write", "isolated"):
        await run(mode, "search_core_memories", query="学习目标", limit=5)
        await run(mode, "get_core_memories")
        await run(mode, "save_core_memory", memory_key="k", content="v", category="general")
        await run(mode, "delete_core_memory", memory_id=real_id)

    return {
        "tool_availability": availability,
        "search_matrix": search_matrix,
        "calls": calls,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="抓 CoreMemory 工具真实观测")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        captured = asyncio.run(capture(backend.path))
        out_path = Path(args.out) if args.out else OUT
        payload = {
            "_meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "workspace": WORKSPACE,
                "layer": "BoundToolExecutor.execute",
                "note": (
                    "由 dataset/tools/capture_memory_tools.py 在临时 SQLite 上跑真实 "
                    "CapabilityRuntime.compile().bind().execute() 产出，禁止手改。"
                    "抓的是**模型真正看得见的那一层**（线上再套一层 json.dumps）。"
                    "memory_id 与各时间戳每次抓取都会变，"
                    "所以**只用它钉字段名和结构，不要把具体值写进种子**；"
                    "命中判定用 search_matrix（只存 memory_key，稳定可复现）。"
                ),
            },
            **captured,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        print(f"\n抓到 {len(captured['calls'])} 次真实调用 → {backend_repo.display_path(out_path, ROOT)}")
        print(f"  来源：{backend.describe()}")
        print("\n每种模式下模型能看见的工具数：")
        for mode, names in captured["tool_availability"].items():
            mem = [n for n in names if "memor" in n]
            print(f"  {mode:9} {len(names):3} 个　记忆工具 {len(mem)} 个 {mem}")
        print("\n检索命中矩阵（真实结果，不是我们挑的）：")
        for q, hits in captured["search_matrix"].items():
            print(f"  {q:10} → {len(hits)} 条 {[h['memory_key'] for h in hits]}")
        print("\n受限模式下的真实观测：")
        for c in captured["calls"]:
            if c["mode"] == "normal":
                continue
            r = c.get("result", c.get("raises"))
            body = json.dumps(r, ensure_ascii=False, default=str)
            print(f"  [{c['mode']:9}] {c['tool']:22} → {body[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
