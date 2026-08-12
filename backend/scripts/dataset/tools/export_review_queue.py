"""把 `needs_review` 的样本导成一份能让人坐下来审的清单。

为什么需要它
------------
`needs_review=true` 标记的是**机器验不了**的内容：概念讲解的正文、教学话术、
事实性表述。校验器能查 JSON 合不合法、参数合不合 schema、复杂度有没有登记，
查不出「这段推导是不是把最好情况当成了平均情况」——
组长审出来的快排那条就是这么漏过去的：它一直挂着 needs_review，只是没人真的审。

标记了却没人审，等于没标记。所以把它导成一份带上下文、带检查要点的 markdown，
让人能一条条过，而不是自己去 grep jsonl。

用法
----
    python3 dataset/tools/export_review_queue.py
    python3 dataset/tools/export_review_queue.py --out somewhere.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa import review  # noqa: E402
from esa.ir import ROLE_ASSISTANT, ROLE_USER, iter_ir_files, load_samples  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "dataset/docs/待人工复核.md"

# 按来源给出「这一条该重点看什么」。审的人最需要的不是「请审核」，是「往哪儿看」。
FOCUS = {
    "gen_calculators.py": [
        "复杂度断言：最好 / 平均 / 最坏有没有混为一谈（快排那条就栽在这儿）",
        "推导过程是不是真的成立，别只看结论对",
        "LaTeX 渲染出来是否正常，`$` 有没有配对",
    ],
    "gen_negatives.py": [
        "这句话是不是**真的**不该调任何工具 —— 别是「该调另一个工具」被标成了不调用",
        "讲解内容有无事实错误",
    ],
    "gen_skills_rag.py": [
        "回答有没有把 Skill 正文照抄出来（system prompt 要求「按正文执行」而不是复述）",
        "有没有编造不存在的流程或来源",
    ],
    # ⚠️ 这组里**没有**带论文信息的样本。原先这里写着「核对论文标题/作者/编号」，
    # 而队列里 gen_external 的条目全是「不该检索」负样本，一篇论文都没有 ——
    # 让人去核对一个不存在的东西，等于这组根本没有检查要点。
    # 17 条 arxiv 正例确实带真实论文元数据，但它们是从 arxiv_real.json 程序化渲染的
    # （`gen_external.py:_arxiv_answer`），编不出来，所以不进人工队列。
    "gen_external.py": [
        "这句话是不是真的**不该检索** —— 课本概念直接讲 vs 前沿论文要查，边界画在哪",
        "概念讲解部分的事实准确性",
    ],
}
DEFAULT_FOCUS = ["事实准确性", "有没有编造工具返回值里没有的内容"]


def fence_for(text: str) -> str:
    """包住正文的围栏，必须比正文里最长的那串反引号更长。

    `hardneg_005` 的讲解正文里嵌了一个 ```python 代码块。用固定的三反引号去包，
    正文里那一行会把外层围栏提前关掉 —— 之后整份文档的代码块全部错位，
    审的人看到的排版和数据里的内容对不上，而且不报错。
    """
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def main() -> int:
    ap = argparse.ArgumentParser(description="导出待人工复核清单")
    ap.add_argument("--ir-dir", default=str(ROOT / "dataset/data/ir"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    all_samples = [s for f in iter_ir_files(args.ir_dir) for s in load_samples(f)]
    ledger = review.load_ledger()
    review.assert_no_stale(all_samples, ledger)
    samples = review.pending(all_samples, ledger)
    samples.sort(key=lambda s: (s.source, s.id))
    n_cleared = sum(1 for s in all_samples if s.needs_review and s.id in ledger)

    by_src = Counter(s.source for s in samples)
    lines = [
        "# 待人工复核清单",
        "",
        f"> 共 **{len(samples)} 条**。这些是**机器验不了**的内容：概念讲解正文、教学话术、事实表述。",
        "> 校验器能查结构、参数、复杂度登记，查不出「这段推导对不对」。",
        "",
        "**标记了却没人审，等于没标记。** 组长审出的快排那条（把最好情况的递推式",
        "当成平均情况的推导）就一直挂着 `needs_review`，只是没人真的看过。",
        "",
        "**发现问题不要直接改 jsonl** —— 数据是从种子库生成的，手改下次重跑就没了。",
        "改 `dataset/seeds/` 里对应的那一条，再重跑生成器。",
        "",
        "**审完一条怎么放行**：在 `dataset/seeds/reviewed.yaml` 里登记它的 id（要签名字、",
        "写清你看了什么），重跑本工具它就从这份清单消失，重跑 `esa.evalset` 它就回到训练集。",
        "下面方框里的勾只是你自己看到哪儿了的书签 —— **打勾不放行，登记才放行**。",
        f"当前已登记放行 **{n_cleared}** 条。",
        "",
        "## 按来源分布",
        "",
        "| 来源 | 条数 |",
        "|---|---:|",
    ]
    for src, n in by_src.most_common():
        lines.append(f"| `{src}` | {n} |")
    lines.append("")

    cur = None
    for s in samples:
        if s.source != cur:
            cur = s.source
            lines += ["---", "", f"## 来自 `{cur}`", "", "**这一组重点看：**", ""]
            lines += [f"- {f}" for f in FOCUS.get(cur, DEFAULT_FOCUS)]
            lines.append("")

        user = next((t.content for t in s.turns if t.role == ROLE_USER), "")
        answer = next((t.content for t in reversed(s.turns)
                       if t.role == ROLE_ASSISTANT and t.content), "").strip()
        fence = fence_for(answer)
        lines += [
            f"### [ ] `{s.id}`",
            "",
            f"- 类别：`{s.category}`　知识点：`{s.topic or '—'}`　模板：`{s.template_id}`",
            "",
            f"**用户**：{user}",
            "",
            "**回答**：",
            "",
            f"{fence}markdown",
            answer,
            fence,
            "",
        ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(samples)} 条待复核 → {out.relative_to(ROOT)}")
    for src, n in by_src.most_common():
        print(f"  {src:24s}{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
