# 工具调用闸门（推理期，可选件）

数据组做的一个**可选**推理期闸门，用来压掉「不该调工具却调了」。
**默认不启用**，接不接、接在哪由后端决定；这里提供方向、阈值和一个参考实现。

## 是什么

在残差流**第 48 层**（最后一层）取「模型即将写第一个 token」那一刻、
**最后一个 token** 的隐状态，往一个固定的 3072 维方向上做点积；
低于阈值就说明**这道题不该调工具**。

方向是用**差值均值**从模型自己的表示里算出来的，**不需要训练**。
线上代价是一次点积（3072 次乘加），可以忽略。

## 实测数字

模型 `adapter_93728_nothink_ep10_20260903_1832`，440 道考卷。
方向在**训练侧探针集**上取、AUROC 在**考卷**上报 —— 两边题目零重叠。

| | |
|---|---|
| 考卷 AUROC | **0.959** |
| 同样算法在 base 模型上 | 0.881 |
| gold 该调那 164 道，投影均值 | **+18.146** |
| gold 不该调那 95 道 | **−10.928** |

按阈值压制调用（低于阈值就不调）：

| 保住的正常调用 | 18 道误触发挡下 | 误触发率会变成 |
|---|---|---|
| **97.6%** | **13** | 30.5% → **8.5%** |
| 94.5% | 13 | 8.5% |
| 89.6% | 14 | 6.8% |
| 79.9% | 16 | 3.4% |
| 70.1% | 17 | 1.7% |

⚠️ 「保住 97.6%」的意思是：164 道该调的题里有 4 道会被误压。
**这是真代价，不是零成本。** 选哪一档取决于产品更怕哪一头。

## 怎么用

```python
from steer.tool_call_gate import ToolCallGate

gate = ToolCallGate.load(
    "steer/tool_call_direction_ep10.npz",
    expect_adapter="adapter_93728_nothink_ep10_20260903_1832",  # 必填
    keep_call_rate=0.976,        # 想保住多少正常调用
)

# 推理时：拿到第 48 层、最后一个 token 的隐状态
#   out = model(**enc, output_hidden_states=True)
#   h = out.hidden_states[gate.layer][0, -1, :]
if gate.should_suppress(h):
    ...  # 别调工具，改走直答 / 追问 / 拒绝
```

自检：`python steer/tool_call_gate.py`（七条，含三条反向验证）。

## 🔴 三条必须知道的

1. **方向绑定某一个 adapter。** 换了模型（哪怕只是多训几个 epoch）就必须重新导。
   拿旧方向配新模型量的是另一个东西，而且**不会有任何自然的报错** ——
   所以 `load()` 强制要求写明 `expect_adapter`，对不上直接抛 `AdapterMismatch`。
   **别把那个异常吞掉。**
2. **它判的是「该不该调」，不是「模型会不会错」。** 误触发只是「不该调」里最靠近
   边界的一批（投影 −5.969，而没误触发的是 −11.215、该调的是 +18.146）——
   离「该调」那组仍然很远，所以阈值卡在该调分布下沿就能挡住大半。
   要它去预测「模型在哪会犯错」，只有 AUROC 0.640，**别那么用**。
3. **需要拿到隐状态。** 走 OpenAI 兼容 API 的话拿不到，得在能访问
   `output_hidden_states` 的那一层接。这是接入的主要成本，也是为什么它是可选件。

## 换了模型怎么重新导

```bash
# 🖥️ 集群，一次前向不生成，约 19 分钟
sbatch ~/esa_hidden.sh <新的 adapter 目录>

# 然后导出方向 + 阈值表
PYTHONPATH=. python tools/probe_tool_direction.py \
    --fit  ~/esa_results/hidden_probe_<tag>.npz \
           ~/esa_results/hidden_probe_tool_<tag>.npz \
    --test ~/esa_results/hidden_main_<tag>.npz \
    --export steer/tool_call_direction_<tag>.npz
```

`esa_hidden.sh` 里有两道硬闸门：peft 注入的参数数必须 >0，
以及**开/关 adapter 各跑一次、隐状态逐位相同就退出**。
第二道是 2026-09-05 补的 —— 在那之前，加载类不对导致 adapter 一个模块都没注入，
跑出来的是 base 的数、而且看起来完全正常，是 base 对照跑出**一模一样的
13 个 AUROC** 才发现的。

## 出处

《Tunable Tool-Call Rates in LLM Agents via Representation Steering》
（[arXiv:2608.25198](https://arxiv.org/abs/2608.25198)）。
那篇是**加**一个方向去推动调用率；我们这里只做**读** ——
同一个前提，代价更小，也不改模型本身的行为。
