#!/usr/bin/env python3
"""把一条训练样本的 labels 打出来，看我们到底在**哪些 token 上算了损失**。

起因（2026-08-26）：后端反馈初版模型输出特别简短。查 LLaMA-Factory 源码发现
`data_args.enable_thinking` 默认 `True`，而我们的训练目标里一个 `<think>` 都没有，
于是 `template.py:427-434` 走 `else: # do compute loss` 分支，把一个**空的**
`<think>\\n\\n</think>` 塞进 `response_ids` —— 也就是每条样本都在教模型「先吐个空思考」。

源码是这么写的，但**别只靠读源码下结论**。这个脚本用真的 tokenizer 跑一遍，
把 label != -100 的那段解码出来给人看。

用法（🖥️ 集群上，`conda activate lf` 之后，**在 `.../backend/scripts/dataset` 目录里跑**）：

    python tools/dump_train_labels.py \\
        --model /remote_dir/home/chenxuzhao/models/Qwen3.5-122B-A10B \\
        --data data/out/esa_agent_train.jsonl

加 `--enable-thinking false` 再跑一次，对比两次的「计损前 40 个 token」。
如果默认那次开头是 `<think>\\n\\n</think>` 而 false 那次不是，机制就坐实了。

⚠️ 只加载 tokenizer，不加载权重 —— 登录节点几秒钟就能跑完，不用排队。

⚠️ **本机跑不了**（没有 torch / datasets），所以这个脚本**第一次是在集群上跑的**。
源码链条已在本机 `~/LlamaFactory` 逐行核实过（见手册 4.3m 的表），但**读源码不等于跑过** ——
第一次跑报错就把错贴回来改。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

IGNORE_INDEX = -100

_FROM_TO_ROLE = {
    "human": "user",
    "gpt": "assistant",
    "function_call": "function",
    "observation": "observation",
    "system": "system",
}


def to_messages(conversations: list[dict]) -> list[dict]:
    """sharegpt 的 from/value → LLaMA-Factory 内部的 role/content。"""
    out = []
    for c in conversations:
        role = _FROM_TO_ROLE.get(c["from"])
        if role is None:
            raise ValueError(f"未知的 from 值：{c['from']!r}")
        out.append({"role": role, "content": c["value"]})
    return out


def run_all(args, tokenizer, template, encode_row) -> int:
    """全量统计：整个训练集的计损 token 里，有多少是空 think。

    这个比例就是「训练信号里有多大一块在教模型吐空思考」，
    是 4.3m 机制一最直接的一个数。

    🔴 **直接数「以空 think 开头的计损段」，不按轮数估算。**
    第一版用 `from == "gpt"` 的轮数 × 4 估，会**少算** ——
    `encode_multiturn` 按 `range(0, len(messages), 2)` 配对，
    `function_call` 轮落在奇数位，同样会被补一个空 think（`template.py:463-470`）。
    与其在这里复述模板的配对规则（复述就会分叉，5.54），不如量它的输出。
    """
    think_ids = template.get_thought_word_ids(tokenizer)
    k = len(think_ids)
    print(f"空 think = {k} 个 token：{tokenizer.decode(think_ids)!r}")

    n_rows = total_loss = think_loss = 0
    segs_total = segs_with_think = 0
    with args.data.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            n_rows += 1
            _, labels = encode_row(row)

            seg: list[int] = []
            segs: list[list[int]] = []
            for lab in labels:
                if lab != IGNORE_INDEX:
                    seg.append(lab)
                elif seg:
                    segs.append(seg)
                    seg = []
            if seg:
                segs.append(seg)

            for one in segs:
                total_loss += len(one)
                segs_total += 1
                if one[:k] == think_ids:
                    think_loss += k
                    segs_with_think += 1

            if n_rows % 200 == 0:
                print(f"  已处理 {n_rows} 条", flush=True)

    print(f"\n样本 {n_rows} 条，计损段 {segs_total} 个"
          f"（其中 {segs_with_think} 个以空 think 开头）")
    print(f"计损 token 合计 {total_loss}")
    if not total_loss:
        return 0
    pct = think_loss / total_loss * 100
    print(f"其中花在**空 think**上的 {think_loss}  → **{pct:.1f}%**")
    print("\n判读：这个百分比就是「训练信号里有多大一块在教模型吐空思考」。")
    print("      回复越短这个数越大 —— 而我们的回复正好偏短（5.61）。")
    print("      用 --enable-thinking false 再跑一次，它应该变成 0.0%。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="基座路径（只读 tokenizer）")
    ap.add_argument("--data", required=True, type=Path, help="esa_agent_train.jsonl")
    ap.add_argument("--template", default="qwen3_5")
    ap.add_argument("--enable-thinking", default="true",
                    choices=["true", "false", "none"],
                    help="对应训练 yaml 的 enable_thinking；默认 true 就是我们现在跑的配置")
    ap.add_argument("--index", type=int, default=0, help="看第几条样本")
    ap.add_argument("--head", type=int, default=40, help="计损段前多少个 token")
    ap.add_argument("--all", action="store_true",
                    help="跑全量，统计**整个训练集里有多大比例的计损 token 花在空 think 上**")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    from llamafactory.data.template import get_template_and_fix_tokenizer
    from llamafactory.hparams import DataArguments

    enable = {"true": True, "false": False, "none": None}[args.enable_thinking]

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    data_args = DataArguments(template=args.template)
    data_args.enable_thinking = enable
    template = get_template_and_fix_tokenizer(tokenizer, data_args)
    print(f"模板 {args.template}  是 ReasoningTemplate 吗: "
          f"{type(template).__name__}  enable_thinking={template.enable_thinking!r}")

    def encode_row(row: dict) -> tuple[list[int], list[int]]:
        messages = to_messages(row["conversations"])
        system = row.get("system", "")
        tools = row.get("tools", "")
        if isinstance(tools, (list, dict)):
            tools = json.dumps(tools, ensure_ascii=False)
        input_ids: list[int] = []
        labels: list[int] = []
        for source_ids, target_ids in template.encode_multiturn(
                tokenizer, messages, system, tools):
            input_ids += source_ids + target_ids
            labels += [IGNORE_INDEX] * len(source_ids) + target_ids
        return input_ids, labels

    if args.all:
        return run_all(args, tokenizer, template, encode_row)

    with args.data.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i == args.index:
                row = json.loads(line)
                break
        else:
            raise SystemExit(f"文件里没有第 {args.index} 条")

    messages = to_messages(row["conversations"])
    system = row.get("system", "")
    tools = row.get("tools", "")
    if isinstance(tools, (list, dict)):
        tools = json.dumps(tools, ensure_ascii=False)

    print(f"\n样本 #{args.index}：{len(messages)} 轮  "
          f"({'→'.join(m['role'] for m in messages)})")
    print(f"目标文本里有 <think> 吗: "
          f"{'有' if '<think>' in messages[-1]['content'] else '🔴 没有'}")

    encoded = template.encode_multiturn(tokenizer, messages, system, tools)
    input_ids: list[int] = []
    labels: list[int] = []
    for source_ids, target_ids in encoded:
        input_ids += source_ids + target_ids
        labels += [IGNORE_INDEX] * len(source_ids) + target_ids

    n_loss = sum(1 for x in labels if x != IGNORE_INDEX)
    print(f"\n总 token {len(input_ids)}，其中计损 {n_loss} "
          f"（{n_loss / len(input_ids) * 100:.1f}%）")

    # 逐个计损段，打头部
    seg, segs = [], []
    for tid, lab in zip(input_ids, labels):
        if lab != IGNORE_INDEX:
            seg.append(tid)
        elif seg:
            segs.append(seg)
            seg = []
    if seg:
        segs.append(seg)

    print(f"\n计损段共 {len(segs)} 段。每段开头 {args.head} 个 token 解码如下：")
    for k, s in enumerate(segs):
        head = tokenizer.decode(s[:args.head])
        flag = "  🔴 空 think 在计损里" if "<think>" in head and "</think>" in head \
            and not head.split("<think>")[-1].split("</think>")[0].strip() else ""
        print(f"\n  [第 {k + 1} 段, {len(s)} token]{flag}")
        print("    " + repr(head))

    print("\n判读：")
    print("  · 若某段以 `<think>\\n\\n</think>` 开头 → 我们正在教模型吐空思考（机制一坐实）")
    print("  · 用 --enable-thinking false 再跑一次，那几个 token 应该移出计损段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
