# backend/scripts/dataset/generators/gen_external.py

"""外部工具生成器：arxiv_search / get_time / get_weather / web_search。

四个工具性质不同，处理方式也不同：
  arxiv_search  观测值是真实论文（data/cache/arxiv_real.json），绝不编造
  get_time      后端是纯函数，可完全复刻
  get_weather   后端是硬编码桩，可完全复刻（但因此只能训"何时该调"）
  web_search    没有真实 SearXNG，只做错误恢复样本；报错文案逐字取自后端源码

顺带补上目前为 0 的 RECOVER_TOOL_ERROR 类。

用法：
    python3 dataset/generators/gen_external.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa import fixtures  # noqa: E402
from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402
from esa.tools_exec import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/external_tools.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/external.jsonl"
SOURCE = "gen_external.py"

SYSTEM = (
    "你是 ESA 学习辅助 Agent，帮助计算机专业学生学习与科研。"
    "需要实时信息或外部资料时调用相应工具；课本上就有的基础概念直接讲解，不要检索。"
    "工具失败时如实说明，不要用猜测代替检索结果。"
)


def mk(sid, tpl, category, tools, turns, version, rng, all_names, review=False, ask_for=()):
    """处理 `mk` 相关逻辑。

    Args:
        sid: object => `sid` 参数。
        tpl: object => `tpl` 参数。
        category: object => `category` 参数。
        tools: object => 可用工具列表。
        turns: object => `turns` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        review: object => `review` 参数。
        ask_for: object => `ask_for` 参数。

    Returns:
        object => 处理结果。
    """
    return Sample(
        id=sid, template_id=tpl, category=category, schema_version=version,
        system=system_for(turns), tool_names=pick_tool_names(tools, all_names, rng),
        source=SOURCE, needs_review=review, turns=turns, ask_for=list(ask_for),
    )


def _arxiv_answer(result: dict) -> str:
    """处理 `_arxiv_answer` 相关逻辑。"""
    rs = result["results"]
    lines = [f"在 arXiv 上按「{result['query']}」检索到 {result['total_results']} 篇，"
             f"这里挑 {len(rs)} 篇比较相关的：\n"]
    for i, r in enumerate(rs, 1):
        who = "、".join(r["authors"][:3]) + ("等" if len(r["authors"]) > 3 else "")
        lines.append(f"{i}. **{r['title']}**（{r['arxiv_id']}，{r['primary_category']}）\n"
                     f"   {who}｜{r['arxiv_url']}")
    lines.append("\n需要我把某一篇的摘要展开讲讲吗？")
    return "\n".join(lines)


def gen_arxiv(cfg, version, rng, all_names, out):
    """处理 `gen_arxiv` 相关逻辑。

    Args:
        cfg: object => `cfg` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        out: object => `out` 参数。
    """
    for group in ("正例", "按作者"):
        for i, item in enumerate(cfg["arxiv_search"][group]):
            args = {"query": item["query"], "max_results": 3}
            if item.get("search_field"):
                args["search_field"] = item["search_field"]
            try:
                result = execute("arxiv_search", args)
            except Exception as exc:  # noqa: BLE001
                print(f"    ⚠️  arxiv_search({args}) 失败，已跳过：{exc}")
                continue
            out.append(mk(
                f"arxiv_{group}_{i:03d}", f"arxiv__{group}__{item['query']}",
                "single_tool_call", ["arxiv_search", "web_search"],
                [Turn(role="user", content=item["zh"]),
                 Turn(role="tool_call", calls=[ToolCall("arxiv_search", args)]),
                 Turn(role="tool_result", results=[ToolResult("arxiv_search", result)]),
                 Turn(role="assistant", content=_arxiv_answer(result))],
                version, rng, all_names))

    # 课本概念不该去检索前沿论文
    replies = {
        "什么是二叉搜索树": "二叉搜索树的定义是：左子树所有结点小于根，右子树所有结点大于根，且左右子树也都是二叉搜索树。一个很有用的推论是它的中序遍历必然有序。",
        "TCP 三次握手的过程是什么": "客户端发 SYN，服务端回 SYN-ACK，客户端再回 ACK，双方进入 ESTABLISHED。三次是必要的：两次握手之后服务端无法确认自己的 SYN-ACK 是否送达，也就确认不了客户端的接收能力。",
        "快速排序怎么实现": "选一个基准元素做 partition，把小于它的放左边、大于的放右边，然后对两侧递归。关键在 partition 的写法和基准的选取——固定选首元素在有序输入上会退化。",
        # 别只写「最优子结构 + 无后效性」：漏掉重叠子问题，等于漏掉 DP 区别于分治的地方。
        "帮我讲讲动态规划的基本思想": "三个要素：最优子结构（大问题的最优解由子问题的最优解组成）、重叠子问题（同一个子问题被反复求解，所以要把结果存下来，这正是 DP 区别于分治的地方）、无后效性（状态一旦确定，后续决策不依赖到达它的路径）。做题时先定状态再写转移。",
        "分页和分段有什么区别": "分页大小固定、对用户透明、解决外碎片；分段长度可变、对用户可见、按逻辑模块划分。记住「页是物理的、段是逻辑的」。",
    }
    for i, q in enumerate(cfg["arxiv_search"]["混淆_不该检索"]):
        out.append(mk(
            f"arxiv_neg_{i:03d}", f"arxiv__不该检索__{i:03d}", "hard_negative",
            ["arxiv_search", "web_search", "retrieve_knowledge"],
            [Turn(role="user", content=q), Turn(role="assistant", content=replies[q])],
            version, rng, all_names, review=True))


def gen_time(cfg, version, rng, all_names, out):
    """处理 `gen_time` 相关逻辑。

    Args:
        cfg: object => `cfg` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        out: object => `out` 参数。
    """
    result = execute("get_time", {})
    for i, q in enumerate(cfg["get_time"]["正例"]):
        out.append(mk(
            f"time_{i:03d}", f"time__正例__{i:03d}", "single_tool_call",
            ["get_time", "get_review_timing"],
            [Turn(role="user", content=q),
             Turn(role="tool_call", calls=[ToolCall("get_time", {})]),
             Turn(role="tool_result", results=[ToolResult("get_time", result)]),
             Turn(role="assistant", content=f"当前时间是 {result}（UTC）。")],
            version, rng, all_names))

    replies = [
        "这个因人而异，没有统一答案。多数人上午和傍晚注意力较好，但更重要的是固定时段形成习惯。你想让我帮你按现有安排排个练习计划吗？",
        "常见的做法是二八开：八成时间练薄弱点，两成时间维持已掌握的。具体怎么分要看你距考试还有多久。",
        "取决于题型和熟练度。选择填空通常几分钟，算法设计题可能要半小时以上。建议按知识点而不是按时间来计量进度。",
    ]
    for i, q in enumerate(cfg["get_time"]["混淆_不该调"]):
        out.append(mk(
            f"time_neg_{i:03d}", f"time__不该调__{i:03d}", "hard_negative",
            ["get_time", "recommend_practice"],
            [Turn(role="user", content=q), Turn(role="assistant", content=replies[i])],
            version, rng, all_names))


def gen_weather(cfg, version, rng, all_names, out):
    """处理 `gen_weather` 相关逻辑。

    Args:
        cfg: object => `cfg` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        out: object => `out` 参数。
    """
    w = cfg["get_weather"]
    for i, (city, p) in enumerate((c, p) for p in w["正例"] for c in w["cities"]):
        result = execute("get_weather", {"city": city})
        out.append(mk(
            f"weather_{i:03d}", f"weather__正例__{city}", "single_tool_call",
            ["get_weather"],
            [Turn(role="user", content=p.format(city=city)),
             Turn(role="tool_call", calls=[ToolCall("get_weather", {"city": city})]),
             Turn(role="tool_result", results=[ToolResult("get_weather", result)]),
             Turn(role="assistant", content=f"{result}。")],
            version, rng, all_names))
    for i, q in enumerate(w["缺参数"]):
        out.append(mk(
            f"weather_ask_{i:03d}", f"weather__缺参数__{i:03d}", "clarify",
            ["get_weather"],
            [Turn(role="user", content=q), Turn(role="assistant", content=w["ask"])],
            version, rng, all_names, ask_for=["city"]))


def gen_web_search_errors(cfg, version, rng, all_names, out):
    """只做错误恢复。失败观测由 fixtures 按**实测**的执行器返回值产出。

    ⚠️ 2026-08-15 重写。后端 `1b64473` 把 web_search 换成 You.com MCP 适配器：
      · 原来那 5 条 SearXNG 文案在后端**一条都不剩**了
      · 观测从字符串 `"[Error]: …"` 变成了 dict
        `{"ok": false, "error": "tool_execution_error", "tool": "web_search", "detail": …}`
        （`capability_runtime.py` 给 web_search 开了专用分支，RuntimeError 在 :165 被接住）

    现在线上真实可达的只有「MCP 没配好」这一种，所以五条样本共用同一个失败观测，
    靠不同的查询意图和不同的恢复话术保持多样性 —— 而不是编五种不同的报错。
    """
    ws = cfg["web_search"]
    result = fixtures.web_search_failed()
    for i, item in enumerate(ws["正例查询"]):
        tmpl = ws["恢复话术"][i % len(ws["恢复话术"])]
        args = {"query": item["query"]}
        out.append(mk(
            f"web_err_{i:03d}", f"web__error__{i:03d}", "tool_error",
            ["web_search", "arxiv_search"],
            [Turn(role="user", content=item["zh"]),
             Turn(role="tool_call", calls=[ToolCall("web_search", args)]),
             Turn(role="tool_result",
                  results=[ToolResult("web_search", result, is_error=True)]),
             Turn(role="assistant", content=tmpl.format(err=result["detail"]))],
            version, rng, all_names))


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260810)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    out: list[Sample] = []

    gen_arxiv(cfg, version, rng, all_names, out)
    gen_time(cfg, version, rng, all_names, out)
    gen_weather(cfg, version, rng, all_names, out)
    gen_web_search_errors(cfg, version, rng, all_names, out)

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {cat:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
