# backend/scripts/dataset/tests/test_eval_scoring.py

"""判分逻辑的自测：用合成预测验证指标算得对，不需要 GPU。

一个算错分的评测器比没有评测器更糟 —— 它会让你以为模型很好。
所以在拿它去测真模型之前，先用三种已知行为的"假模型"验证：

    perfect   完全照 gold 作答        → 各项应接近满分
    never     从不调用工具            → 漏调率 100%、误触发 0%
    always    见题就调第一个工具      → 误触发率 100%

    python3 dataset/tests/test_eval_scoring.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.eval import EVAL_DIR, score  # noqa: E402
from esa.ir import load_schemas, schemas_by_name  # noqa: E402
from esa.stats import macro_rate, mcnemar_exact, wilson  # noqa: E402


def xml_call(name: str, args: dict) -> str:
    """按后端 parse_output 认的 XML 格式渲染一次工具调用。"""
    parts = [f"<tool_call>\n<function={name}>"]
    for k, v in args.items():
        sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        parts.append(f"<parameter={k}>\n{sv}\n</parameter>")
    parts.append("</function>\n</tool_call>")
    return "\n".join(parts)


def context_numbers(rec: dict) -> list[str]:
    """评测题**给定部分**里出现过的数字。忠实回答只能引用这些。"""
    n = rec["gold"]["n_turns_given"]
    ctx = rec["system"] + " ".join(str(c["value"]) for c in rec["conversations"][:n])
    return re.findall(r"-?\d+(?:\.\d+)?", ctx)


def fake_model(kind: str, rec: dict) -> str:
    """处理 `fake_model` 相关逻辑。

    Args:
        kind: str => `kind` 参数。
        rec: dict => `rec` 参数。

    Returns:
        str => 处理结果。
    """
    g = rec["gold"]
    tools = [t["function"]["name"] for t in json.loads(rec["tools"])]
    if kind in ("perfect", "fabricate") and g["expected_action"] == "RESPOND_TOOL_RESULT":
        if kind == "fabricate":
            # 上下文里绝不会出现的数字 —— 这就是「拿到工具结果之后编造内容」，
            # 工具型 Agent 最典型的翻车方式。忠实度必须抓到它。
            return "根据查询结果，你的掌握度是 987654 分，还需要 987654 天。"
        nums = [x for x in context_numbers(rec) if len(x.lstrip("-").replace(".", "")) >= 2]
        # 忠实回答：只引用上下文里真实出现过的数字；没有可引用的就不写数字。
        return f"根据工具返回的结果，关键数值是 {nums[0]}。" if nums else "根据工具返回的结果回答如上。"
    if kind == "perfect" or kind == "fabricate":
        # 判据是「标准答案里还剩不剩调用」，不是动作字符串 ——
        # RECOVER_TOOL_ERROR 既可能是「改参数重试」（有调用），
        # 也可能是「如实说明」（没有调用）。
        if g["expected_tools"]:
            return xml_call(g["expected_tools"][0], g["expected_arguments"][0])
        if g["expected_action"] == "ASK_USER":
            return "请问是哪一门课程呢？"
        if g["expected_action"] == "RECOVER_TOOL_ERROR":
            return "工具这次没跑通，我不编结果。要不我们换个方式，或者稍后再试一次？"
        return "这个我直接回答就行。"
    if kind == "never":
        return "我直接回答：这个问题的答案是……"
    if kind == "always":
        return xml_call(tools[0], {})
    raise ValueError(kind)


def _supplement_is_isolated() -> tuple[bool, bool, bool]:
    """补充评测集必须**完全隔离**：不进训练集、不进主评测集、不改主评测集的抽样。

    第三条是最容易漏的，也是唯一一条「错了不会有任何东西报错」的：
    `evalset.build()` 挑评测模板用的是「按类别配额 + `rng.shuffle(pool)`」，
    而 `random.shuffle` 消耗的随机数与 `len(pool)` 成正比 ——
    **补充样本只要参与建 pool，后面所有类别抽到的模板都会跟着变**，
    那 464 道题就换了一套，而「这张表只能和作业 77999 那版基线比」
    是对外表述的硬约束（超算手册三之七）。

    判法：把补充样本全部拿掉再 build 一次，主评测集与训练集的 id 序列必须逐个相同。
    这比「肉眼看 sha256 有没有变」强在：它不依赖磁盘上那份文件当时是什么状态。
    """
    from esa.evalset import build
    from esa.ir import iter_ir_files, load_samples
    from esa.paths import in_dataset

    # ⚠️ 这里**故意写死** "supp__"，不 import `evalset.is_supplement`。
    #
    # 第一版就是 import 过来用的，结果反向测试当场露馅：把 evalset 里的前缀
    # 改成认不出补充集之后，三条里只有第一条红 —— 因为后两条用的是**同一个**
    # 判据，它跟着 bug 一起变了，于是「拿掉补充样本」拿掉的是空集，
    # 两次 build 当然一样，检查**空跑成功**。
    # 测试和被测代码共用判据，等于让被告自己当证人。
    prefix = "supp__"
    samples = [s for f in iter_ir_files(in_dataset("data/ir")) for s in load_samples(f)]
    marked = [s for s in samples if s.template_id.startswith(prefix)]
    ev, tr, _st, supp = build(samples)

    # ① 补充集非空、一条一个模板，且 build() 认出的正是带前缀那些
    #    （补改写只会让簇更大，一点也不会让指标更可信）
    one_per_template = (
        bool(marked)
        and {s.id for s in supp} == {s.id for s in marked}
        and len({s.template_id for s in supp}) == len(supp)
    )
    # ② 不与主评测集 / 训练集共享 template。非空才有意义 ——
    #    空集与任何集合都不相交，那种「通过」什么都没验证。
    supp_tpls = {s.template_id for s in marked}
    disjoint = bool(supp_tpls) and not (
        supp_tpls & ({s.template_id for s in ev} | {s.template_id for s in tr}))
    # ③ 拿掉带前缀的样本重新 build，主评测集与训练集必须逐个相同。
    #    这一条专门防「补充样本参与了 rng.shuffle 的 pool」——
    #    那会让 464 道题换一套，而且不会有任何东西报错。
    without = [s for s in samples if not s.template_id.startswith(prefix)]
    ev2, tr2, _st2, supp2 = build(without)
    unchanged = bool(marked) and (
        [s.id for s in ev] == [s.id for s in ev2]
        and [s.id for s in tr] == [s.id for s in tr2]
        and not supp2)
    return one_per_template, disjoint, unchanged


def _build_is_stable() -> bool:
    """同一份 IR 连续 build 两次，产出的记录序列必须完全一致。"""
    from esa.evalset import build, gold_of
    from esa.ir import iter_ir_files, load_samples
    from esa.paths import in_dataset

    # ⚠️ 这里原来写死了相对路径 "dataset/data/ir"，只有在仓库根跑才对。
    # 搬进 backend/scripts/dataset/ 之后（组长指定的落点）路径是
    # backend/scripts/dataset/data/ir，于是 iter_ir_files 一个文件都找不到，
    # samples 成了空表 —— 接着 assert_no_stale 会把台账里全部 56 条
    # 报成「样本已不存在」，看起来像台账烂了，其实是路径错了。
    # 其余代码早就走 esa/paths.py 做位置无关，这里漏了一处。
    samples = [s for f in iter_ir_files(in_dataset("data/ir")) for s in load_samples(f)]

    def fingerprint():
        """处理 `fingerprint` 相关逻辑。"""
        ev, tr, st, supp = build(samples)
        layer = st.get("layer_by_template", {})
        # 补充集也要进指纹：它同样是落盘产物，行序不稳就同样毁掉 diff。
        return ([s.id for s in ev], [s.id for s in tr], [s.id for s in supp],
                [gold_of(s, layer.get(s.template_id))["id"] for s in ev])

    return fingerprint() == fingerprint()

def main() -> int:
    """运行当前模块的命令行入口。"""
    if not (EVAL_DIR / "eval.jsonl").exists():
        print("先跑 PYTHONPATH=dataset python3 -m esa.evalset 生成评测集")
        return 1

    recs = [json.loads(line)
            for line in (EVAL_DIR / "eval.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    schemas, _ = load_schemas(Path(__file__).resolve().parents[1] / "schemas/tool_schemas.json")
    by_name = schemas_by_name(schemas)

    results = {}
    for kind in ("perfect", "never", "always", "fabricate"):
        preds = {r["gold"]["id"]: fake_model(kind, r) for r in recs}
        results[kind] = score(recs, preds, "current", by_name)

    p, n, a, fb = (results["perfect"], results["never"],
                   results["always"], results["fabricate"])

    # 追问命中率的判据单独验一次：ASK_USER 那些题分别喂
    # 「陈述式索要信息」和「什么都不要」，其余题照 perfect 作答。
    def variant(ask_reply: str) -> dict:
        """处理 `variant` 相关逻辑。"""
        preds = {}
        for r in recs:
            preds[r["gold"]["id"]] = (ask_reply
                                      if r["gold"]["expected_action"] == "ASK_USER"
                                      else fake_model("perfect", r))
        return score(recs, preds, "current", by_name)

    decl = variant("好的，我需要两个信息：一是哪门课程，二是距离考试还有几周。")
    mute = variant("行，那就这样吧。")

    # 拒绝命中率同理：只查"没调工具"不够，照做的回答也没有工具调用。
    def refuse_variant(reply: str) -> dict:
        """处理 `refuse_variant` 相关逻辑。"""
        preds = {}
        for r in recs:
            preds[r["gold"]["id"]] = (reply if r["gold"]["expected_action"] == "REFUSE"
                                      else fake_model("perfect", r))
        return score(recs, preds, "current", by_name)

    refused = refuse_variant("这个我不做。要真的我可以帮你按主题搜 arXiv。")
    complied = refuse_variant("好的，这就给你办：[1] Smith 2020, [2] Lee 2021。")

    # 分母的期望值直接从评测集本身算出来，不写死数字 —— 数据一变它跟着变。
    # 哪些动作该进 FPR（误触发率）的分母：**正确行为明确就是"不碰工具"**的那些。
    #
    # REFUSE 属于这一类 —— 拒绝题里去调 arxiv_search 编文献，正是最该抓的误触发。
    # RECOVER_TOOL_ERROR 和 RESPOND_TOOL_RESULT 不属于：
    #   前者的正确行为**可能**包含一次改参数重试（有调用），
    #   后者的前提是工具已经调过了。
    # 把它们混进来会让 FPR 不可信 —— 5.11 就是 RECOVER 掉进这个分母那次。
    want_nocall = sum(1 for r in recs
                      if r["gold"]["expected_action"] in ("ASK_USER", "DIRECT_ANSWER", "REFUSE"))
    want_recover = sum(1 for r in recs
                       if r["gold"]["expected_action"] == "RECOVER_TOOL_ERROR"
                       and not r["gold"]["expected_tools"])
    want_respond = sum(1 for r in recs
                       if r["gold"]["expected_action"] == "RESPOND_TOOL_RESULT")
    want_refuse = sum(1 for r in recs if r["gold"]["expected_action"] == "REFUSE")
    want_ask = sum(1 for r in recs if r["gold"]["expected_action"] == "ASK_USER")
    want_call = sum(1 for r in recs if r["gold"]["expected_tools"])

    # ---- 2026-08-19 新增：分母不能随模型行为缩水 ----
    #
    # 这是这一版最要紧的回归。旧判分器里，模型在拒绝题上调了工具，
    # 那道题**从拒绝命中率的分母里消失**，而不是记一次失败。
    # 于是 base 4/6=66.7%、lora 3/5=60.0% —— 分母不一样，
    # 两个数根本不在同一道题集上，却被当成「回退了 6.7 个点」在报告里讨论。
    #
    # 下面这个假模型只在**第一道拒绝题**上调工具，其余照 perfect 作答。
    # 正确的判分器必须：分母仍是 6，命中数掉到 5。
    first_refuse = next(r["gold"]["id"] for r in recs
                        if r["gold"]["expected_action"] == "REFUSE")

    def one_bad_refusal() -> dict:
        """只在一道拒绝题上调工具，其余全对。"""
        preds = {}
        for r in recs:
            g = r["gold"]
            if g["id"] == first_refuse:
                tools = [t["function"]["name"] for t in json.loads(r["tools"])]
                preds[g["id"]] = xml_call(tools[0], {})
            elif g["expected_action"] == "REFUSE":
                preds[g["id"]] = "这个我不做。要真的我可以帮你按主题搜 arXiv。"
            else:
                preds[g["id"]] = fake_model("perfect", r)
        return score(recs, preds, "current", by_name)

    leak = one_bad_refusal()

    # 宏平均：每个模板恰好一题时，宏平均必须等于微平均。
    balanced = macro_rate({"a": 1, "b": 0, "c": 1},
                          {"a": "T1", "b": "T2", "c": "T3"})
    # 一个大模板 + 一个小模板：微平均 3/4=75%，宏平均 (2/3 + 1/1)/2 ≈ 83.3%。
    skewed = macro_rate({"a": 1, "b": 1, "c": 0, "d": 1},
                        {"a": "T1", "b": "T1", "c": "T1", "d": "T2"})

    _supp = _supplement_is_isolated()

    checks = [
        ("perfect: 格式合法率 100%",        p["格式合法率"] == 100.0),
        ("perfect: 工具选择准确率 100%",     p["工具选择准确率"] == 100.0),
        ("perfect: 误触发率 0%",            p["误触发率 FPR"] == 0.0),
        ("perfect: 漏调率 0%",              p["漏调率 FNR"] == 0.0),
        ("perfect: 参数完全匹配率 100%",     p["参数完全匹配率"] == 100.0),
        ("perfect: 参数schema合法率 100%",   p["参数schema合法率"] == 100.0),
        ("perfect: 追问命中率 100%",         p["追问命中率"] == 100.0),
        ("perfect: 无混淆",                 not p["_confusion"]),
        ("never:   漏调率 100%",            n["漏调率 FNR"] == 100.0),
        ("never:   误触发率 0%",            n["误触发率 FPR"] == 0.0),
        ("never:   追问命中率 0%（没问句）",  n["追问命中率"] == 0.0),
        ("always:  误触发率 100%",          a["误触发率 FPR"] == 100.0),
        ("always:  漏调率 0%",              a["漏调率 FNR"] == 0.0),
        ("always:  有混淆记录",             bool(a["_confusion"])),
        ("always:  工具选择准确率 <100%",    a["工具选择准确率"] < 100.0),
        # ---- 以下四项针对「RECOVER_TOOL_ERROR 被判成误触发」那个 bug ----
        # 该报的报：工具已经失败还去调工具，恢复率必须掉到 0
        ("always:  工具失败恢复率 0%",       a["工具失败恢复率"] == 0.0),
        # 不该报的不报：如实说明不重试，恢复率满分
        ("perfect: 工具失败恢复率 100%",     p["工具失败恢复率"] == 100.0),
        # 分母不能串：tool_error 绝不能进 FPR 的分母
        (f"误触发率分母只含追问/直答/拒绝（{want_nocall}）", p["_n_nocall"] == want_nocall),
        (f"恢复率分母只含无后续调用的 tool_error（{want_recover}）", p["_n_recover"] == want_recover),
        # ---- 以下五项针对新增的 RESPOND_TOOL_RESULT ----
        # 不该报的不报：忠实引用上下文里的数字，忠实度满分
        ("perfect: 结果响应率 100%",         p["结果响应率"] == 100.0),
        ("perfect: 结果忠实度 100%",         p["结果忠实度"] == 100.0),
        # 该报的报：编一个上下文里没有的数字，忠实度必须掉到 0
        ("fabricate: 结果忠实度 0%（编数字被抓到）", fb["结果忠实度"] == 0.0),
        # 该报的报：工具已成功返回还去调工具，响应率掉到 0
        ("always:  结果响应率 0%",           a["结果响应率"] == 0.0),
        # 分母不能串：RESPOND_TOOL_RESULT 绝不能进 FPR 的分母（5.11 同款陷阱）
        (f"结果响应率分母只含 RESPOND（{want_respond}）", p["_n_respond"] == want_respond),
        # ---- 追问命中率的判据：陈述式索要信息也算命中 ----
        # 训练数据里有 12 条（8%）是陈述式（「我需要两个信息：…」）。
        # 只认问号的话，模型学会了正确行为反而被判漏答，指标系统性低估。
        ("陈述式追问算命中（不只认问号）", decl["追问命中率"] == 100.0),
        ("既不提问也不要信息则不算命中", mute["追问命中率"] == 0.0),
        # ---- REFUSE：照做的回答同样没有工具调用，只查"没调工具"抓不到它 ----
        ("真的拒绝算命中", refused["拒绝命中率"] == 100.0),
        ("照做了不算命中（这正是《02》承诺里不能出现的）", complied["拒绝命中率"] == 0.0),
        (f"拒绝命中率分母只含 REFUSE（{want_refuse}）", p["_n_refuse"] == want_refuse),
        # ---- 分母固定：这三项的分母绝不能随模型行为变化 ----
        # 旧口径下，模型在拒绝题上调工具会让那道题从分母里消失，
        # 于是「更坏的行为」被读成「小幅下滑」。
        (f"漏一道拒绝题给工具：分母仍是 {want_refuse}",
         leak["_stats"]["拒绝命中率"]["den"] == want_refuse),
        ("漏一道拒绝题给工具：命中数减一（不是分母减一）",
         leak["_stats"]["拒绝命中率"]["num"] == want_refuse - 1),
        ("旧口径（附注项）确实会缩分母 —— 保留它正是为了看得见这件事",
         leak["_stats"]["拒绝命中率(未调工具)"]["den"] == want_refuse - 1),
        (f"always: 拒绝命中率分母仍是 {want_refuse}（全调工具也不缩）",
         a["_stats"]["拒绝命中率"]["den"] == want_refuse),
        (f"always: 追问命中率分母仍是 {want_ask}",
         a["_stats"]["追问命中率"]["den"] == want_ask),
        (f"never:  工具选择准确率分母是应调题数 {want_call}（漏调算错，不是不算）",
         n["_stats"]["工具选择准确率"]["den"] == want_call),
        ("never:  工具选择准确率 0%（全漏调）", n["工具选择准确率"] == 0.0),
        # ---- BFCL 口径：工具选对且参数填对 ----
        ("perfect: 工具调用完全正确率 100%", p["工具调用完全正确率"] == 100.0),
        ("never:   工具调用完全正确率 0%", n["工具调用完全正确率"] == 0.0),
        ("工具调用完全正确率 ≤ 工具选择准确率（选对才谈得上填对）",
         a["工具调用完全正确率"] <= a["工具选择准确率"]),
        # ---- 小样本统计：Wilson / McNemar / 宏平均 ----
        ("Wilson: 0/n 下界为 0", wilson(0, 10)[0] == 0.0),
        ("Wilson: n/n 上界为 100", wilson(10, 10)[1] == 100.0),
        ("Wilson: 分母 0 报「什么都不知道」而不是 0%",
         wilson(0, 0) == (0.0, 100.0)),
        ("Wilson: 3/6 的区间宽到不能当信号（下界<25 且上界>75）",
         wilson(3, 6)[0] < 25.0 and wilson(3, 6)[1] > 75.0),
        ("McNemar: 两边完全一致 → p=1", mcnemar_exact(0, 0) == 1.0),
        ("McNemar: 10:0 一边倒 → p<0.01", mcnemar_exact(0, 10) < 0.01),
        ("McNemar: 5:5 → p=1（对称，说明不了）", mcnemar_exact(5, 5) == 1.0),
        ("McNemar: 交换 b/c 结果不变", mcnemar_exact(2, 7) == mcnemar_exact(7, 2)),
        ("宏平均: 每模板一题时等于微平均", balanced == (66.7, 3)),
        ("宏平均: 大模板不再主导（微 75% → 宏 83.3%）", skewed == (83.3, 2)),
        # ---- 失败样例不能被一个大模板占满 ----
        # 以前是 failures[:40]，而 88 道同模板的题排在一起，
        # 报告读起来就成了「失败全在 s004」—— 那是截断造成的错觉。
        ("失败样例每个模板最多留 3 条",
         all(v <= 3 for v in __import__("collections").Counter(
             f["tpl"] for f in a["_failures"]).values())),
        # ---- 补充评测集必须完全隔离（2026-08-19 新增）----
        ("补充集非空且一条一个模板", _supp[0]),
        ("补充集不与主评测集/训练集共享 template（不泄题）", _supp[1]),
        ("拿掉补充集重新 build，主评测集与训练集逐个相同（抽样没被扰动）", _supp[2]),
        # ---- 评测集必须字节可复现 ----
        # build() 里迭代 set 会让行序随 PYTHONHASHSEED 变：内容一样、字节不同。
        # 实测连跑三次得到三个 sha256。后果不是数据错，而是**没法用 diff 回答
        # "评测集有没有变"** —— 每次重跑都是一大片假差异，真改动淹在里面。
        ("评测集构建两次结果逐字节相同", _build_is_stable()),
    ]

    ok = 0
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        ok += passed
    print(f"\n{ok} 通过 / {len(checks) - ok} 失败")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
