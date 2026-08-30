# backend/scripts/dataset/generators/gen_external.py

"""外部工具生成器：arxiv_search / get_time / web_search。

四个工具性质不同，处理方式也不同：
  arxiv_search  观测值是真实论文（data/cache/arxiv_real.json），绝不编造
  get_time      后端是纯函数，可完全复刻
  🪦 get_weather  上游 `c18c84e`（2026-08-28）从注册表删了它，整组已移除
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
    # 🔴 2026-08-26 重写：原来每条只有一句定义（66~101 字）。用户问的是「什么是 X」，
    # 而 system prompt 明写着「用自己的话解释概念及机制，并给出贴题例子」——
    # 旧文本连例子都没有，是在教模型违反 system prompt（4.3m 机制二）。
    # 新形态统一为三段：**机制 → 贴题例子 → 易错点**，长度随内容需要变（190~400 字不等），
    # ⚠️ 不是「凑字数」：判据是这三段在不在，不是多少字（4.3q 那条长度偏置的警告）。
    replies = {
        "什么是二叉搜索树": (
            "二叉搜索树是一棵二叉树，且对每个结点都满足：左子树里所有值比它小，右子树里所有值比它大，"
            "左右子树本身也是二叉搜索树。这个约束带来一个很有用的推论——**中序遍历的结果必然有序**。\n\n"
            "查找时从根开始，比根小就往左走、比根大就往右走，每一步都砍掉一半的候选。"
            "比如在 [1,3,4,6,7,8,10,13,14] 建成的 BST 里找 7，路径是 8 → 3 → 6 → 7，四步就到了。\n\n"
            "最容易忽略的一点：这些性质都建立在树**没退化**的前提上。"
            "按 1,2,3,4,5 这样有序插入，BST 会长成一条链，查找退化到 O(n)，"
            "和在链表里线性扫没区别。所以工程上用的是 AVL、红黑树这类会自平衡的变种。"
        ),
        "TCP 三次握手的过程是什么": (
            "客户端发 SYN（带自己的初始序号 x），服务端回 SYN-ACK（带自己的序号 y，并确认 x+1），"
            "客户端再回 ACK（确认 y+1），双方进入 ESTABLISHED。\n\n"
            "为什么必须三次，关键在于**双方都要确认对方的收发能力**。"
            "第一次让服务端知道「客户端能发」；第二次让客户端知道「服务端能收也能发」；"
            "第三次让服务端知道「客户端能收」。少了第三次，服务端就无法确认自己的 SYN-ACK 到没到，"
            "也就确认不了客户端的接收能力。\n\n"
            "举个能看出差别的场景：客户端因为网络抖动重发了一个早已失效的旧 SYN，"
            "服务端如果两次握手就直接建连，就会白白为一个根本不存在的连接占着资源；"
            "有第三次时客户端不会对这个旧连接回 ACK，服务端等不到就把它丢掉。\n\n"
            "两个常见的混淆：一是把它和四次挥手搞混——挥手要四次是因为关闭是单向的，"
            "一方没数据了不代表另一方也没有；二是以为三次握手能防伪造，"
            "实际上 SYN 洪泛攻击正是利用了「服务端在第二次之后就要分配资源等第三次」这个窗口。"
        ),
        "快速排序怎么实现": (
            "选一个基准元素做 partition，把小于它的挪到左边、大于的挪到右边，"
            "基准落到它最终该在的位置上，然后对左右两段递归。递归到长度 1 就自然有序了。\n\n"
            "以 [5,3,8,1,9,2] 取首元素 5 为基准为例：一趟 partition 之后大致是 [3,1,2] 5 [8,9]，"
            "5 已经就位，再分别对 [3,1,2] 和 [8,9] 重复同样的事。\n\n"
            "两个坑：**基准选取**——固定取首元素时，遇到本来就有序的输入每次只能切掉一个元素，"
            "复杂度从 O(n log n) 退化到 O(n²)，所以实践中用三数取中或随机选；"
            "另外快排是**不稳定**的，相等元素的相对顺序会被 partition 打乱，"
            "要稳定排序得用归并。"
        ),
        # 别只写「最优子结构 + 无后效性」：漏掉重叠子问题，等于漏掉 DP 区别于分治的地方。
        "帮我讲讲动态规划的基本思想": (
            "三个要素：**最优子结构**（大问题的最优解由子问题的最优解组成）、"
            "**重叠子问题**（同一个子问题被反复求解，所以要把结果存下来——这正是 DP 区别于分治的地方）、"
            "**无后效性**（状态一旦确定，后续决策不依赖你是怎么走到它的）。\n\n"
            "斐波那契是最直观的对照：朴素递归里 f(n-2) 会被算很多遍，是指数级；"
            "把算过的存进数组，同样的递推就降到线性。归并排序虽然也是分解子问题，"
            "但左右两半毫无重叠，所以它是分治不是 DP。\n\n"
            "做题时的顺序是**先定状态再写转移**，不要反过来。"
            "最常见的错误是状态定义漏了维度——比如背包问题只用「前 i 个物品」而漏掉「剩余容量」，"
            "转移方程就怎么写都不对。另外别把「有重叠」当成充分条件，最优子结构不成立时 DP 同样不适用。"
        ),
        "分页和分段有什么区别": (
            "分页把地址空间切成**固定大小**的页（通常 4KB），"
            "切法由硬件定，和程序的逻辑结构无关；分段按**逻辑单位**切，"
            "代码段、数据段、栈段各自一段，长度不固定，由程序结构决定。\n\n"
            "地址形式也不同：分页的逻辑地址是一维的，页号和页内偏移是同一个数拆出来的；"
            "分段是二维的，必须显式给出「段号 + 段内偏移」。"
            "举个具体的：一个 10KB 的数组在分页下会被拆到 3 个不一定相邻的页里，"
            "而在分段下它整段连续存放。\n\n"
            "碎片的类型正好相反：分页因为大小固定，页内用不满会产生**内部碎片**，但没有外部碎片；"
            "分段大小不一，段与段之间会留下**外部碎片**，需要紧凑来回收。"
            "现代系统用段页式把两者叠起来，先分段再对每段分页。"
        ),
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
    gen_web_search_errors(cfg, version, rng, all_names, out)

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {cat:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
