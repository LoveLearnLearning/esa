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


def _build_is_stable() -> bool:
    """同一份 IR 连续 build 两次，产出的记录序列必须完全一致。"""
    from esa.evalset import build, gold_of
    from esa.ir import iter_ir_files, load_samples

    samples = [s for f in iter_ir_files("dataset/data/ir") for s in load_samples(f)]

    def fingerprint():
        """处理 `fingerprint` 相关逻辑。"""
        ev, tr, st = build(samples)
        layer = st.get("layer_by_template", {})
        return ([s.id for s in ev], [s.id for s in tr],
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
