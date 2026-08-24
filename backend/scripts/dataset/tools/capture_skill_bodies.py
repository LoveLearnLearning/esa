# backend/scripts/dataset/tools/capture_skill_bodies.py

"""抓取 `load_skill` 的**线上真实返回值**，落成缓存。

为什么要有这个脚本
------------------
`data/cache/skills_bodies.json` 原本存的是 `skills/*.md` 的**整份文件文本**（含 frontmatter），
再由 `gen_skills_rag.py` 用自己写的正则 `re.split(r"^---\\s*$", ...)` 把 frontmatter 剥掉。

但线上 `load_skill()` 返回的是 `SkillDefinition.body`
（`backend/agent/tools/skills.py:246-252` → `_parse_skill` 在 `skills.py:56` 做
`text[4:].split("\\n---\\n", 1)` 然后 `body.strip()`）。

⚠️ **如实说明**：这两套剥法在当前 11 份 Skill 上**逐字节一致**，实测过。
所以改成执行**并没有修正任何错误数据**，它修的是隐患 —— 正文里哪天出现一行 `---`
（Markdown 分隔线，写文档时很自然），正则会从那里切开，而后端不会。
到那时数据会悄悄错，且没有任何校验拦得住，跟 5.10 / 5.12 一模一样。

顺带解决的真问题是**覆盖面**：旧缓存是 2026-08-10 手工抓的 9 份，
后端此后新增了 adaptive_practice / math_problem_solving，并改写了
homework_review / profile_personalization 两份正文 —— 手工抓的东西没人会想起来重抓。

用法
----
    python3 dataset/tools/capture_skill_bodies.py                 # 默认用本地 ~/esa
    python3 dataset/tools/capture_skill_bodies.py --repo <路径>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "dataset"))
import backend_repo  # noqa: E402
from esa.cache_contract import skill_source_hashes  # noqa: E402

OUT = ROOT / "dataset/data/cache/skills_bodies.json"


def capture(repo: Path) -> dict:
    """跑真实 load_skill()，返回落盘用的全部字段。"""
    sys.path.insert(0, str(repo))
    try:
        from backend.agent.tools.bootstrap import register_builtin_tools  # noqa: PLC0415
        from backend.agent.tools.skills import (  # noqa: PLC0415
            build_skills_context, list_skill_definitions, list_skills,
            list_skills_detail, load_skill,
        )
    except ImportError as exc:
        raise SystemExit(
            f"无法 import 后端 skills 模块：{exc}\n"
            "它会连带 import 整个 tool registry，缺依赖就先 pip install。"
            "注意不要改用本地复刻顶替 —— 那正是这个脚本要修掉的问题。"
        ) from exc

    register_builtin_tools()
    files = list_skills()  # 已排除 SKILLS.md（skills.py:120-126）
    print(f"后端 skills 目录下 {len(files)} 个 Skill（SKILLS.md 不算）：")

    detail = dict(list_skills_detail())
    bodies = {name: load_skill(name) for name in detail}

    # 索引里的顺序不是文件名序，是 (-priority, name)（skills.py:196-206）。
    # 「我目前可用的是：前几个」这类话术照着它写，所以顺序要一并钉住。
    index_block = build_skills_context()
    index_order = [
        line.removeprefix("- ").split(":", 1)[0].strip()
        for line in index_block.splitlines()
        if line.startswith("- ")
    ]
    candidates = {
        skill.name for skill in list_skill_definitions() if not skill.autoload
    }
    assert set(index_order) == candidates, (
        f"索引里的候选 Skill 名对不上：{index_order} vs {sorted(candidates)}"
    )

    for name in sorted(bodies):
        body = bodies[name]
        assert not body.startswith("---"), f"{name} 的返回值仍带 frontmatter，剥法对不上"
        print(f"  {name:26s} {len(body):5d} 字符")

    # 失败文案也一并钉住：gen_skills_rag 的「不存在的 skill」那组要逐字用它
    missing_probe = "definitely_not_a_real_skill"
    not_found = load_skill(missing_probe)
    assert missing_probe in not_found, f"失败文案格式变了：{not_found!r}"
    return {
        "bodies": bodies,
        "descriptions": detail,
        "index_order": index_order,
        "skills_index_block": index_block,
        "not_found_template": not_found.replace(missing_probe, "{name}"),
    }


def main() -> int:
    """运行当前模块的命令行入口。"""
    ap = argparse.ArgumentParser(description="抓取 load_skill 的线上真实返回值")
    ap.add_argument("--repo", help="本地后端仓库副本；默认 ~/esa")
    ap.add_argument("--download", action="store_true", help="强制下载快照（抓不到本地改动，慎用）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        captured = capture(backend.path)
        bodies = captured["bodies"]
        not_found_template = captured["not_found_template"]

        payload = {
            "_meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "source_sha256": skill_source_hashes(backend.path),
                "note": (
                    "由 dataset/tools/capture_skill_bodies.py 调用后端真实 load_skill() 产出，"
                    "存的就是模型线上看到的观测值（不含 frontmatter），禁止手改"
                ),
                "not_found_template": not_found_template,
                "skill_names": captured["index_order"],
                "skills_index_block": captured["skills_index_block"],
            },
            "descriptions": captured["descriptions"],
            "bodies": bodies,
        }
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n抓到 {len(bodies)} 份 Skill 正文 → {out_path.relative_to(ROOT)}")
    print(f"  来源：{backend.describe()}")
    print(f"  未知 skill 的失败文案：{not_found_template!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
