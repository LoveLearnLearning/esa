"""按 workspace scope 导出工具 schema —— **取代交接文档里那句「cp 过来」**。

    python3 dataset/tools/capture_tool_schemas.py

为什么不能再 cp
---------------
`backend/agent/tools/tool_schemas.json` 曾经**恰好**等于学习空间的工具集，
所以一直是直接 cp。2026-08-14 的 `abc0362` 之后它变成了**全局目录**：
32 个工具，含科研 3 个（`start_frontier_tracking` 等）和教学 1 个
（`get_teaching_context`）。

继续 cp 会把科研和教学工具喂给学习空间的模型 —— 而这**不会有任何东西报错**，
校验器只查 schema_version 一致、参数合法，不查"这个工具在这个空间里该不该出现"。

真正的判据在后端自己的 `agent/tools/catalog.py`：
每个工具有 scope（common / learning / research / teaching），
而学习空间的路由是 `tool_scopes = {"common", workspace}`
（`core/router/workspace_profiles.py:18`，`core/web/routers/learning.py:52` 也明写）。

所以本脚本 = 跑后端真实注册表 → 用后端真实的 `tool_scope()` 过滤
→ **再过一道后端真实的 `compact_tool_schema()` 投影** → 落盘。

为什么还要 compact 那一步（2026-08-25 补）
------------------------------------------
上游 08-24 给运行时加了紧凑投影：`ScopedToolView.compile()` 对每个 schema 调
`compact_tool_schema()`，**换掉工具描述、并删掉几乎全部参数描述**
（`agent/tools/catalog.py:106-136`）。也就是说 `tr.schemas` 里那份**不是**模型
看见的那一份。实测差别不小：

    retrieve_knowledge  tr.schemas : 从知识库检索紧凑证据。……必须遵守每条结果的 citation_mode……
    retrieve_knowledge  模型看见的 : 检索公共课程知识库以取得回答证据。

只做 scope 过滤、不做 compact，就是**又抓低了一层**（5.18 / 5.24 同款）——
而且照旧不会有任何东西报错。所以这一步不是可选项。

⚠️ 上游同时把本脚本的 scope 过滤**整段删掉**了，改成导出全部 33 个工具，
理由是「过滤由 ScopedToolView 每轮完成，数据集不该维护第二份合同」。
那个理由对**运行时快照**成立，对**训练数据**不成立：样本里的工具清单必须是
模型在那一轮真能看见的集合。上游按删掉过滤的版本重生成过一次我们的数据，
结果学习空间的样本里出现了 `start_frontier_tracking`（科研工具）——
这正是本文件开头那段要防的事。因此：**compact 采纳，删过滤不采纳。**

附件工具为什么排除
------------------
5 个 `parse_*_attachment` 属于 common scope，但它们是**按轮动态注入**的：
`_attachment_inventory` 在没有 attachment_ids 时返回 `("", None)`
（`core/web/routers/chat.py:92-99`），无附件的对话里根本不会出现。
我们本轮不覆盖附件路径（组长定的增量策略），所以排除；
`--with-attachments` 可以带上，将来要造附件样本时用。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_repo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dataset/schemas/tool_schemas.json"
META = ROOT / "dataset/schemas/tool_schemas_meta.json"

WORKSPACE = "learning"
ATTACHMENT_PREFIX = "parse_"
ATTACHMENT_SUFFIX = "_attachment"


def capture(repo: Path, with_attachments: bool) -> tuple[list, dict]:
    sys.path.insert(0, str(repo))
    from backend.agent.tools import tr  # noqa: PLC0415
    from backend.agent.tools.bootstrap import register_builtin_tools  # noqa: PLC0415

    register_builtin_tools()
    from backend.agent.tools.catalog import tool_scope  # noqa: PLC0415

    # 紧凑投影是 2026-08-24 上游给运行时加的（见文件头）。老后端没有这个函数，
    # 取不到就退回恒等投影 —— 但要留声，否则将来对着老 clone 抓一次，
    # 抓出来的又是模型看不见的那一层，而且悄无声息。
    try:
        from backend.agent.tools.catalog import compact_tool_schema  # noqa: PLC0415
    except ImportError:
        print("⚠️ 这个后端版本没有 compact_tool_schema()，"
              "导出的是未投影的 schema —— 确认它确实早于上游 2026-08-24 那次改动。")
        def compact_tool_schema(schema):  # noqa: ANN001, ANN202
            return schema

    allowed = {"common", WORKSPACE}
    kept, dropped = [], {}
    for schema in tr.schemas:
        name = (schema.get("function", schema))["name"]
        scope = tool_scope(name)
        is_attachment = name.startswith(ATTACHMENT_PREFIX) and name.endswith(ATTACHMENT_SUFFIX)
        if scope not in allowed:
            dropped.setdefault(f"scope={scope}", []).append(name)
            continue
        if is_attachment and not with_attachments:
            dropped.setdefault("按轮动态注入的附件工具", []).append(name)
            continue
        # 投影顺序照抄运行时：先按 scope 过滤，再 compact（catalog.py:238-247）。
        kept.append(compact_tool_schema(schema))

    kept.sort(key=lambda s: (s.get("function", s))["name"])

    # 交叉验证：拿后端真实的 `ScopedToolView.compile()` 编一份学习空间视图，
    # 要求和我们手工过滤出来的**逐字节相同**。这样「我们复刻的过滤规则」
    # 就不再是手抄的了 —— 后端哪天改了 scope 或投影，这里当场炸，
    # 而不是等到数据里出现一个线上不存在的工具（5.16 那个形状）。
    try:
        from backend.agent.tools.catalog import ScopedToolView  # noqa: PLC0415
    except ImportError:
        pass
    else:
        excluded = frozenset(
            name for name in tr.registered_tools
            if name.startswith(ATTACHMENT_PREFIX) and name.endswith(ATTACHMENT_SUFFIX)
        ) if not with_attachments else frozenset()
        runtime_view = ScopedToolView.compile(
            tr, frozenset(allowed), excluded_names=excluded)
        ours = json.dumps(kept, ensure_ascii=False, sort_keys=True)
        theirs = json.dumps(list(runtime_view.schemas), ensure_ascii=False, sort_keys=True)
        if ours != theirs:
            our_names = {(s.get("function", s))["name"] for s in kept}
            rt_names = {(s.get("function", s))["name"] for s in runtime_view.schemas}
            raise SystemExit(
                "❌ 与后端运行时视图对不上，别拿这份产物去生成数据。\n"
                f"   我们多出来：{sorted(our_names - rt_names)}\n"
                f"   运行时多出来：{sorted(rt_names - our_names)}\n"
                "   名字一致却仍不等 = 投影规则变了（compact_tool_schema）。"
            )

    return kept, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description="按 workspace scope 导出工具 schema")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    ap.add_argument("--download", action="store_true")
    ap.add_argument(
        "--with-attachments", action="store_true",
        help="把 5 个附件工具也带上（本轮不需要，见文件头说明）",
    )
    args = ap.parse_args()

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        kept, dropped = capture(backend.path, args.with_attachments)
        out_path = Path(args.out) if args.out else OUT
        # ⚠️ 元信息必须跟着 `--out` 走。
        # 2026-08-18 之前它写死成 META，于是**任何带 --out 的调用都会污染工作副本**：
        # `check_backend_updates.py` 每次都用 --out 指到临时目录跑这个脚本
        # （它的文档字符串还写着「不覆盖 data/cache/」），结果每查一次后端更新，
        # 就把 tool_schemas_meta.json 的 schema_version / source_repo
        # 盖成"被检查的那个 commit"的值 —— 而 tool_schemas.json 本身没动。
        # 后果是 meta 说 abc60289、数据里却是 289b35e2，两边对不上而没人报错。
        meta_path = (out_path.parent / "tool_schemas_meta.json"
                     if args.out else META)
        body = json.dumps(kept, ensure_ascii=False, indent=2) + "\n"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")

        # schema_version 由 esa.ir.compute_schema_version 从 schemas 内容算，
        # 不是文件字节的哈希 —— 这里跟它保持一致，免得元信息里记了个对不上的数。
        sys.path.insert(0, str(ROOT / "dataset"))
        from esa.ir import compute_schema_version  # noqa: PLC0415

        version = compute_schema_version(kept)
        meta_path.write_text(
            json.dumps(
                {
                    "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source": "github.com/LoveLearnLearning/esa",
                    "source_repo": backend.describe(),
                    "workspace": WORKSPACE,
                    "tool_scopes": sorted({"common", WORKSPACE}),
                    "schema_version": version,
                    "with_attachments": args.with_attachments,
                    "kept": [(s.get("function", s))["name"] for s in kept],
                    "dropped": dropped,
                    "note": (
                        "由 dataset/tools/capture_tool_schemas.py 用后端真实 "
                        "catalog.tool_scope() 过滤 + compact_tool_schema() 投影产出，"
                        "并与 ScopedToolView.compile() 逐字节交叉验证过；禁止手改，"
                        "也不要直接 cp backend/agent/tools/tool_schemas.json —— "
                        "那份是未过滤、未投影的全局目录，含科研/教学工具。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print(f"\n导出 {len(kept)} 个工具 → {backend_repo.display_path(out_path, ROOT)}")
        print(f"  来源：{backend.describe()}　workspace={WORKSPACE}")
        for reason, names in sorted(dropped.items()):
            print(f"  排除（{reason}）：{len(names)} 个 {sorted(names)}")
        print(f"  元信息 → {backend_repo.display_path(meta_path, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
