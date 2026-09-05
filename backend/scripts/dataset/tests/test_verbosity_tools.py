# backend/scripts/dataset/tests/test_verbosity_tools.py

"""4.3m 那两个诊断工具的自测（不需要 GPU，也不需要 torch）。

要守的是两条会**静默出错**的地方：

1. `dump_train_labels._FROM_TO_ROLE` 必须覆盖真实训练文件里出现的全部 `from` 值。
   漏一个不会报错吗？会 —— 我们让它 raise。但如果哪天有人图省事改成
   `.get(x, "user")`，`function_call` 就会被当成用户消息，计损段整个错位，
   而结论照样会打印出来。所以用**真文件**去验，不是用手写的样例。

2. `measure_verbosity.quantiles` 的分位数取法。分位数算错不会崩，
   只会让「微调后掉了多少字」这个数悄悄失真。

    python3 dataset/tests/test_verbosity_tools.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from dataset.esa.preds import load_preds_file  # noqa: E402
from dataset.esa.ir import Sample, Turn  # noqa: E402
from dataset.esa.validate import check_shape  # noqa: E402
from dataset.tools.dump_train_labels import _FROM_TO_ROLE, to_messages  # noqa: E402
from dataset.tools.measure_verbosity import quantiles  # noqa: E402

TRAIN = ROOT / "data" / "out" / "esa_agent_train.jsonl"


def check_roles_cover_real_file() -> list[tuple[str, bool]]:
    if not TRAIN.exists():
        return [(f"跳过：{TRAIN} 不存在（先跑 esa.build）", True)]

    seen: set[str] = set()
    rows = 0
    with TRAIN.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows += 1
            for c in json.loads(line)["conversations"]:
                seen.add(c["from"])

    unmapped = seen - set(_FROM_TO_ROLE)
    return [
        (f"角色表覆盖真实训练文件出现的全部 from 值"
         f"（{rows} 条，见到 {sorted(seen)}）", not unmapped),
    ]


def check_unknown_role_raises() -> list[tuple[str, bool]]:
    try:
        to_messages([{"from": "赛博朋克", "value": "x"}])
    except ValueError:
        raised = True
    except Exception:
        raised = False
    else:
        raised = False
    return [("未知 from 值必须 raise，不许默默当成 user", raised)]


def check_role_mapping_is_not_identity() -> list[tuple[str, bool]]:
    msgs = to_messages([
        {"from": "human", "value": "a"},
        {"from": "function_call", "value": "b"},
        {"from": "observation", "value": "c"},
        {"from": "gpt", "value": "d"},
    ])
    roles = [m["role"] for m in msgs]
    return [
        ("sharegpt → 内部角色映射正确"
         f"（得到 {roles}）",
         roles == ["user", "function", "observation", "assistant"]),
    ]


def check_quantiles() -> list[tuple[str, bool]]:
    vals = list(range(1, 101))  # 1..100
    q = quantiles(vals)
    out = [
        ("分位数：n 对", q["n"] == 100),
        ("分位数：中位落在 51（下标 50）", q["med"] == 51),
        ("分位数：p10 落在 11", q["p10"] == 11),
        ("分位数：max 是真的最大值", q["max"] == 100),
        ("分位数：空列表返回空字典，不抛异常", quantiles([]) == {}),
        ("分位数：单元素时四个数都是它", quantiles([7])["med"] == 7
         and quantiles([7])["p90"] == 7 and quantiles([7])["max"] == 7),
    ]
    return out


def check_pred_meta_line() -> list[tuple[str, bool]]:
    """预测文件首行是 `_meta` 指纹行、**没有 `id`**。

    2026-08-26 `measure_verbosity` 第一版自己写了读取、直接 `r["id"]`，
    在集群上当场 KeyError —— 而 eval.py 里 predict 那段的注释早就写了
    「`load_preds` 会跳过没有 id 的行」。现在两边共用 `load_preds_file`。
    """
    import json
    import tempfile

    # 顺带守住「轻工具不拖重依赖」：import esa.preds 不许把 jsonschema
    # 之类拉进来（2026-08-26 集群上就是这么炸的）。
    # 🔴 **必须开子进程量**：本文件自己 import 了 esa.validate，它会把 jsonschema
    #    拉进 sys.modules —— 在本进程里数 sys.modules，量的是测试文件的依赖，
    #    不是 esa.preds 的。第一版就是这么写错的，当场红了一条。
    import subprocess
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);"
         "import esa.preds;"
         "print(','.join(sorted(m for m in ('jsonschema','transformers','torch')"
         " if m in sys.modules)))" % str(ROOT)],
        capture_output=True, text=True)
    heavy = [m for m in probe.stdout.strip().split(",") if m]

    lines = [
        {"_meta": {"eval_fingerprint": "deadbeef1234abcd#443", "tag": "base"}},
        {"id": "q1", "raw": "<think>\n想一想\n</think>\n\n答案一"},
        {"id": "q2", "raw": "答案二"},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as fh:
        for r in lines:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        path = Path(fh.name)
    try:
        meta, preds = load_preds_file(path)
    finally:
        path.unlink()

    return [
        (f"轻工具不拖重依赖：import esa.preds 没加载 {('/'.join(heavy)) or 'jsonschema/transformers/torch'}",
         not heavy),
        ("预测文件：首行 _meta 不被当成一条预测（曾在这里 KeyError）",
         set(preds) == {"q1", "q2"}),
        ("预测文件：_meta 里的指纹被返回，可用来验考卷配不配套（5.59）",
         meta.get("eval_fingerprint") == "deadbeef1234abcd#443"),
        ("预测文件：raw 原样返回，不做解析",
         preds["q2"] == "答案二"),
    ]


def _s(sid: str, tpl: str, answer: str) -> "Sample":
    return Sample(id=sid, template_id=tpl, category="hard_negative",
                  schema_version="x", system="s", tool_names=[],
                  turns=[Turn(role="user", content="q"),
                         Turn(role="assistant", content=answer)])


def check_shape_gates() -> list[tuple[str, bool]]:
    """L2 形状闸门：默认只报不拦，--strict-shape 才判不合格。

    这两条是 2026-08-26 试跑当场翻出来的真实缺陷，不是假想：
      · 两个问不同问题的模板，回答一字不差
      · 同一模板下几十条回答长度恒定（长度是模板常量，不随内容变）
    """
    dup = [_s("a", "tpl_A", "完全一样的一段回答"),
           _s("b", "tpl_B", "完全一样的一段回答")]
    flat = [_s(f"f{i}", "tpl_F", "长度基本一样的一段话" + "。" * (i % 3))
            for i in range(8)]
    varied = [_s(f"v{i}", "tpl_V", "长度差很多" + "。" * (i * 12))
              for i in range(8)]

    out = []
    lenient = check_shape(dup + flat, strict=False)
    out.append(("形状闸门：默认只报不拦，一个 Finding 都不产生", lenient == []))

    # 🔴 A 是线索不是判据：真缺陷「问的不是一回事却给同一答案」需要语义判断，
    #    两版都做不精确（工具返回相同、算式不同结果相同都会误报），所以它
    #    连 strict 下都不产生 Finding。误报的硬闸门会被无视，比没有更糟。
    out.append(("形状 A：只出线索清单，strict 下也不判不合格",
                check_shape(dup, strict=True) == []))

    # 🔴 B 也降级为线索：template_id 的定义就是「同一事实组合的所有话术」，
    #    同模板内工具返回必然相同，长度恒定往往是**对的**（S002 那 16 条是
    #    同一个问题的 16 种说法）。而 S003 那 65 条工具返回也相同却是真缺陷。
    #    区别在「问的是不是一回事」——语义判断，做不成硬闸门。
    out.append(("形状 B：只出线索清单，strict 下也不判不合格",
                check_shape(flat, strict=True) == []))
    out.append(("形状：三条合起来也不产生任何 Finding",
                check_shape(dup + flat + varied, strict=True) == []))

    # C 只算下界，任何情况下都不产生 Finding
    noex = [_s(f"c{i}", f"tpl_C{i}", "这是一段很长的回答。" * 20) for i in range(3)]
    out.append(("形状 C：例子出现率只算下界，永远不判不合格（5.57）",
                [f for f in check_shape(noex, strict=True)
                 if f.check.startswith("shape_example")] == []))
    return out


def main() -> int:
    checks: list[tuple[str, bool]] = []
    checks += check_roles_cover_real_file()
    checks += check_unknown_role_raises()
    checks += check_role_mapping_is_not_identity()
    checks += check_quantiles()
    checks += check_pred_meta_line()
    checks += check_shape_gates()

    ok = 0
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        ok += passed
    print(f"\n{ok} 通过 / {len(checks) - ok} 失败")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
