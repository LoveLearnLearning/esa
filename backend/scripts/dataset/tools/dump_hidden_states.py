#!/usr/bin/env python3
"""🖥️ **集群上跑（要 GPU）。** 把每道题「模型该出手那一刻」的隐状态存下来。

这是干什么用的
--------------
《Tunable Tool-Call Rates in LLM Agents via Representation Steering》
（[arXiv 2608.25198](https://arxiv.org/abs/2608.25198)，2026-08-25）说：
**「调不调工具」由残差流里的单一线性方向控制，不需要训练就能提取，
推理期加一个强度 α 就能把调用率从 ~0% 单调推到 >90%，且能泛化到未见过的工具。**

我们的误触发率（FPR）是唯一一个「多训也不动」的指标 ——
训练侧探针上 32.9% → 23.2%（10 epoch），考卷上 30.5% → 30.5%（一动不动）。
也就是说多训只让它**记住了那些具体负例**，没学会「不该调」这条规则。
如果上面那篇成立，说明这根本不是知识问题，是**表示空间里一个可以直接拧的方向**。

这个脚本只做**验证前提**那一步：把隐状态存下来，交给 `probe_tool_direction.py`
去看 call / no-call 在这个空间里分不分得开。**分不开就直接排除掉整条路线**，
成本是一次前向（不生成）；分得开，那条推理期干预才值得跟后端提。

🔴 三条一定要守的
-----------------
1. **必须走模型真正看见的那一层**（5.18 那一族，已经踩过五次）。
   所以 messages 用 `esa.eval.build_messages` **原样复用**，模板用 adapter 目录里
   那份 `chat_template.jinja`（llamafactory 训练时存下来的就是它），
   而不是自己拼一遍 prompt。
2. **拟合和测试必须分开**：拟合用训练侧探针集，测试用考卷。
   在考卷上拟合再在考卷上报数，等于拿考卷训练。
3. **只取「该出手那一刻」的最后一个 token** —— 而那一刻是提示停在
   `<|im_start|>assistant\n` 的时候，**后面什么都还没有**。
   ⚠️ 第一版写的是 `enable_thinking=False`，模板会往后拼一段 `<think>\n\n</think>\n\n`
   （`chat_template.jinja:149-153`），采到的就成了「已经决定不思考之后」那一步 ——
   不是决策点。用模型自己的输出反推才发现：ep10 的 440 条预测里 **249 条
   （56.6%）正文以 `<think>` 开头**，说明线上的生成提示里根本没有 think 前缀。
   现在渲染完会把尾巴切掉并**断言**停在 assistant 头上，切不掉就退出。

用法
----
    python tools/dump_hidden_states.py \\
        --model /remote_dir/home/chenxuzhao/models/Qwen3.5-122B-A10B \\
        --adapter $HOME/esa_results/adapter_93728_nothink_ep10_20260903_1832 \\
        --suite probe --out $HOME/esa_results/hidden_probe_ep10.npz
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from esa.eval import SUITES, build_messages  # noqa: E402
from esa.paths import in_dataset  # noqa: E402

# gold 的 expected_action → 二分类标签。
#   1 = 这一刻**应该**调工具   0 = 这一刻**不该**调
# RESPOND_TOOL_RESULT 不进：那是工具已经调完、在写回复，不是 call/no-call 的决策点。
# RECOVER_TOOL_ERROR 也不进：它是「工具失败之后怎么办」，决策结构不一样。
LABELS = {
    "CALL_TOOL": 1,
    "DIRECT_ANSWER": 0,
    "ASK_USER": 0,
    "REFUSE": 0,
}


def load_suite(suite: str) -> list[dict]:
    path = in_dataset("data/eval") / SUITES[suite]["eval"]
    if not path.is_file():
        sys.exit(f"❌ 找不到 {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", default=None,
                    help="不给就是 base 模型（用来对照：方向是训出来的还是本来就有的）")
    ap.add_argument("--suite", required=True, choices=list(SUITES))
    ap.add_argument("--out", required=True)
    ap.add_argument("--every-n-layers", type=int, default=4,
                    help="每隔几层取一层（最后一层一定取）。存全部层太占地方，磁盘现在很紧")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 道，调试用")
    a = ap.parse_args()

    import numpy as np
    import torch
    import transformers
    from transformers import AutoConfig, AutoTokenizer

    recs = [r for r in load_suite(a.suite) if r["gold"]["expected_action"] in LABELS]
    if a.limit:
        recs = recs[:a.limit]
    print(f"{a.suite}：{len(recs)} 道进入（只要 {sorted(LABELS)} 这四类）")
    from collections import Counter
    print("  标签分布：", dict(Counter(r["gold"]["expected_action"] for r in recs)))

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)

    # 🔴 模板必须是 llamafactory 训练/推理时用的那一份。adapter 目录里存着它。
    if a.adapter:
        tpl = pathlib.Path(a.adapter) / "chat_template.jinja"
        if tpl.is_file():
            tok.chat_template = tpl.read_text(encoding="utf-8")
            print(f"  ✅ 用 adapter 目录里的 chat_template.jinja（{tpl.stat().st_size} 字节）")
        else:
            print("  ⚠️ adapter 目录里没有 chat_template.jinja，退回 tokenizer 自带的 —— "
                  "这可能和推理时不是同一个模板，结论要打折")

    # 🔴 2026-09-05 第二次返工。第一版用 AutoModelForCausalLM 加载，模块路径成了
    #    `model.layers.…`；而 adapter 的权重键是
    #    `base_model.model.model.language_model.layers.…`（这个模型是
    #    Qwen3_5MoeForConditionalGeneration，带 vision_config 的多模态壳子）。
    #    路径对不上 → peft **一个模块都没注入、也不报错**，
    #    于是「加了 adapter」和「没加」跑出来的隐状态**逐字节相同**。
    #    是 base 对照跑出**一模一样的 13 个 AUROC**才暴露的 —— 两个模型不可能
    #    在 13 层上都相同到小数点后三位。**没有那次对照，这个错会一路写进报告。**
    #    所以下面按 config 里写的架构类加载，并且加两道硬闸门。
    print("加载模型…", flush=True)
    t0 = time.time()
    cfg = AutoConfig.from_pretrained(a.model, trust_remote_code=True)
    arch = (getattr(cfg, "architectures", None) or [None])[0]
    cls = getattr(transformers, arch, None) if arch else None
    if cls is None:
        from transformers import AutoModelForCausalLM
        cls = AutoModelForCausalLM
        print(f"  ⚠️ transformers 里没有 {arch!r}，退回 AutoModelForCausalLM")
    else:
        print(f"  按 config.architectures 用 {arch}")
    model = cls.from_pretrained(
        a.model, dtype=torch.bfloat16, device_map="auto", trust_remote_code=True)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
        # 闸门一：真的注进去了吗
        n_lora = sum(1 for n, _ in model.named_parameters() if "lora_" in n)
        if n_lora == 0:
            sys.exit("❌ 闸门一：peft 一个 lora 参数都没注入 —— "
                     "多半是模块路径对不上（adapter 的键里带 language_model，"
                     "而加载出来的模型没有那一层）。**不许往下跑**，"
                     "跑出来的是 base 的数、还长得完全正常。")
        print(f"  ✅ 闸门一：注入 {n_lora} 个 lora 参数")
    model.eval()
    print(f"  加载完 {time.time() - t0:.0f} 秒", flush=True)

    # 多模态壳子的 config 上没有 num_hidden_layers，层数在 text_config 里（实测 48）。
    # 找不到就报错退出，不猜一个默认值 —— 猜错了会静默取错层。
    cfg_m = model.config
    n_layers = getattr(cfg_m, "num_hidden_layers", None)
    if n_layers is None:
        n_layers = getattr(getattr(cfg_m, "text_config", None), "num_hidden_layers", None)
    if n_layers is None:
        sys.exit(f"❌ 从 config 里读不出层数（{type(cfg_m).__name__}）—— 先查清楚再跑，别猜")
    keep = sorted({i for i in range(0, n_layers + 1, a.every_n_layers)} | {n_layers})
    print(f"  共 {n_layers} 层，取 {len(keep)} 层：{keep}")

    feats: list[np.ndarray] = []
    labels: list[int] = []
    ids: list[str] = []
    shown = False
    t0 = time.time()
    for i, rec in enumerate(recs, 1):
        msgs = build_messages(rec)
        tools = json.loads(rec["tools"])
        # 🔴 2026-09-05 返工。第一版写的是 enable_thinking=False，模板于是把
        #    `<think>\n\n</think>\n\n` 拼进了生成提示（chat_template.jinja:149-153），
        #    我采到的是**模型"已经决定不思考"之后**那一步的状态 —— 不是决策点。
        #
        #    怎么确认的：ep10 的 440 条预测里 **249 条（56.6%）正文以 `<think>` 开头**。
        #    如果推理时的提示里已经有 think 前缀，模型的续写就不可能再吐一个 `<think>` 出来。
        #    所以线上那一版的生成提示**停在 `<|im_start|>assistant\n`**，
        #    后面写什么（think 还是直接 tool_call）由模型自己决定 —— 那才是决策点。
        #
        #    模板两个分支都会往后加东西（False 加空 think、否则加 `<think>\n`），
        #    所以这里渲染完把尾巴那截切掉，再**断言**它正好停在 assistant 头上。
        #    5.18 那一族第六次：读了模板 ≠ 采对了位置，得拿模型自己的输出去反推。
        HEAD = "<|im_start|>assistant\n"
        text = tok.apply_chat_template(
            msgs, tools=tools, tokenize=False, add_generation_prompt=True)
        cut = text.rfind(HEAD)
        if cut < 0:
            sys.exit(f"❌ 渲染结果里找不到 {HEAD!r} —— 模板换了，先核对再跑")
        text = text[:cut + len(HEAD)]
        if not text.endswith(HEAD):
            sys.exit("❌ 截完之后没停在 assistant 头上，拒绝继续")
        if not shown:
            # 只打一次，人工核一眼「这确实是模型看见的那一层」
            print("── 渲染出来的 prompt（首 300 / 末 300 字）──")
            print(text[:300].replace("\n", "\\n"))
            print("   …")
            print(text[-300:].replace("\n", "\\n"))
            print("──────────────────────────────────────")
            shown = True
        enc = tok(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model(**enc, output_hidden_states=True, use_cache=False)
        if out.hidden_states is None:
            sys.exit("❌ 模型没返回 hidden_states —— 这个壳子可能要换个入口，先查再跑")
        # 闸门二：**关掉 adapter 再跑一遍，两次必须不一样**。
        # 闸门一只证明「参数注进来了」，不证明「前向真的走了它」——
        # 而这次栽的正是「看起来都对、结果是 base 的数」。只在第一条上做，代价一次前向。
        if a.adapter and i == 1:
            with torch.no_grad(), model.disable_adapter():
                ref = model(**enc, output_hidden_states=True, use_cache=False)
            diff = max(float((out.hidden_states[k] - ref.hidden_states[k]).abs().max())
                       for k in keep)
            if diff == 0.0:
                sys.exit("❌❌ 闸门二：开 adapter 与关 adapter 的隐状态**逐位相同** —— "
                         "adapter 没起作用。2026-09-05 就是这么白跑了两个作业，"
                         "而且 base 对照跑出一模一样的 13 个 AUROC 才发现。不许往下跑。")
            print(f"  ✅ 闸门二：开/关 adapter 隐状态最大差 {diff:.4g}（非零，adapter 生效）",
                  flush=True)
        # hidden_states[k] 是第 k 层输出，[0] 是 embedding。取**最后一个 token**：
        # 那正是模型即将写第一个 token 时的状态。
        vec = np.stack([out.hidden_states[k][0, -1, :].float().cpu().numpy() for k in keep])
        feats.append(vec.astype(np.float16))
        labels.append(LABELS[rec["gold"]["expected_action"]])
        ids.append(rec["gold"]["id"])
        if i % 25 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(recs)}  {el:.0f}s（{el / i:.1f}s/道）", flush=True)

    out_path = pathlib.Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        feats=np.stack(feats),          # (N, len(keep), hidden)
        labels=np.array(labels, dtype=np.int8),
        ids=np.array(ids),
        layers=np.array(keep, dtype=np.int32),
        suite=a.suite,
        adapter=str(a.adapter or "base"),
    )
    print(f"✅ {len(feats)} 道 × {len(keep)} 层 → {out_path}"
          f"（{out_path.stat().st_size / 1e6:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
