# backend/scripts/dataset/generators/gen_tool_errors.py

"""工具失败恢复（tool_error）生成器。

补的是全库最薄的一类：原来只有 8 条（web_search 5 + load_skill 404 3），
评测集只分到 3 条，任何指标都没有统计意义。

这里覆盖线上真实存在的三种失败形态（详见 seeds/tool_errors.yaml 的文件头）：
  ① 抛异常被 tool_register 包装成 "[Error]: …" 字符串
  ② 三个计算器不抛异常，失败也是正常返回一个带 error 键的 dict
  ③ 会话模式阻断 / 空结果，返回 allowed=False 或 count=0 + note

三种长得完全不同，恢复动作却是同一个：如实说明，绝不编结果。

观测值的来源，一条都不是写死的：
  ① 报错文案逐字取自后端源码，种子库里每条带 src 行号
  ② 由 data/cache/math_real.json 提供 —— 那是跑后端真实函数抓的
  ③ 由 fixtures 的 BLOCKED_BUILDERS / recommend_practice 真实计算

用法：
    python3 dataset/generators/gen_tool_errors.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa import fixtures  # noqa: E402
from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402
from esa.tools_exec import execute, latex_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/tool_errors.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/tool_errors.jsonl"
SOURCE = "gen_tool_errors.py"


def mk(sid, tpl, tools, turns, version, rng, all_names) -> Sample:
    """处理 `mk` 相关逻辑。

    Args:
        sid: object => `sid` 参数。
        tpl: object => `tpl` 参数。
        tools: object => 可用工具列表。
        turns: object => `turns` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。

    Returns:
        Sample => 处理结果。
    """
    return Sample(
        id=sid, template_id=tpl, category="tool_error", schema_version=version,
        system=system_for(turns),
        tool_names=pick_tool_names(tools, all_names, rng),
        source=SOURCE, turns=turns,
    )


def _fmt(text: str, **kw) -> str:
    """回答正文里可以用 {value} / {latex} / {err} 引用真实返回值。

    统一走 format：种子库里凡是要保留的花括号都写成 `{{}}`（LaTeX 的 \\sum_{{i=1}} 就是这么写的）。
    """
    return text.format(**kw).strip()


def gen_wrapped(cfg, version, rng, all_names, out) -> None:
    """① 抛异常 → tool_register.call 返回 f"[Error]: {e}"（tool_register.py:79-80）。

    观测是**字符串**不是 dict —— 这一点必须和线上一致，否则模型会以为失败也长成 JSON。
    """
    for item in cfg["wrapped"]:
        err = f"[Error]: {item['err']}"
        out.append(mk(
            f"toolerr_{item['id']}", f"toolerr__{item['tool']}__{item['id']}",
            item["lures"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall(item["tool"], item["args"])]),
             Turn(role="tool_result", results=[ToolResult(item["tool"], err, is_error=True)]),
             Turn(role="assistant", content=_fmt(item["a"], err=err, value="", latex=""))],
            version, rng, all_names))


def gen_calculators(cfg, version, rng, all_names, out) -> None:
    """② 三个计算器：失败是正常返回里的 error 键，不是异常。

    带 retry_args 的做成「报错 → 改对参数 → 成功 → 回答」四段式：
    这类失败源于 schema 没写清（binomial 的 expression 要写成 'n, r'，
    描述里一个例子都没有），模型第一次写错完全合理，读懂报错改对才是要教的能力。
    """
    for item in cfg["calculators"]:
        tool, args = item["tool"], item["args"]
        failed = execute(tool, args)
        if "error" not in failed:
            print(f"    ⚠️  {item['id']}: {tool}({args}) 居然成功了，种子写错了，已跳过")
            continue

        turns = [
            Turn(role="user", content=item["q"]),
            Turn(role="tool_call", calls=[ToolCall(tool, args)]),
            Turn(role="tool_result", results=[ToolResult(tool, failed, is_error=True)]),
        ]

        if item.get("retry_args") is not None:
            ok = execute(tool, item["retry_args"])
            if ok.get("result") is None:
                print(f"    ⚠️  {item['id']}: 重试参数仍然失败（{ok.get('error')}），已跳过")
                continue
            value = ok["result"]
            turns += [
                Turn(role="tool_call", calls=[ToolCall(tool, item["retry_args"])]),
                Turn(role="tool_result", results=[ToolResult(tool, ok)]),
                Turn(role="assistant",
                     content=_fmt(item["a_retry"], value=value,
                                  latex=_latex_or_blank(tool, value), err=failed["error"])),
            ]
        else:
            turns.append(Turn(role="assistant",
                              content=_fmt(item["a"], err=failed["error"], value="", latex="")))

        out.append(mk(
            f"toolerr_{item['id']}", f"toolerr__{tool}__{item['id']}",
            item["lures"], turns, version, rng, all_names))


def _latex_or_blank(tool: str, value) -> str:
    """math_solver 的 result 是纯文本 sympy 串，线上没有 latex 字段，要自己渲染。"""
    if tool != "math_solver":
        return str(value)
    return latex_of(str(value))


def gen_empty_result(cfg, version, rng, all_names, out) -> None:
    """③ 空结果：课程名不在知识图谱里，ranking 为空 → count=0 + note。

    观测由 fixtures.recommend_practice 真实计算（mastery_tools.py:160-168 的分支）。
    调用本身完全正确，模型无从预知库里有没有这门课。
    """
    for item in cfg["empty_result"]:
        result = fixtures.recommend_practice(item["course"], item["weeks_to_exam"])
        if result["count"] != 0:
            print(f"    ⚠️  {item['id']}: 课程 {item['course']!r} 居然在知识图谱里，"
                  f"拿不到空结果，已跳过")
            continue
        out.append(mk(
            f"toolerr_{item['id']}", f"toolerr__recommend_practice__{item['id']}",
            item["lures"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call",
                  calls=[ToolCall("recommend_practice",
                                  {"course": item["course"], "weeks_to_exam": item["weeks_to_exam"]})]),
             Turn(role="tool_result",
                  results=[ToolResult("recommend_practice", result, is_error=True)]),
             Turn(role="assistant",
                  content=_fmt(item["a"], note=result["note"], course=item["course"],
                               courses="、".join(fixtures.known_courses()[:6]),
                               err="", value="", latex=""))],
            version, rng, all_names))


def gen_blocked(cfg, version, rng, all_names, out) -> None:
    """③ 会话模式阻断：allowed/saved 为 False + 一句 reason。

    既不是 [Error]: 也没有 error 键 —— 这是第三种失败长相。
    观测由 fixtures.blocked_learning 按**真实抓取**产出（learning_real.json 钉住）。

    ⚠️ 只有学情工具走这一支。记忆工具在受限会话里根本不在工具表里，
    「调了被拒」的场景线上不存在，那 4 条样本已删（见种子文件里的说明）。

    ⚠️ 工具表也要按模式裁：isolated 会话里模型看不见记忆工具，
    干扰项里摆一个它看不见的工具，等于教它一个线上不成立的选择题。
    """
    for item in cfg["blocked"]:
        tool, mode = item["tool"], item["mode"]
        result = fixtures.BLOCKED_BUILDERS[tool](mode=mode)
        visible = fixtures.memory_tools_available(mode)
        out.append(mk(
            f"toolerr_{item['id']}", f"toolerr__{tool}__{item['id']}",
            item["lures"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall(tool, item["args"])]),
             Turn(role="tool_result", results=[ToolResult(tool, result, is_error=True)]),
             Turn(role="assistant",
                  content=_fmt(item["a"], reason=result["reason"], err="", value="", latex=""))],
            version, rng, [n for n in all_names if n in visible]))


def gen_denied(cfg, version, rng, all_names, out) -> None:
    """④ 策略拒绝：`{"ok": false, "error": <码>, "tool": ..., "detail": <文案>}`。

    第四种失败长相，键名和前三种全都不一样，是 BoundToolExecutor 把
    MemoryPolicyDenied / ValueError 接住后包出来的（capability_runtime.py:151-171）。
    与会话模式无关 —— 普通会话里存一句带 API Key 的内容就会走到这里。
    """
    for item in cfg.get("denied", []):
        tool, args = item["tool"], item["args"]
        result = execute(tool, args)
        if result.get("ok") is not False:
            print(f"    ⚠️  {item['id']}: {tool}({args}) 居然没被拒，种子写错了，已跳过")
            continue
        out.append(mk(
            f"toolerr_{item['id']}", f"toolerr__{tool}__{item['id']}",
            item["lures"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall(tool, args)]),
             Turn(role="tool_result", results=[ToolResult(tool, result, is_error=True)]),
             Turn(role="assistant",
                  content=_fmt(item["a"], reason=result["detail"], err="", value="", latex=""))],
            version, rng, all_names))


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260810)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    out: list[Sample] = []

    gen_wrapped(cfg, version, rng, all_names, out)
    gen_calculators(cfg, version, rng, all_names, out)
    gen_empty_result(cfg, version, rng, all_names, out)
    gen_blocked(cfg, version, rng, all_names, out)
    gen_denied(cfg, version, rng, all_names, out)

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    shapes = Counter()
    for s in out:
        r = [x for t in s.turns for x in t.results if x.is_error][0].content
        if isinstance(r, str):
            shapes["① [Error]: 字符串"] += 1
        elif r.get("ok") is False:
            shapes["④ 执行器包的 ok/error/detail"] += 1
        elif "error" in r:
            shapes["② 带 error 键的 dict"] += 1
        else:
            shapes["③ 阻断 / 空结果"] += 1
    for k, n in sorted(shapes.items()):
        print(f"  {k:22s} {n}")
    n_retry = sum(1 for s in out if len(s.called_tool_names()) > 1)
    print(f"  其中「改参数重试成功」{n_retry} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
