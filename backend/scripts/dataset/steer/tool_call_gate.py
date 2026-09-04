#!/usr/bin/env python3
"""推理期闸门：从隐状态判断「这一刻该不该调工具」，用来压掉误触发。

一句话
------
在残差流第 **48** 层（最后一层）取「模型即将写第一个 token」那一刻的隐状态，
往一个固定方向上投影；投影低于阈值就说明**这道题不该调工具**。
方向是从模型自己的表示里用差值均值算出来的，**不需要训练**，一次点积就够。

实测（`adapter_93728_nothink_ep10_20260903_1832`，440 道考卷）
-------------------------------------------------------------
方向在训练侧探针集上取、AUROC 在考卷上报，两边题目不重叠：

    考卷 AUROC = 0.959          base 模型同样算法只有 0.881
    gold 该调 164 道 投影均值 +18.146    不该调 95 道 −10.928

按阈值压制调用的代价/收益：

    保住 97.6% 的正常调用  →  18 道误触发挡下 13 道  →  FPR 30.5% → 8.5%
    保住 89.6%             →  挡下 14 道            →  FPR 6.8%
    保住 79.9%             →  挡下 16 道            →  FPR 3.4%

🔴 三条必须知道的
-----------------
1. **方向绑定某一个 adapter。** 换了模型（哪怕只是多训几个 epoch）就得重新导，
   拿旧方向去配新模型量的是另一个东西，而且**不会有任何报错**。
   所以 `load()` 强制要求调用方写明期望的 adapter 名，对不上直接抛。
   重新导的办法见 `dataset/steer/README.md`。
2. **它压的是「该不该调」，不是「模型会不会错」。** 误触发只是「不该调」里
   最靠近边界的一批（投影 −5.969，而没误触发的是 −11.215、该调的是 +18.146）——
   离「该调」那组仍然很远，所以阈值卡在该调分布的下沿就能挡住大半。
   别指望它去预测模型在哪犯错，那件事它只能做到 AUROC 0.640。
3. **这是数据组给的一个可选件，默认不启用。** 它是推理侧的东西，
   要不要接、接在哪，是后端的决定。这里只提供方向、阈值和一个参考实现。

出处
----
《Tunable Tool-Call Rates in LLM Agents via Representation Steering》
(arXiv:2608.25198)。那篇做的是**加**一个方向去推动调用率；
我们这里只做**读**——同一个前提，代价更小，也不改模型行为本身。
"""
from __future__ import annotations

import pathlib

import numpy as np


class AdapterMismatch(RuntimeError):
    """方向与模型对不上。**不要 catch 掉继续跑** —— 那就是拿错尺子量。"""


class ToolCallGate:
    """把方向 + 阈值包成一个可调用的闸门。

    Attributes:
        layer: 该在第几层取隐状态（取最后一个 token）。
        threshold: 低于它就判「不该调」。
        keep_call_rate: 这个阈值下，正常调用能保住多少（实测值，供调用方权衡）。
        auroc: 导出时在考卷上测到的可分性。
    """

    def __init__(self, direction: np.ndarray, layer: int, threshold: float,
                 keep_call_rate: float, auroc: float, adapter: str):
        self.direction = np.asarray(direction, dtype=np.float32)
        self.layer = int(layer)
        self.threshold = float(threshold)
        self.keep_call_rate = float(keep_call_rate)
        self.auroc = float(auroc)
        self.adapter = str(adapter)

    @classmethod
    def load(cls, path: str | pathlib.Path, *, expect_adapter: str,
             keep_call_rate: float = 0.976) -> "ToolCallGate":
        """读方向文件。

        Args:
            path: `tool_call_direction_*.npz`。
            expect_adapter: **调用方必须写明**自己加载的是哪个 adapter。
                对不上就抛 `AdapterMismatch` —— 这道检查存在的理由是
                「拿旧方向配新模型」不会有任何自然的报错。
            keep_call_rate: 想保住多少正常调用（0.976 / 0.945 / 0.896 / 0.799 / 0.701）。
                取最接近的那一档，并把实际取到的值记在 `self.keep_call_rate`。

        Raises:
            AdapterMismatch: `expect_adapter` 与文件里记的对不上。
        """
        d = np.load(pathlib.Path(path), allow_pickle=True)
        got = str(d["adapter"])
        if got != expect_adapter:
            raise AdapterMismatch(
                f"方向是从 {got!r} 导的，而你加载的是 {expect_adapter!r}。\n"
                "方向绑定某一个 adapter —— 换了模型必须重新导（见 steer/README.md）。\n"
                "🔴 别把这个异常吞掉：拿旧方向配新模型不会报错，只会静默量错。")
        rates = np.asarray(d["keep_call_rate"], dtype=np.float32)
        i = int(np.argmin(np.abs(rates - keep_call_rate)))
        return cls(direction=d["direction"], layer=int(d["layer"]),
                   threshold=float(np.asarray(d["thresholds"])[i]),
                   keep_call_rate=float(rates[i]), auroc=float(d["auroc"]),
                   adapter=got)

    def score(self, hidden: np.ndarray) -> float:
        """把隐状态投到方向上。越大越像「该调工具」。

        Args:
            hidden: 第 `self.layer` 层、**最后一个 token** 的隐状态，形状 (hidden_size,)。
                也就是 `output_hidden_states=True` 时 `hidden_states[layer][0, -1, :]`。
        """
        h = np.asarray(hidden, dtype=np.float32).reshape(-1)
        if h.shape != self.direction.shape:
            raise ValueError(
                f"隐状态维度 {h.shape} 与方向 {self.direction.shape} 对不上 —— "
                "多半是取错了层或者取的不是最后一个 token")
        return float(h @ self.direction)

    def should_suppress(self, hidden: np.ndarray) -> bool:
        """True = 这一刻不该调工具，建议改走直答 / 追问 / 拒绝。"""
        return self.score(hidden) < self.threshold

    def __repr__(self) -> str:  # pragma: no cover - 只为日志好看
        return (f"ToolCallGate(layer={self.layer}, threshold={self.threshold:+.3f}, "
                f"keep_call_rate={self.keep_call_rate:.1%}, auroc={self.auroc:.3f}, "
                f"adapter={self.adapter!r})")


def _self_test() -> int:
    """反向验证：闸门必须在该报的时候报、不该报的时候不报。"""
    here = pathlib.Path(__file__).resolve().parent
    npz = here / "tool_call_direction_ep10.npz"
    if not npz.is_file():
        print(f"❌ 找不到 {npz}")
        return 1
    ok = 0
    cases = []

    d = np.load(npz, allow_pickle=True)
    adapter = str(d["adapter"])
    g = ToolCallGate.load(npz, expect_adapter=adapter)
    cases.append(("adapter 对得上 → 正常加载", True))
    cases.append((f"层号 = {g.layer}，维度 = {g.direction.shape[0]}",
                  g.layer == 48 and g.direction.shape[0] == 3072))

    try:
        ToolCallGate.load(npz, expect_adapter="别的模型")
        cases.append(("adapter 对不上 → 必须抛", False))
    except AdapterMismatch:
        cases.append(("adapter 对不上 → 必须抛", True))

    # 沿方向正向走足够远 = 该调；反向 = 不该调
    hi = g.direction * (abs(g.threshold) + 100.0)
    lo = -hi
    cases.append(("强正向投影 → 不压制", g.should_suppress(hi) is False))
    cases.append(("强反向投影 → 压制", g.should_suppress(lo) is True))

    try:
        g.score(np.zeros(7))
        cases.append(("维度不对 → 必须抛", False))
    except ValueError:
        cases.append(("维度不对 → 必须抛", True))

    # 换一档阈值，保住的调用比例必须跟着变
    g2 = ToolCallGate.load(npz, expect_adapter=adapter, keep_call_rate=0.70)
    cases.append(("换保守档 → 阈值更高、保住的调用更少",
                  g2.threshold > g.threshold and g2.keep_call_rate < g.keep_call_rate))

    for name, passed in cases:
        print(f"{'✅' if passed else '❌'} {name}")
        ok += bool(passed)
    print(f"\n{ok} 通过 / {len(cases) - ok} 失败")
    print(f"\n{g!r}")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
