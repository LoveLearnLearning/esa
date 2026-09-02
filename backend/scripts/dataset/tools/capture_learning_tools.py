"""抓 8 个学情工具的**真实返回结构**，让 `fixtures.py` 不再是纯手写复刻。

    python3 dataset/tools/capture_learning_tools.py

为什么做这个
------------
`esa/fixtures.py` 覆盖 686 条样本（52% 语料），一直是**手写复刻**，
没有真实抓取来源。2026-08-13 记忆工具那次证明了这有多危险：
后端改了返回结构，67 条样本静默错掉，而 33 项契约**全绿**——
因为契约钉的是复刻自己的形状，不是后端的。

学情工具这次侥幸没变（比对过 `303a2f7` 的旧 `mastery_tools.py`
和新 `learning/runtime.py`，载荷逐字一致），但"侥幸"不是防线。

一条必须理解的原则
------------------
**capture 钉结构，fixtures 供取值。**

`apply_evidence` 带时间衰减（`retention` 随 `now` 变），所以捕获值
**不是逐日可复现的**。硬拿捕获值当数据会让语料每天都变。
所以分工是：

  - 本脚本产出的 `learning_real.json`：**结构的事实来源**
    （有哪些键、什么类型、怎么嵌套、阻断时长什么样）
  - `esa/fixtures.py`：**取值的来源**（确定性哈希，保证语料字节可复现）
  - `tests/test_fixture_contract.py`：比对两者的**结构**，不比数值

后端一改结构，契约测试就红；后端只改数值口径，那是另一回事，
由这份缓存的 diff 体现出来给人看。

接线方式抄自后端自己的 `backend/tests/test_knowledge_map_service.py:9-26`
和 `test_profile_projection.py:156-162`，不是我编的组合。

抓在哪一层：只能是 BoundToolExecutor（2026-08-19 改）
------------------------------------------------------
本脚本原来直接调 `execute_learning_tool`，比模型看得见的那一层**低一层**。
成功路径上两者返回值相同，所以一直没出事；**报错路径上两者是两种东西**：

    execute_learning_tool          抛 ValueError("unknown knowledge point 'quicksort'")
    BoundToolExecutor.execute      返回 {"ok": false, "error": "tool_execution_error",
                                        "tool": ..., "detail": "unknown knowledge point ..."}

`capability_runtime.py:193-199` 把 `(ValueError, RuntimeError)` 整个接住转成 dict，
**从不抛给 agent loop**。所以缓存里原来那条 `raises: {...}` 描述的是一个
线上不存在的形态 —— 谁照着它写恢复样本，写出来的观测就是编的。
这是 5.18 在另一个文件上的重演：当时的结论「跑模型真正走的那条路径」
只应用到了记忆工具，学情这边没回头检查。

判断标准还是那一句：**抓下来的东西，中间还隔着几层才到模型眼前？隔着就是抓错了。**
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
OUT = ROOT / "dataset/data/cache/learning_real.json"

USER = "stu_demo"

# 学习空间的 scope（core/router/workspace_profiles.py:18），与 capture_tool_schemas 一致
SCOPES = frozenset({"common", "learning"})

# 确定性种子：(kp_id, 答对次数, 答错次数)。
# 选的知识点覆盖「有记录 / 无记录 / 有前置」三种情况，
# 具体数值不重要——我们只要结构。
SEED_PRACTICE = [
    ("设备管理", 1, 3),
    ("进程调度", 3, 1),
    ("虚拟内存", 2, 2),
    ("死锁", 0, 4),
    ("信号量", 4, 0),
]



def _model_projection(result):
    """取三投影里模型看得见的那一层。

    2026-09-02：上游 `d29d3e4` 把工具返回换成了 `ToolExecutionResult`
    （`model_content` / `display_content` / `audit_metadata` 三投影）。
    链路核过：`loop_runtime.tool_result_channels()` 拆包 →
    `serialize_tool_result()` = `json.dumps(model_content, default=str)` →
    `ToolObservation.model_text` → `agent.py:361` 的 `{"role":"tool","content":…}`。
    **模型看见的是 `model_content`**，`display_content` 走界面、
    `audit_metadata` 是独立字段，两者都不能抓（5.18 / 5.31 / 5.47 同形）。

    旧后端直接返回 dict，那时没有这层包装 —— 所以不认识就原样返回。
    """
    mc = getattr(result, "model_content", None)
    return result if mc is None else mc

def capture(repo: Path) -> dict:
    sys.path.insert(0, str(repo))
    from backend.agent.learning.evidence_store import LearningEvidenceStore  # noqa: PLC0415
    from backend.agent.learning.learning_state_service import LearningStateService  # noqa: PLC0415
    from backend.agent.memories.kg_loader import load_into_store  # noqa: PLC0415
    from backend.agent.memories.knowledge_graph import KnowledgeGraphStore  # noqa: PLC0415
    from backend.agent.memories.mastery_store import MasteryStore  # noqa: PLC0415
    from backend.agent.tools.context import (  # noqa: PLC0415
        AgentRuntimeDependencies,
        ToolExecutionContext,
    )
    from backend.agent.tools.bootstrap import register_builtin_tools  # noqa: PLC0415
    from backend.agent.workspaces.capability_runtime import CapabilityRuntime  # noqa: PLC0415
    from backend.core.router.models import ResourceScope, WorkspaceRoute  # noqa: PLC0415

    # 后端重构后工具注册不再是 import 副作用，要显式调用，
    # 否则 ScopedToolView 编出来是空的（capture_memory_tools.py 同款，f3b8c15 踩过）。
    register_builtin_tools()

    tmp = Path(tempfile.mkdtemp(prefix="esa_learn_"))
    kg = KnowledgeGraphStore(tmp / "kg.db")
    n_points, n_edges = load_into_store(kg)  # 真实知识图谱，不是造的
    mastery = MasteryStore(tmp / "mastery.db")
    evidence = LearningEvidenceStore(tmp / "evidence.db")

    for kp_id, ok, bad in SEED_PRACTICE:
        for _ in range(ok):
            mastery.record_answer(user_name=USER, kp_id=kp_id, correct=True)
        for _ in range(bad):
            mastery.record_answer(user_name=USER, kp_id=kp_id, correct=False)

    scope = ResourceScope(metadata={"conversation_id": "c1"})
    route = WorkspaceRoute(
        workspace_type="learning",
        agent_profile_id="learning.v1",
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}),
        prompt_key="learning.v1",
        profile_policy="learning.profile.v1",
        memory_policy_id="learning.memory.v1",
        resource_scope=scope,
        action_policy="learning.actions.v1",
    )

    def ctx_for(mode: str):
        return ToolExecutionContext(
            user_id=USER,
            conversation_id="c1",
            workspace_route=route,
            authorized_resources=scope,
            conversation_mode=mode,
            runtime_dependencies=AgentRuntimeDependencies(
                knowledge_graph_store=kg,
                mastery_store=mastery,
                learning_evidence_store=evidence,
                learning_state_service=LearningStateService(
                    kg_store=kg, mastery_store=mastery, evidence_store=evidence
                ),
            ),
            request_id="r1",
            username=USER,
            total_weeks=18,
        )

    runtime = CapabilityRuntime()

    def bind(mode: str):
        """编一份该模式下的真实能力视图再绑上下文 —— 与线上同一条路径。"""
        view = runtime.compile(
            skill_scopes=SCOPES,
            tool_scopes=SCOPES,
            profile_fingerprint="capture.learning",
            policy_versions=("capture.v1",),
            conversation_mode=mode,
            has_research_project=False,
            has_attachments=False,
        )
        return view.bind(ctx_for(mode))

    calls: list[dict] = []

    def run(mode: str, name: str, branch: str = "", **args):
        """跑一次**模型真正走的那一层**。

        ⚠️ 别改回 `execute_learning_tool` —— 那比这里低一层，报错路径上
        它抛异常而这一层返回 dict，两者是两种东西（见文件头）。
        真抛穿到这里的异常仍然如实记下来：那是线上会把整轮 run 打崩的证据。
        """
        entry: dict = {"mode": mode, "tool": name, "arguments": args}
        if branch:
            # 同一个工具的不同分支要能分别比对（记忆侧同款）——
            # 只比第一个返回值，等于报错分支从来没被校验过。
            entry["branch"] = branch
        try:
            entry["result"] = _model_projection(asyncio.run(bind(mode).execute(name, args)))
        except Exception as exc:  # noqa: BLE001
            entry["raises"] = {"type": type(exc).__name__, "message": str(exc)}
        calls.append(entry)
        return entry.get("result")

    # ---- normal：八个工具各跑一次，覆盖有记录/无记录两种 ----
    run("normal", "recommend_practice", course="操作系统", weeks_to_exam=2)
    run("normal", "recommend_practice", course="不存在的课", weeks_to_exam=2)
    run("normal", "get_mastery_report", course="操作系统")
    run("normal", "get_mastery_report")
    run("normal", "get_mastery_level", kp_id="进程调度")
    # ⚠️ 这里原来传的是 "从没练过的知识点"，本意是抓「无记录」分支。
    # 但它压根不是知识图谱里的知识点，后端在 _canonical_kp_id 就先报错了 ——
    # 抓到的是**报错分支**，而「无记录」分支一次都没抓到过（低一层时表现为 raises，
    # 更看不出来）。换成真实存在但没练过的知识点，两种分支才各归各位。
    # ⚠️ 这个知识点要同时满足两个条件，换的时候两边都要看：
    #   · 在真实知识图谱里（否则走的是 unknown_kp 那一支）
    #   · 在 fixtures 的确定性画像里**也**没有记录（`load_states` 里查不到）
    # 否则契约测试比的是两边的**不同分支**，会报一堆假差异。
    run("normal", "get_mastery_level", branch="no_record", kp_id="队列")
    run("normal", "get_weak_prerequisites", kp_id="死锁")
    run("normal", "get_review_timing", kp_id="进程调度")
    run("normal", "record_answer", kp_id="进程调度", correct=True)
    run(
        "normal", "record_learning_evidence",
        kp_id="进程调度", activity_type="practice", correct=True,
        independent=True, hint_level=0,
    )
    run("normal", "get_learning_evidence_summary")

    # ---- 报错分支：模型看见的是 dict，不是异常（2026-08-19 补）----
    # 这三条都是**线上真会发生**的：
    #   · kp_id 传英文/拼音  —— 后端 schema 只写「知识点 id」，没说是中文 canonical id，
    #     基线里 L3 的参数错误 4/4 全是这个原因（交接文档「给别人的两条反馈」）
    #   · kp_id 传空串      —— 用户没说清知识点时模型容易漏填
    #   · weeks_to_exam 为负 —— 用户说「考试已经过了」时照做的结果
    run("normal", "get_mastery_level", branch="unknown_kp", kp_id="binary tree traversal")
    run("normal", "get_mastery_level", branch="empty_kp", kp_id="")
    run("normal", "recommend_practice", branch="negative_weeks",
        course="操作系统", weeks_to_exam=-2)

    # ---- isolated / no_write：阻断分支的真实形状 ----
    # 我们原来的复刻给阻断载荷加了一堆字段（user_name/course/count/...），
    # 而后端真实只有三个键。这里把真相钉下来。
    for mode in ("isolated", "no_write"):
        run(mode, "recommend_practice", course="操作系统", weeks_to_exam=2)
        run(mode, "get_mastery_report", course="操作系统")
        run(mode, "record_answer", kp_id="进程调度", correct=True)
        run(mode, "record_learning_evidence", kp_id="进程调度", activity_type="practice", correct=True)

    return {"calls": calls, "kg": {"points": n_points, "edges": n_edges}}


def shape(value, depth: int = 0):
    """把返回值抽象成结构描述：只留键名和类型，丢掉具体数值。"""
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def main() -> int:
    ap = argparse.ArgumentParser(description="抓学情工具真实返回结构")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        captured = capture(backend.path)
        for c in captured["calls"]:
            if "result" in c:
                c["shape"] = shape(c["result"])

        out_path = Path(args.out) if args.out else OUT
        payload = {
            "_meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "note": (
                    "由 dataset/tools/capture_learning_tools.py 在临时 SQLite 上跑真实 "
                    "execute_learning_tool 产出，禁止手改。"
                    "⚠️ result 里的数值**不是逐日可复现的**（apply_evidence 带时间衰减），"
                    "所以数据生成一律以 esa/fixtures.py 的确定性取值为准；"
                    "本文件的权威部分是 `shape`（结构），由 test_fixture_contract.py 校验。"
                ),
                "knowledge_graph": captured["kg"],
            },
            "calls": captured["calls"],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        print(f"\n抓到 {len(captured['calls'])} 次真实调用 → {backend_repo.display_path(out_path, ROOT)}")
        print(f"  来源：{backend.describe()}")
        print(f"  知识图谱：{captured['kg']['points']} 个知识点 / {captured['kg']['edges']} 条依赖边")
        for c in captured["calls"]:
            r = c.get("result")
            desc = (
                sorted(r) if isinstance(r, dict)
                else f"list[{len(r)}]" if isinstance(r, list)
                else c.get("raises", "?")
            )
            print(f"  [{c['mode']:8}] {c['tool']:28} → {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
