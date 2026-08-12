"""ESA 数据集的中间表示（IR）。

所有生成器只产出 IR，绝不直接产出训练用的 ShareGPT jsonl。渲染由 render.py 负责。

这样做的理由：工具调用的线上格式（Qwen 原生 JSON vs 自定义 XML）还没和后端定下来。
IR 只记录「调用了哪个工具、参数是什么」这个语义事实，格式怎么变都只需要重新渲染一次。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# IR 的四种角色。注意这套角色和 ShareGPT 的 from 字段不是一一对应，
# 映射关系在 render.py 里，因为 LLaMA-Factory 对角色顺序有强制要求。
ROLE_USER = "user"
ROLE_TOOL_CALL = "tool_call"
ROLE_TOOL_RESULT = "tool_result"
ROLE_ASSISTANT = "assistant"

# 数据类别。评测指标按这个维度分组统计，所以必须是受控词表。
CATEGORIES = {
    "plain_qa",          # 不调用工具的普通回答
    "concept",           # 概念讲解
    "single_tool_call",  # 单工具调用正样本
    "hard_negative",     # 困难负样本：给了工具但不该调
    "multi_turn_tool",   # 多轮 / 链式工具调用
    "clarify",           # 参数缺失时追问
    "tool_error",        # 工具异常恢复
    "refusal",           # 越权 / 拒绝
    "parallel_tool_call",  # 并行工具调用
}


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    name: str
    content: Any
    # 工具是否执行失败。tool_error 类样本用它标记，渲染时不做特殊处理，
    # 但校验器据此放宽「最终回答必须引用工具返回值」的检查。
    is_error: bool = False


@dataclass
class Turn:
    role: str
    content: str | None = None
    calls: list[ToolCall] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)


@dataclass
class Sample:
    id: str
    template_id: str
    category: str
    schema_version: str
    system: str
    tool_names: list[str]
    turns: list[Turn]
    # 生成来源，便于出问题时回溯是哪个生成器写的
    source: str = ""
    # 概念讲解类样本讲的是哪个知识点（kp_id）。事实核查靠它定位该样本允许出现哪些断言。
    topic: str = ""
    # 无法自动核验、需要人工过目的样本。写作类内容默认为 True，机器验过的可以关掉。
    needs_review: bool = False
    # clarify 类样本**该追问哪几个参数**（架构 V1 里叫 ask_for）。
    #
    # 这个信息生成器一直是知道的（gen_scenarios.py 里那个 key 变量），
    # 但以前直接丢掉了 —— 于是「只询问缺失信息」「不得重复询问已有信息」
    # 「不得猜测缺失参数」这三条行为契约**一条都没法机器验证**，
    # 157 条 clarify（全库 14%）只被验证了"没有调用工具"。
    ask_for: list[str] = field(default_factory=list)

    def user_queries(self) -> list[str]:
        return [t.content or "" for t in self.turns if t.role == ROLE_USER]

    def called_tool_names(self) -> list[str]:
        return [c.name for t in self.turns for c in t.calls]


def compute_schema_version(schemas: list[dict[str, Any]]) -> str:
    """工具 schema 的内容指纹。

    每条样本都记录它是基于哪个版本生成的。后端改了 schema 之后，
    对不上的样本就必须重新生成 —— 否则训练数据和线上工具定义会悄悄脱节。
    """
    canonical = json.dumps(schemas, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def load_schemas(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    """读工具 schema，返回 (schemas, schema_version)。"""
    schemas = json.loads(Path(path).read_text(encoding="utf-8"))
    return schemas, compute_schema_version(schemas)


def schemas_by_name(schemas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {s["function"]["name"]: s for s in schemas}


def _turn_from_dict(d: dict[str, Any]) -> Turn:
    return Turn(
        role=d["role"],
        content=d.get("content"),
        calls=[ToolCall(**c) for c in d.get("calls", [])],
        results=[ToolResult(**r) for r in d.get("results", [])],
    )


def sample_from_dict(d: dict[str, Any]) -> Sample:
    return Sample(
        id=d["id"],
        template_id=d["template_id"],
        category=d["category"],
        schema_version=d["schema_version"],
        system=d["system"],
        tool_names=list(d["tool_names"]),
        turns=[_turn_from_dict(t) for t in d["turns"]],
        source=d.get("source", ""),
        topic=d.get("topic", ""),
        needs_review=bool(d.get("needs_review", False)),
        ask_for=list(d.get("ask_for", [])),
    )


def _turn_dict(t: Turn) -> dict[str, Any]:
    """Turn → dict。空的 content/calls/results 不落盘，让 IR 文件保持可读。

    ⚠️ 只剪**结构字段**，绝不递归进 ToolCall.arguments / ToolResult.content。

    以前这里是一个无差别递归的 `_prune`，凡是 None / [] / "" 的值一律剪掉 ——
    连工具返回值内部也剪。可那些正是线上真实存在的观测内容：
      calculator 失败时      result 就是 None
      recommend_practice 空结果时  recommendations 就是 []
      get_mastery_level 无记录时   mastery_level / retention 都是 None
    剪掉之后落盘的观测线上永远不会出现，模型学的是一个不存在的结构。
    """
    out: dict[str, Any] = {"role": t.role}
    if t.content:
        out["content"] = t.content
    if t.calls:
        out["calls"] = [{"name": c.name, "arguments": c.arguments} for c in t.calls]
    if t.results:
        out["results"] = [{"name": r.name, "content": r.content, "is_error": r.is_error}
                          for r in t.results]
    return out


def _sample_dict(s: Sample) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": s.id,
        "template_id": s.template_id,
        "category": s.category,
        "schema_version": s.schema_version,
        "system": s.system,
        "tool_names": list(s.tool_names),
        "turns": [_turn_dict(t) for t in s.turns],
    }
    if s.source:
        d["source"] = s.source
    if s.topic:
        d["topic"] = s.topic
    if s.needs_review:
        d["needs_review"] = True
    if s.ask_for:
        d["ask_for"] = list(s.ask_for)
    return d


def dump_samples(samples: list[Sample], path: str | Path) -> None:
    """写 IR jsonl，一行一个样本。

    collect 模式（`capture_system_prompts.py` 空跑生成器收集消息时）一律不落盘：
    那一轮里每条样本的 system 都是占位符，写出去就是一批看起来正常的坏数据。
    这里直接不写，而不是写完再指望后面有人发现。
    """
    if os.environ.get("ESA_SYSTEM_PROMPT_MODE") == "collect":
        print(f"[collect 模式] 跳过落盘 {Path(path).name}（{len(samples)} 条，system 是占位符）")
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for s in samples:
            fh.write(json.dumps(_sample_dict(s), ensure_ascii=False) + "\n")


def load_samples(path: str | Path) -> list[Sample]:
    out = []
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(sample_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_no} IR 解析失败: {exc}") from exc
    return out


def iter_ir_files(root: str | Path) -> Iterator[Path]:
    yield from sorted(Path(root).glob("*.jsonl"))
