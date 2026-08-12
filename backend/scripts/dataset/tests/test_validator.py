"""校验器的负向测试：故意造坏数据，确认每种错误都能被抓到。

一个从不报错的校验器等于没有校验器。每加一条新检查，都要在这里补一条对应的坏样本。

    python dataset/tests/test_validator.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, ToolCall, ToolResult, Turn, load_schemas, schemas_by_name  # noqa: E402
from esa.validate import validate_sample  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS, VERSION = load_schemas(ROOT / "dataset/schemas/tool_schemas.json")
BY_NAME = schemas_by_name(SCHEMAS)


def make(**over) -> Sample:
    """一条本身完全合法的样本，测试时逐项破坏它。"""
    base = dict(
        id="t1",
        template_id="tpl",
        category="single_tool_call",
        schema_version=VERSION,
        system="你是 ESA。",
        tool_names=["calculator", "web_search"],
        turns=[
            Turn(role="user", content="算一下 2+2"),
            Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "2+2"})]),
            Turn(role="tool_result", results=[ToolResult("calculator", {"expression": "2+2", "result": 4})]),
            Turn(role="assistant", content="结果是 $4$。"),
        ],
    )
    base.update(over)
    return Sample(**base)


CASES: list[tuple[str, Sample, str]] = [
    (
        "基准样本应当通过",
        make(),
        "",
    ),
    (
        "消息数为奇数",
        make(turns=make().turns[:3]),
        "role_seq",
    ),
    (
        "工具调用后面没跟 tool_result",
        make(turns=[Turn(role="user", content="算 2+2"), Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "2+2"})])]),
        "call_result",
    ),
    (
        "调用了 schema 里不存在的工具",
        make(
            tool_names=["nonexistent_tool"],
            turns=[
                Turn(role="user", content="x"),
                Turn(role="tool_call", calls=[ToolCall("nonexistent_tool", {})]),
                Turn(role="tool_result", results=[ToolResult("nonexistent_tool", {})]),
                Turn(role="assistant", content="好的。"),
            ],
        ),
        "tool_exists",
    ),
    (
        "调用了不在本样本 tool_names 里的工具",
        make(tool_names=["web_search"]),
        "tool_visible",
    ),
    (
        "缺必填参数",
        make(
            turns=[
                Turn(role="user", content="算一下"),
                Turn(role="tool_call", calls=[ToolCall("calculator", {})]),
                Turn(role="tool_result", results=[ToolResult("calculator", {"expression": "2+2", "result": 4})]),
                Turn(role="assistant", content="结果是 $4$。"),
            ]
        ),
        "arg_schema",
    ),
    (
        "出现未知参数",
        make(
            turns=[
                Turn(role="user", content="算一下 2+2"),
                Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "2+2", "precision": 3})]),
                Turn(role="tool_result", results=[ToolResult("calculator", {"expression": "2+2", "result": 4})]),
                Turn(role="assistant", content="结果是 $4$。"),
            ]
        ),
        "arg_unknown",
    ),
    (
        "math_solver 条件必填缺 variable",
        make(
            tool_names=["math_solver"],
            turns=[
                Turn(role="user", content="求导"),
                Turn(role="tool_call", calls=[ToolCall("math_solver", {"operation": "diff", "expression": "x**2"})]),
                Turn(role="tool_result", results=[ToolResult("math_solver", {"result": "2*x"})]),
                Turn(role="assistant", content="导数是 $2x$。"),
            ],
        ),
        "arg_conditional",
    ),
    (
        "hard_negative 类别却调了工具",
        make(category="hard_negative"),
        "category_calls",
    ),
    (
        "最终回答没引用工具返回值（编造）",
        make(
            turns=[
                Turn(role="user", content="算一下 2+2"),
                Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "2+2"})]),
                Turn(role="tool_result", results=[ToolResult("calculator", {"expression": "2+2", "result": 4})]),
                Turn(role="assistant", content="结果是 $99$。"),
            ]
        ),
        "grounding",
    ),
    (
        "LaTeX 定界符不配对",
        make(
            turns=[
                Turn(role="user", content="算一下 2+2"),
                Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "2+2"})]),
                Turn(role="tool_result", results=[ToolResult("calculator", {"expression": "2+2", "result": 4})]),
                Turn(role="assistant", content="结果是 $4。"),
            ]
        ),
        "latex",
    ),
    (
        "schema 版本对不上",
        make(schema_version="deadbeef"),
        "schema_version",
    ),
    (
        "回答里混入手机号",
        make(
            turns=[
                Turn(role="user", content="算一下 2+2"),
                Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": "2+2"})]),
                Turn(role="tool_result", results=[ToolResult("calculator", {"expression": "2+2", "result": 4})]),
                Turn(role="assistant", content="结果是 $4$，有问题打 13812345678。"),
            ]
        ),
        "privacy",
    ),
]


def corpus_cases() -> list[tuple[str, bool]]:
    """语料级检查（跨样本），单条 validate_sample 查不到这些。"""
    from esa.system_prompt import COLLECT_PLACEHOLDER
    from esa.validate import (
        check_answer_polarity,
        check_error_texts_registered,
        check_negative_not_positive,
        check_exact_duplicates,
        check_clarify_contract,
        check_refusal_contract,
        check_no_collect_placeholder,
        check_revision_uses_latest,
        check_topic_known,
        check_verified_facts,
    )

    results = []

    # 1) 字面完全相同的两条样本必须被抓到
    a, b = make(id="d1"), make(id="d2")
    results.append(("字面重复的用户话术", bool(check_exact_duplicates([a, b]))))
    results.append(("话术不同则不应报重复",
                    not check_exact_duplicates([a, make(id="d3", turns=[
                        Turn(role="user", content="换个问法算 2+2"),
                        *make().turns[1:]])])))

    # 1a2) topic 写错会让复杂度检查静默失效，所以拼错必须被抓到。
    #      两套知识点命名空间都是合法的（根 KG 的中文 id / seeds 的 snake_case），
    #      两边各配一个"对的不该报"，否则这条检查会变成只会报错的假检查。
    kp = {"quicksort_analysis", "并查集"}
    results.append(("topic 拼错必须被抓到",
                    bool(check_topic_known([make(id="t1", topic="并查集集")], kp))))
    results.append(("topic 用中文 KG id 不应误报",
                    not check_topic_known([make(id="t2", topic="并查集")], kp)))
    results.append(("topic 用 snake_case id 不应误报",
                    not check_topic_known([make(id="t3", topic="quicksort_analysis")], kp)))
    results.append(("topic 留空不应误报",
                    not check_topic_known([make(id="t4", topic="")], kp)))
    results.append(("知识点清单读不到时必须吵，而不是静默放行",
                    bool(check_topic_known([make(id="t5", topic="并查集集")], set()))))

    # 1b) collect 模式的占位 system prompt 绝不能进数据
    results.append(("system 是 collect 占位符必须被抓到",
                    bool(check_no_collect_placeholder([make(id="c1", system=COLLECT_PLACEHOLDER)]))))
    results.append(("正常 system prompt 不应误报",
                    not check_no_collect_placeholder([make(id="c2", system="# 你是一个辅助计算机专业学生学习的 Agent")])))

    # 1c) ASK_USER 的四条行为契约（架构 V1 的 Behavior Contract）
    #     每条都配"该报的报"和"不该报的不报"两个用例 ——
    #     只写前者会得到一个永远报错的假检查（5.9 就是这么来的）。
    def clarify(ask, ask_for, user="帮我安排一下数据结构的复习", sid="cl1", tools=None):
        return Sample(
            id=sid, template_id=f"cl__{sid}", category="clarify", schema_version=VERSION,
            system="你是 ESA。", tool_names=tools or ["recommend_practice"],
            ask_for=list(ask_for),
            turns=[Turn(role="user", content=user), Turn(role="assistant", content=ask)],
        )

    def hits(sample, check_name):
        return any(f.check == check_name
                   for f in check_clarify_contract([sample], BY_NAME))

    # ① 必须真的在索要信息
    results.append(("追问没在要信息被抓到",
                    hits(clarify("好的，我知道了。", ["weeks_to_exam"]), "clarify_no_question")))
    results.append(("问句式追问不误报",
                    not hits(clarify("请问还有几周考试？", ["weeks_to_exam"]), "clarify_no_question")))
    # 这一条是实测撞出来的：157 条里有 12 条是陈述式索要信息，
    # 只认问号的第一版把它们全判成了违规。
    results.append(("陈述式追问不误报（「我需要两个信息：…」）",
                    not hits(clarify("好的，我需要两个信息：一是哪门课程，二是距离考试还有几周。",
                                     ["course", "weeks_to_exam"]), "clarify_no_question")))

    # ② 只询问缺失信息：追问的参数得对某个在场工具是必填
    results.append(("追问一个谁都不必填的参数被抓到",
                    hits(clarify("请问你想查哪个知识点？", ["kp_id"],
                                 tools=["get_mastery_report"]), "clarify_optional_param")))
    # 这一条也是实测撞出来的：course 在干扰工具 get_mastery_report 里是可选、
    # 在真正要调的 recommend_practice 里是必填，第一版取"第一个含该参数的工具"就误报了。
    results.append(("必填参数被干扰工具带偏时不误报",
                    not hits(clarify("请问哪门课、还有几周考？", ["course", "weeks_to_exam"],
                                     tools=["get_mastery_report", "recommend_practice"]),
                             "clarify_optional_param")))

    # ③ 不得重复询问已有信息
    results.append(("用户已说课程却仍追问 course 被抓到",
                    hits(clarify("请问是哪门课程？", ["course"],
                                 user="帮我安排一下数据结构的复习"), "clarify_reask")))
    results.append(("用户没说课程时追问 course 不误报",
                    not hits(clarify("请问是哪门课程？", ["course"],
                                     user="帮我安排一下复习"), "clarify_reask")))

    # ④ 不得猜测缺失参数
    results.append(("追问里替用户猜了周数被抓到",
                    hits(clarify("那就按 12 周来安排，可以吗？", ["weeks_to_exam"]), "clarify_guess")))
    results.append(("追问里引用用户说过的数字不误报",
                    not hits(clarify("你说的 12 周是指期末考试吗？", ["weeks_to_exam"],
                                     user="我还有 12 周考试，帮我安排数据结构复习"), "clarify_guess")))

    # 1d) REFUSE 的行为契约（架构 V1 的 Behavior Contract）
    def refusal(ans, sid="rf1"):
        return Sample(
            id=sid, template_id=f"rf__{sid}", category="refusal", schema_version=VERSION,
            system="你是 ESA。", tool_names=["arxiv_search"],
            turns=[Turn(role="user", content="帮我编三篇参考文献"),
                   Turn(role="assistant", content=ans)],
        )

    def rf_hits(ans, check_name):
        return any(f.check == check_name for f in check_refusal_contract([refusal(ans)]))

    # 该报的报：标成 refusal 却照做了 —— 没有工具调用、结构合法、类别也对，
    # 没有这条检查它会**完全静默**地通过，而它教的正好是反的。
    results.append(("标成 refusal 却照做了被抓到",
                    rf_hits("好的，这是三篇：[1] Smith 2020…", "refusal_not_refusing")))
    results.append(("正常拒绝不误报",
                    not rf_hits("编参考文献我不做，伪造引用一查就穿。要真的我帮你搜。",
                                "refusal_not_refusing")))
    # 回归：第一版词表漏了「不编」，把一条合格的部分拒绝判成了违规。
    results.append(("「占位文献不编」这种说法不误报（实测撞出来的）",
                    not rf_hits("提纲我来列，占位文献不编——占位符最后经常忘了换。",
                                "refusal_not_refusing")))
    # 该报的报：一边说不做、一边暗示已经做了，用户会真的拿去用
    results.append(("拒绝的同时假装已执行被抓到",
                    rf_hits("这个我不做。不过我已经帮你生成了三篇，你看看。",
                            "refusal_pretend")))
    results.append(("拒绝并给出替代项不误报",
                    not rf_hits("编参考文献我不做。要真的我可以帮你按主题搜 arXiv。",
                                "refusal_pretend")))

    # 2) 「修改参数」用了旧值必须被抓到
    stale = Sample(
        id="r1", template_id="S002__修改参数__x", category="multi_turn_tool",
        schema_version=VERSION, system="你是 ESA。", tool_names=["recommend_practice"],
        turns=[
            Turn(role="user", content="我想复习数据结构，还有 8 周考试。"),
            Turn(role="assistant", content="好的。"),
            Turn(role="user", content="改一下，我要问的是操作系统"),
            # ↓ 仍然用旧课程，属于教反了
            Turn(role="tool_call", calls=[ToolCall("recommend_practice", {"course": "数据结构", "weeks_to_exam": 8})]),
            Turn(role="tool_result", results=[ToolResult("recommend_practice", {"recommendations": []})]),
            Turn(role="assistant", content="好的，已为你安排。"),
        ],
    )
    results.append(("修改参数却用了旧值", bool(check_revision_uses_latest([stale]))))

    fixed = Sample(**{**stale.__dict__, "id": "r2"})
    fixed.turns = list(stale.turns)
    fixed.turns[3] = Turn(role="tool_call",
                          calls=[ToolCall("recommend_practice", {"course": "操作系统", "weeks_to_exam": 8})])
    results.append(("修改参数用了新值则通过", not check_revision_uses_latest([fixed])))

    # 3) 复杂度断言核查
    facts = {"complexity": {"quicksort_analysis": ["O(n log n)", "O(n^2)", "O(log n)"]}}
    wrong = make(id="f1", topic="quicksort_analysis", turns=[
        Turn(role="user", content="快排平均复杂度"),
        Turn(role="assistant", content="快速排序平均时间复杂度是 $O(n)$。"),
    ])
    right = make(id="f2", topic="quicksort_analysis", turns=[
        Turn(role="user", content="快排平均复杂度"),
        Turn(role="assistant", content="平均 $O(n \\log n)$，最坏 $O(n^2)$。"),
    ])
    results.append(("复杂度写错（O(n)）", bool(check_verified_facts([wrong], facts))))
    results.append(("复杂度正确且含对比项", not check_verified_facts([right], facts)))

    # 4) 报错文案登记核查
    #
    # 正反两个用例缺一不可：只写「该报错的会报」会得到一个永远报错的假检查
    # （5.9 那次就是这么栽的：登记表带 O(...) 包装、正文抽出来不带，两边永远对不上，
    #  看起来一直在工作，实则完全失效）。
    literals = {"[Error]: 搜索请求超时", "当前会话为 isolated 模式，禁止读取长期记忆"}
    patterns = [re.compile(r"^未找到课程 '.+' 的知识点，请确认课程名$")]

    def toolerr(sid: str, content) -> Sample:
        return make(id=sid, category="tool_error", tool_names=["web_search"], turns=[
            Turn(role="user", content="搜一下最新的大模型进展"),
            Turn(role="tool_call", calls=[ToolCall("web_search", {"query": "大模型 最新进展"})]),
            Turn(role="tool_result", results=[ToolResult("web_search", content, is_error=True)]),
            Turn(role="assistant", content="搜索没跑通，我不会用猜测代替检索结果。"),
        ])

    made_up = toolerr("e1", "[Error]: 服务暂时不可用，请稍后重试")   # 线上不存在的句子
    registered = toolerr("e2", "[Error]: 搜索请求超时")               # web_search.py:94 的原文
    by_pattern = toolerr("e3", {"count": 0, "recommendations": [],
                                "note": "未找到课程 '高等数学' 的知识点，请确认课程名"})
    no_text = toolerr("e4", {"count": 0, "recommendations": []})      # 标了 is_error 却没有文案

    results.append(("编造的报错文案被拦下",
                    bool(check_error_texts_registered([made_up], literals, patterns))))
    results.append(("登记过的报错文案放行",
                    not check_error_texts_registered([registered], literals, patterns)))
    results.append(("正则登记的报错文案放行",
                    not check_error_texts_registered([by_pattern], literals, patterns)))
    results.append(("标了 is_error 却没有报错文案被拦下",
                    bool(check_error_texts_registered([no_text], literals, patterns))))
    results.append(("非 tool_error 类不受此检查影响",
                    not check_error_texts_registered([make(id="e5")], literals, patterns)))

    # 5) 答对/答错的标签极性
    #
    # 这条检查是被组长审出来的 bug 逼出来的：生成器把 record_answer 的 correct
    # 写死成 True，于是「刚做完哈希表的练习，答错了」的 gold 也是 correct=True。
    # 结构全合法、schema 全通过、grounding 也过 —— 全绿，只有语义是反的。
    def answered(q: str, correct: bool, sid: str) -> Sample:
        return make(id=sid, tool_names=["record_answer"], turns=[
            Turn(role="user", content=q),
            Turn(role="tool_call", calls=[ToolCall("record_answer", {"kp_id": "哈希表", "correct": correct})]),
            Turn(role="tool_result", results=[ToolResult("record_answer", {"kp_id": "哈希表", "correct": correct})]),
            Turn(role="assistant", content="记下了。"),
        ])

    results.append(("说答错了却记成 correct=True",
                    bool(check_answer_polarity([answered("刚做完哈希表的练习，答错了", True, "p1")]))))
    results.append(("说答错了且记成 correct=False 则通过",
                    not check_answer_polarity([answered("刚做完哈希表的练习，答错了", False, "p2")])))
    results.append(("说做对了却记成 correct=False",
                    bool(check_answer_polarity([answered("哈希表这题我做对了", False, "p3")]))))
    results.append(("说做对了且记成 correct=True 则通过",
                    not check_answer_polarity([answered("哈希表这题我做对了", True, "p4")])))
    results.append(("线索模糊时不乱报",
                    not check_answer_polarity([answered("哈希表那道题我交了", True, "p5")])))

    # 6) 「该调 B 却标成不该调 A」
    def neg(answer: str, sid: str) -> Sample:
        return make(id=sid, category="hard_negative", tool_names=["retrieve_knowledge", "calculator"],
                    turns=[Turn(role="user", content="帮我算 2 的 16 次方"),
                           Turn(role="assistant", content=answer)])

    results.append(("负样本的回答自己承认「这个用计算器算就行」",
                    bool(check_negative_not_positive([neg("这个用计算器算就行，不需要查知识库。", "n1")]))))
    results.append(("真正什么都不该调的负样本则通过",
                    not check_negative_not_positive([neg("递归就是函数直接或间接调用自身。", "n2")])))
    results.append(("自我介绍里列能力不算承认（曾误报寒暄样本）",
                    not check_negative_not_positive(
                        [neg("我是 ESA，可以帮你规划练习、查学情、讲知识点。", "n3")])))
    return results


def main() -> int:
    passed = failed = 0
    for name, sample, expect in CASES:
        checks = {f.check for f in validate_sample(sample, BY_NAME, VERSION)}
        ok = (not checks) if expect == "" else (expect in checks)
        print(f"{'✅' if ok else '❌'} {name:36s} 命中={sorted(checks) or '无'}")
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"     期望命中 {expect!r}")

    print()
    for name, ok in corpus_cases():
        print(f"{'✅' if ok else '❌'} {name}")
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    print(f"\n{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
