# backend/scripts/dataset/tools/capture_parser_golden.py

"""拿**后端真实 parse_output** 跑一批输入，把结果存成黄金样例。

为什么要有这个脚本
------------------
`esa/backend_parser.py` 是后端解析器的一份本地复刻。复刻是不得已 ——
评测器要在没有后端源码的机器上跑（超算、别人 clone 下来的数据集仓库）。

代价是它会悄悄和后端脱节。2026-08-11 就发生了一次：后端加了
「按 schema 恢复参数类型」（`parser.py:79-99` + `tool_arguments.py:88-137`），
我们这边还是旧版，于是 `<parameter=lower>0</parameter>` 在后端是字符串 `"0"`、
在我们这里是整数 `0`。**没有任何东西会报错**，只有评测分数悄悄和线上对不上。

所以把真实后端的输出钉下来，由 `tests/test_parser_compat.py` 逐条比对。
指纹对不上就说明后端改了解析器 —— 重抓，按差异改 `backend_parser.py`。

输入从哪来
----------
1. 真实数据渲染出的线上文本（`render.assistant_wire_segments`），覆盖实际会遇到的调用
2. 一组**故意刁钻**的手写用例：string 类型的 "0"、enum 越界、布尔字符串、
   数组/对象的字符串形式、未知工具、坏 XML —— 类型恢复的边界全在这里

用法
----
    python3 dataset/tools/capture_parser_golden.py            # 默认用本地 ~/esa
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_repo  # noqa: E402

from esa.ir import iter_ir_files, load_samples, load_schemas, schemas_by_name  # noqa: E402
from esa.render import assistant_wire_segments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
IR_DIR = ROOT / "dataset/data/ir"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/cache/parser_golden.json"
PARSER_SOURCES = ["backend/core/utils/parser.py", "backend/core/utils/tool_arguments.py"]

# 手写的边界用例。每一条都对应一个"复刻很容易写错"的地方。
EDGE_CASES = [
    # string 类型的 "0" —— 不能被 json.loads 变成整数（这次脱节的正是它）
    "<tool_call><function=math_solver><parameter=operation>integrate</parameter>"
    "<parameter=expression>x**2</parameter><parameter=variable>x</parameter>"
    "<parameter=lower>0</parameter><parameter=upper>1</parameter></function></tool_call>",
    # integer 类型收到字符串
    "<tool_call><function=recommend_practice><parameter=course>操作系统</parameter>"
    "<parameter=count>3</parameter></function></tool_call>",
    # boolean 的字符串形式
    "<tool_call><function=record_learning_evidence><parameter=kp_id>os_scheduling</parameter>"
    "<parameter=independent>true</parameter></function></tool_call>",
    # enum 越界 —— 后端会抛 ValueError 然后原样保留
    "<tool_call><function=math_solver><parameter=operation>不存在的操作</parameter>"
    "<parameter=expression>x</parameter><parameter=variable>x</parameter></function></tool_call>",
    # 未知工具：没有 schema，全走 _try_cast
    "<tool_call><function=完全不存在的工具><parameter=a>0</parameter></function></tool_call>",
    # 坏 XML：匹配不到 <function=...>，后端 continue → 返回空对象
    "<tool_call>{\"name\": \"calculator\", \"arguments\": {\"expression\": \"1+1\"}}</tool_call>",
    # 纯文本 + think
    "<think>先想一下</think>不需要调用工具，直接回答就行。",
    # 空参数值
    "<tool_call><function=calculator><parameter=expression></parameter></function></tool_call>",
    # 并行调用
    "<tool_call><function=get_time></function></tool_call>"
    "<tool_call><function=get_weather><parameter=city>北京</parameter></function></tool_call>",
]


def to_jsonable(parsed) -> dict:
    """转换 `jsonable` 相关数据。"""
    d = asdict(parsed) if is_dataclass(parsed) else dict(parsed)
    return {
        "reasoning": d.get("reasoning"),
        "content": d.get("content"),
        "tool_calls": [
            {"name": c["name"], "arguments": c["arguments"]} if isinstance(c, dict)
            else {"name": c.name, "arguments": c.arguments}
            for c in d.get("tool_calls", [])
        ],
    }


def collect_inputs(by_name: dict) -> list[str]:
    """真实数据渲染出的线上文本 + 手写边界用例。

    两种 tool_format 都要抓：
      xml  —— 后端 parse_output 期望的格式，类型恢复逻辑全在这条路径上
      qwen —— LLaMA-Factory 实际会训出来的格式，喂给后端就是 6.1 那个静默失败。
              把它的真实结果也钉住，免得哪天"静默失败"被悄悄改掉而我们没发现。
    """
    texts: list[str] = []
    seen: set[str] = set()
    for f in iter_ir_files(IR_DIR):
        for s in load_samples(f):
            for fmt in ("xml", "qwen"):
                for seg in assistant_wire_segments(s, by_name, fmt):
                    if seg and seg not in seen:
                        seen.add(seg)
                        texts.append(seg)
    for case in EDGE_CASES:
        if case not in seen:
            seen.add(case)
            texts.append(case)
    return texts


def main() -> int:
    """运行当前模块的命令行入口。"""
    ap = argparse.ArgumentParser(description="抓取后端 parse_output 的黄金样例")
    ap.add_argument("--repo", help="本地后端仓库副本；默认 ~/esa")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    schemas, schema_version = load_schemas(SCHEMAS)
    by_name = schemas_by_name(schemas)
    inputs = collect_inputs(by_name)

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        sys.path.insert(0, str(backend.path))
        try:
            from backend.core.utils.parser import parse_output  # noqa: PLC0415
        except ImportError as exc:
            raise SystemExit(f"无法 import 后端 parse_output：{exc}") from exc

        fingerprint = {}
        for rel in PARSER_SOURCES:
            p = backend.path / rel
            if not p.exists():
                raise SystemExit(f"后端仓库里找不到 {rel}，路径可能变了")
            fingerprint[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]

        cases = [
            {"input": text, "expected": to_jsonable(parse_output(text, schemas))}
            for text in inputs
        ]

        payload = {
            "_meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "source_sha256": fingerprint,
                "schema_version": schema_version,
                "note": (
                    "由 dataset/tools/capture_parser_golden.py 调用后端真实 parse_output 产出。"
                    "tests/test_parser_compat.py 断言 esa/backend_parser.py 逐条复现它。禁止手改"
                ),
            },
            "cases": cases,
        }
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    n_calls = sum(len(c["expected"]["tool_calls"]) for c in cases)
    print(f"\n抓到 {len(cases)} 条黄金样例（共 {n_calls} 次工具调用）→ {out_path.relative_to(ROOT)}")
    print(f"  来源：{backend.describe()}")
    for rel, h in fingerprint.items():
        print(f"  {h}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
