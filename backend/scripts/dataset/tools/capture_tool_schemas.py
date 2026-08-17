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

所以本脚本 = 跑后端真实注册表 → 用后端真实的 `tool_scope()` 过滤 → 落盘。

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
        kept.append(schema)

    kept.sort(key=lambda s: (s.get("function", s))["name"])
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
        body = json.dumps(kept, ensure_ascii=False, indent=2) + "\n"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")

        # schema_version 由 esa.ir.compute_schema_version 从 schemas 内容算，
        # 不是文件字节的哈希 —— 这里跟它保持一致，免得元信息里记了个对不上的数。
        sys.path.insert(0, str(ROOT / "dataset"))
        from esa.ir import compute_schema_version  # noqa: PLC0415

        version = compute_schema_version(kept)
        META.write_text(
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
                        "catalog.tool_scope() 过滤产出，禁止手改，也不要再直接 cp "
                        "backend/agent/tools/tool_schemas.json —— 那份是全局目录，"
                        "含科研/教学工具。"
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
        print(f"  元信息 → {backend_repo.display_path(META, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
