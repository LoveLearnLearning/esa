#!/usr/bin/env python3
"""闸门：恢复话术不许引用模型看不见的东西。

这道守的是什么
--------------
2026-09-02 查出 24 条样本在教模型**编造技术原因**：

    数据里的工具返回  "[Error]: arXiv API 请求超时（已重试 5 次）"
    我们教的回答      「arXiv 那边没响应（[Error]: arXiv API 请求超时（已重试 5 次））…」
    模型实际看到      {"ok":false,"error_code":"tool_internal_error",
                       "message":"工具暂时无法完成请求，请稍后重试"}

上游 `d29d3e4` 之后，**每个工具返回都过 `normalize_tool_error_result`**
（`capability_runtime.py:101`，在 try 块之外的正常返回路径上），
错误载荷被统一成 `{ok,error_code,error,retryable,tool,attempt,message}`，
原文塞进 `audit_metadata.legacy_*` —— 模型看不见。

于是那些话术在教模型：**看到一句笼统的失败文案，就编出一个具体原因并加括号引用。**
这正对着本数据集最核心的主张（不编造）。

🔴 **为什么原有闸门没拦住**：`validate` 的 `error_text` 要求报错文案必须在
`seeds/tool_errors.yaml` 的 `registry` 登记，"不许凭印象编报错" ——
它查的是**数据里的载荷**，没查**那个载荷模型是不是真看得到**。
5.18 的第五次同形，也是最贵的一次：查了 A（文案登记），没查 B（可见性）。

判据
----
对每条带 `is_error` 结果的样本：把载荷过一遍 `normalize_tool_error_result`，
拿到模型真正会看到的那一层；凡是**只在原始载荷里出现、可见载荷里没有**的字符串，
如果末轮回答引用了它（≥6 字的子串），就是不合格。

⚠️ 不 import 整个后端（依赖装不全），只 import `execution_errors` 那一个模块。
找不到就明确报错、不放行（5.72）。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
IR = HERE.parent / "data" / "ir"
MIN_QUOTE = 6          # 少于这个长度的重合当巧合，不判


def _known_codes() -> set[str]:
    """协议里合法的 error_code —— 从后端源码读，不手写。"""
    for repo in (pathlib.Path.home() / "esa", HERE.parents[3]):
        f = repo / "backend" / "agent" / "tools" / "execution_errors.py"
        if f.is_file():
            import re as _re
            body = f.read_text(encoding="utf-8").split("ERROR_MESSAGES")[1].split("}")[0]
            return set(_re.findall(r'"([a-z_]+)":', body))
    return set()


KNOWN_CODES: set[str] = set()


def _load_normalizer():
    for repo in (pathlib.Path.home() / "esa", HERE.parents[3]):
        if (repo / "backend" / "agent" / "tools" / "execution_errors.py").is_file():
            sys.path.insert(0, str(repo))
            from backend.agent.tools.execution_errors import (  # noqa: PLC0415
                normalize_tool_error_result,
            )
            return normalize_tool_error_result, repo
    sys.exit("❌ 找不到 backend/agent/tools/execution_errors.py —— "
             "这道闸门要拿它算「模型看得见的那一层」，找不到就不能放行（5.72）")


def _strings(value) -> set[str]:
    """把载荷里所有字符串值摊平（键名不算，模型读的是值）。"""
    out: set[str] = set()
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            out |= _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= _strings(v)
    return out


def main() -> int:
    global KNOWN_CODES
    normalize, repo = _load_normalizer()
    KNOWN_CODES = _known_codes()
    print(f"对着 {repo} 算「模型看得见的那一层」")

    bad: list[tuple[str, str]] = []
    notfixed: list[tuple] = []
    checked = 0
    for path in sorted(IR.glob("*.jsonl")):
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            s = json.loads(line)
            answer = ""
            # 🔴 «模型看得见的» 不只是工具返回：用户说过的话、以及**它自己发出去的
            #    tool_call 参数**，都在上下文里。2026-09-02 第一版闸门漏了这两处，
            #    把 `toolerr_calc_unknown_function`（用户问「帮我算 arcsin(0.5)」、
            #    模型自己传了 expression="arcsin(0.5)"）误判成幻觉 —— 那条恰恰是
            #    好样本：发现 arcsin 不认、改成 asin 重试。误报的闸门比没有更糟（5.67）。
            context: set[str] = set()
            for t in s.get("turns", []):
                if t.get("role") == "assistant" and t.get("content"):
                    answer = t["content"]
                if t.get("role") == "user" and t.get("content"):
                    context.add(t["content"])
                for c in t.get("calls", []) or []:
                    context |= _strings(c.get("arguments") or {})
            if not answer:
                continue
            for t in s.get("turns", []):
                for r in t.get("results", []) or []:
                    if not r.get("is_error"):
                        continue
                    raw = r.get("content")
                    out = normalize(raw, tool=r.get("tool", "?"), attempt=1)
                    visible = getattr(out, "model_content", out)
                    # 判据三：`[Error]:` 是旧包装的特征，线上已经不存在这个形态了。
                    # 话术里出现它 = 编了一个载荷里没有的原文。
                    # 🔴 这条是 2026-09-02 反向验证逼出来的：判据二只看「载荷被改写时
                    #    丢了什么」，所以当载荷已经是统一协议（不动点）时，
                    #    话术凭空编一句 `[Error]: …` 它一声不吭。
                    if "[Error]" in answer and "[Error]" not in json.dumps(
                            visible, ensure_ascii=False):
                        bad.append((s["id"], "[Error]:（旧格式标记，线上已不存在）"))
                        continue
                    if visible == raw:
                        continue           # 没被改写，话术引用的就是模型看见的
                    checked += 1
                    # 判据一（强）：错误载荷必须是 normalize 的**不动点**。
                    # 变了就说明数据里存的不是模型看得见的那一层。
                    notfixed.append((s["id"], r.get("tool", "?"), raw, visible))
                    # 判据二（更重）：话术引用了被改写时丢掉的内容 = 教模型编造。
                    lost = _strings(raw) - _strings(visible)
                    for frag in lost:
                        if len(frag) < MIN_QUOTE or frag not in answer:
                            continue
                        # 用户说过、或模型自己传过的，不算「看不见」
                        if any(frag in c for c in context):
                            continue
                        bad.append((s["id"], frag))
                        break

    print(f"检查了 {checked} 条「载荷会被协议改写」的样本")
    if notfixed:
        byid = {}
        for sid, tool, raw, vis in notfixed:
            code = vis.get("error_code") if isinstance(vis, dict) else "?"
            byid.setdefault(code, []).append(sid)
        ours = {c: v for c, v in byid.items() if c in KNOWN_CODES}
        theirs = {c: v for c, v in byid.items() if c not in KNOWN_CODES}
        print(f"\n⚠️ 线索（不判不合格）：{len(notfixed)} 条载荷不是 normalize 的不动点")
        if ours:
            print("   ── 我们能修的（error_code 在协议枚举里，数据没跟上）：")
            for c, ids in sorted(ours.items(), key=lambda x: -len(x[1])):
                print(f"      → {c}：{len(ids)} 条  例 {ids[0]}")
        if theirs:
            print("   ── 🔴 等后端的（error_code **不在** 16 个枚举里，"
                  "是 normalize 拿业务错误文案当 code 造成的）：")
            for c, ids in sorted(theirs.items(), key=lambda x: -len(x[1]))[:6]:
                print(f"      → {c!r}：{len(ids)} 条  例 {ids[0]}")
            if len(theirs) > 6:
                print(f"      …… 还有 {len(theirs) - 6} 种")
            print("      **不要照抄进数据** —— 那是把后端的 bug 固化成训练目标。")
    if bad:
        print(f"\n❌ {len(bad)} 条回答引用了模型看不见的内容：")
        for sid, frag in bad[:12]:
            print(f"   {sid:44} 引用了「{frag[:56]}」")
        if len(bad) > 12:
            print(f"   …… 还有 {len(bad) - 12} 条")
        print("\n   这些话术在教模型：看到一句笼统的失败文案，就编出一个具体原因。")
        print("   修法是把载荷换成模型真会看到的那一层，话术照着新载荷重写。")
        return 1
    print("✅ 没有回答引用模型看不见的内容")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
