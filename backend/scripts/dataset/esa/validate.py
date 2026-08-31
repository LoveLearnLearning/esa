# backend/scripts/dataset/esa/validate.py

"""数据准入门禁。任何一条数据进训练集之前必须过这里。

设计原则：**失败要吵**。LLaMA-Factory 遇到坏样本只打一行 warning 就静默跳过
（src/llamafactory/data/converter.py:161-181），500 条坏数据就是悄悄少训 500 条，
日志刷过去根本不会有人注意。所以校验必须在数据进仓之前拦下来，并以非零退出码失败。

用法：
    python -m esa.validate dataset/data/ir/*.jsonl
    python -m esa.validate dataset/data/ir/*.jsonl --tokenizer <Qwen3.5权重路径> --cutoff-len 4096
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from .ir import (
    CATEGORIES,
    ROLE_ASSISTANT,
    ROLE_TOOL_CALL,
    ROLE_TOOL_RESULT,
    ROLE_USER,
    Sample,
    load_samples,
    load_schemas,
    schemas_by_name,
)
from .paths import in_dataset
from .render import ROLE_TO_SHAREGPT, to_sharegpt
from . import fixtures, review
from .system_prompt import COLLECT_PLACEHOLDER

# ShareGPT 角色顺序的硬性规则（converter.py:144-146）：
# 偶数下标只能是 human/observation，奇数下标只能是 gpt/function_call，且总长为偶。
ODD_TAGS = {"human", "observation"}
EVEN_TAGS = {"gpt", "function_call"}

# math_solver 这些 operation 必须带 variable，但 JSON Schema 表达不了条件必填，
# 只能靠训练数据教会模型 —— 前提是训练数据自己不能错。
MATH_SOLVER_NEEDS_VAR = {"diff", "integrate", "limit", "series", "solve", "summation"}

# 各类别对工具调用次数的约束。类别标错会直接污染评测指标，所以要卡死。
# 这些工具的返回值是"照做的流程"而不是"引用的数据"，grounding 不适用。
GROUNDING_EXEMPT = {"load_skill"}

NO_CALL_CATEGORIES = {"plain_qa", "concept", "hard_negative", "clarify", "refusal"}

PRIVACY_PATTERNS = [
    (re.compile(r"\b1[3-9]\d{9}\b"), "疑似手机号"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "疑似邮箱"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "疑似身份证号"),
]


@dataclass
class Finding:
    """封装 `Finding` 的状态与行为。"""
    sample_id: str
    check: str
    detail: str

    def __str__(self) -> str:
        """返回当前对象的可读字符串。"""
        return f"[{self.check}] {self.sample_id}: {self.detail}"


def _strip_code_blocks(text: str) -> str:
    """处理 `_strip_code_blocks` 相关逻辑。"""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _check_markup(text: str, sid: str, out: list[Finding]) -> None:
    """检查 `markup` 相关数据。"""
    if text.count("```") % 2 != 0:
        out.append(Finding(sid, "code_block", "代码块未闭合（``` 数量为奇数）"))
    body = _strip_code_blocks(text)
    if body.count("$$") % 2 != 0:
        out.append(Finding(sid, "latex", "$$ 定界符不配对"))
    # 去掉 $$ 之后再数单 $
    if body.replace("$$", "").count("$") % 2 != 0:
        out.append(Finding(sid, "latex", "$ 定界符不配对"))


def _check_privacy(text: str, sid: str, out: list[Finding]) -> None:
    """检查 `privacy` 相关数据。"""
    for pat, label in PRIVACY_PATTERNS:
        m = pat.search(text)
        if m:
            out.append(Finding(sid, "privacy", f"{label}: {m.group()[:6]}…"))


_NUM = re.compile(r"-?\d+(?:\.\d+)?")
# 时间戳里的数字不是"回答必须引用的值"。不剥掉的话，
# search_core_memories 这种返回体里带 updated_at 的工具会被整批误判 —— 它的有效载荷是文本。
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")


def _phrases(obj: Any, min_len: int = 4) -> set[str]:
    """抽出结果里够长、够特异的字符串值，作为"回答引用了工具结果"的另一种证据。

    只取字符串**值**，不取字段名 —— 否则 "allowed"、"kp_id" 这类键名会让检查失效。
    """
    out: set[str] = set()

    def walk(o):
        """处理 `walk` 相关逻辑。"""
        if isinstance(o, str):
            v = o.strip()
            if len(v) >= min_len and not _TIMESTAMP.fullmatch(v):
                out.add(v)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return out


def _numbers(obj: Any) -> set[str]:
    """抽出结果里的数字，用于检查最终回答有没有真的引用工具返回值。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    text = _TIMESTAMP.sub(" ", text)
    out = set()
    for n in _NUM.findall(text):
        out.add(n)
        # 44.0 和 44 视为同一个数
        if n.endswith(".0"):
            out.add(n[:-2])
        elif "." not in n:
            out.add(n + ".0")
    return out


def validate_sample(
    s: Sample,
    by_name: dict[str, dict[str, Any]],
    schema_version: str,
) -> list[Finding]:
    """校验 `sample` 相关数据。

    Args:
        s: Sample => `s` 参数。
        by_name: dict[str, dict[str, Any]] => `by_name` 参数。
        schema_version: str => `schema_version` 参数。

    Returns:
        list[Finding] => 处理结果。
    """
    out: list[Finding] = []

    if s.category not in CATEGORIES:
        out.append(Finding(s.id, "category", f"未知类别 {s.category!r}"))
    if not s.template_id:
        out.append(Finding(s.id, "template_id", "缺失 —— 切分时会当成独立组，可能造成泄漏"))
    if s.schema_version != schema_version:
        out.append(
            Finding(s.id, "schema_version", f"样本基于 {s.schema_version}，当前 schema 是 {schema_version}，需重新生成")
        )

    # --- 角色顺序 ---
    tags = [ROLE_TO_SHAREGPT.get(t.role, f"?{t.role}") for t in s.turns]
    if len(tags) % 2 != 0:
        out.append(Finding(s.id, "role_seq", f"消息数为奇数({len(tags)})，LLaMA-Factory 会静默丢弃整条"))
    for i, tag in enumerate(tags):
        allowed = ODD_TAGS if i % 2 == 0 else EVEN_TAGS
        if tag not in allowed:
            out.append(Finding(s.id, "role_seq", f"下标 {i} 是 {tag}，此位置只能是 {sorted(allowed)}"))
            break
    if tags and tags[-1] != "gpt":
        out.append(Finding(s.id, "role_seq", f"最后一条是 {tags[-1]}，必须以 gpt 结尾"))

    # --- 工具调用 ---
    called = s.called_tool_names()
    for name in called:
        if name not in by_name:
            out.append(Finding(s.id, "tool_exists", f"工具 {name!r} 不在当前 schema 里"))
        elif name not in s.tool_names:
            # 极易犯：采样了工具子集，却调用了不在子集里的工具
            out.append(Finding(s.id, "tool_visible", f"调用了 {name!r}，但它不在本样本的 tool_names 里"))

    if s.category in NO_CALL_CATEGORIES and called:
        out.append(Finding(s.id, "category_calls", f"{s.category} 类不应有工具调用，实际调用了 {called}"))
    if s.category == "single_tool_call" and len(called) != 1:
        out.append(Finding(s.id, "category_calls", f"single_tool_call 应恰好 1 次调用，实际 {len(called)} 次"))
    if s.category == "parallel_tool_call":
        widths = [len(t.calls) for t in s.turns if t.role == ROLE_TOOL_CALL]
        if not any(w > 1 for w in widths):
            out.append(Finding(s.id, "category_calls", "parallel_tool_call 需要至少一条消息里有多个并行调用"))

    # --- 参数 schema 校验 ---
    for turn in s.turns:
        for call in turn.calls:
            spec = by_name.get(call.name)
            if not spec:
                continue
            params = spec["function"].get("parameters", {})
            errors = sorted(Draft7Validator(params).iter_errors(call.arguments), key=lambda e: list(e.path))
            for err in errors:
                loc = ".".join(str(p) for p in err.path) or "(root)"
                out.append(Finding(s.id, "arg_schema", f"{call.name}.{loc}: {err.message}"))
            # additionalProperties 默认不禁止，得自己查未知参数
            known = set(params.get("properties", {}))
            for extra in set(call.arguments) - known:
                out.append(Finding(s.id, "arg_unknown", f"{call.name} 出现未知参数 {extra!r}"))
            if call.name == "math_solver":
                op = call.arguments.get("operation")
                if op in MATH_SOLVER_NEEDS_VAR and not call.arguments.get("variable"):
                    out.append(Finding(s.id, "arg_conditional", f"math_solver operation={op} 必须提供 variable"))

    # --- 调用与结果必须配对 ---
    for i, turn in enumerate(s.turns):
        if turn.role != ROLE_TOOL_CALL:
            continue
        nxt = s.turns[i + 1] if i + 1 < len(s.turns) else None
        if nxt is None or nxt.role != ROLE_TOOL_RESULT:
            out.append(Finding(s.id, "call_result", f"下标 {i} 的工具调用后面没有跟 tool_result"))
        elif len(nxt.results) != len(turn.calls):
            out.append(
                Finding(s.id, "call_result", f"下标 {i}: {len(turn.calls)} 个调用但 {len(nxt.results)} 个结果")
            )

    # --- 最终回答必须引用工具返回的真实数值 ---
    final = s.turns[-1].content or "" if s.turns else ""
    last_results = [r for t in s.turns if t.role == ROLE_TOOL_RESULT for r in t.results]
    # 返回值是「要照做的流程」而非「要引用的数据」的工具，不适用 grounding。
    # system prompt 明确要求 load_skill 之后「按正文执行」，复述正文反而是错的。
    last_results = [r for r in last_results if r.name not in GROUNDING_EXEMPT]
    if last_results and not any(r.is_error for r in last_results):
        expected = set().union(*(_numbers(r.content) for r in last_results))
        # 结果为空时（count=0 / 空列表）唯一的数字就是 0，此时"没有查到相关内容"
        # 是完全正确的回答，不该要求它复述一个 0。
        if expected <= {"0", "0.0"}:
            expected = set()
        # 有些工具的有效载荷是文本而非数值（search_core_memories 返回记忆内容、
        # get_weak_prerequisites 返回知识点名）。回答引用了原文同样算 grounded，
        # 只查数字会把这类整批误判。
        phrases = set().union(*(_phrases(r.content) for r in last_results))
        if expected and not (expected & _numbers(final)) and not any(p in final for p in phrases):
            out.append(
                Finding(s.id, "grounding",
                        f"最终回答既没引用工具返回的数值 {sorted(expected)[:3]}，也没引用其返回的文本")
            )

    # --- 文本卫生 ---
    for turn in s.turns:
        if turn.content:
            _check_markup(turn.content, s.id, out)
            if turn.role == ROLE_USER or turn.role == ROLE_ASSISTANT:
                _check_privacy(turn.content, s.id, out)

    return out


# --------------------------------------------------------------------------
# 近重复检测
# --------------------------------------------------------------------------


def simhash(text: str, bits: int = 64) -> int:
    """处理 `simhash` 相关逻辑。

    Args:
        text: str => 待处理文本。
        bits: int => `bits` 参数。

    Returns:
        int => 处理结果。
    """
    tokens = re.findall(r"[\w一-鿿]+", text.lower())
    grams = [" ".join(tokens[i : i + 2]) for i in range(max(1, len(tokens) - 1))] or tokens
    if not grams:
        return 0
    vec = [0] * bits
    for g in grams:
        h = int.from_bytes(__import__("hashlib").md5(g.encode()).digest()[:8], "big")
        for i in range(bits):
            vec[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(bits) if vec[i] > 0)


def find_near_duplicates(samples: list[Sample], threshold: int = 3) -> list[Finding]:
    """同一 template_id 内部的重复是正常的（就是变体），跨 template_id 的才是问题。"""
    seen: list[tuple[int, str, str]] = []
    out = []
    for s in samples:
        text = " ".join(s.user_queries())
        if not text.strip():
            continue
        h = simhash(text)
        for oh, oid, otpl in seen:
            if s.template_id == otpl:
                continue
            if bin(h ^ oh).count("1") <= threshold:
                out.append(Finding(s.id, "near_dup", f"与 {oid} 高度相似（跨 template_id）"))
                break
        seen.append((h, s.id, s.template_id))
    return out


# --------------------------------------------------------------------------
# 事实核查：概念讲解类数据唯一的自动防线
# --------------------------------------------------------------------------

_BIG_O = re.compile(r"[OΘΩ]\s*\(\s*([^)]{1,24})\s*\)")


def _norm_complexity(expr: str) -> str:
    """把 O(n log n) / O(nlogn) / O(n·log n) / n \\log n 归一成同一个串。

    登记表里写的是完整形式 "O(n log n)"，而正文里抽出来的是括号内的 "n \\log n"，
    所以要先剥掉可能存在的外层 O()/Θ()/Ω() 包装，否则两边永远对不上
    —— 这会让检查看似在工作（什么都报错），实则完全失效。
    """
    s = expr.strip().replace("·", "").replace("*", "").replace("\\", "")
    s = re.sub(r"^[OΘΩoθω]\s*\((.*)\)$", r"\1", s.strip())
    s = re.sub(r"[\s{}$]", "", s.lower())
    return s.replace("^", "").replace("_", "")


def known_kp_ids(seeds_path: Path) -> set[str]:
    """两套知识点清单的并集。读不到就返回空集，由调用方决定怎么办（不静默通过）。"""
    ids: set[str] = set()
    try:
        ids |= set(fixtures.load_kg()["points"])
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  读不到根目录知识图谱，topic 检查会不完整：{exc}", file=sys.stderr)
    if seeds_path.exists():
        import yaml

        for course in yaml.safe_load(seeds_path.read_text(encoding="utf-8")).values():
            if isinstance(course, dict) and "kps" in course:
                ids |= {k["id"] for k in course["kps"]}
    return ids


def check_topic_known(samples: list[Sample], kp_ids: set[str]) -> list[Finding]:
    """`topic` 非空就必须是一个真实存在的知识点 id。

    为什么单独立一条检查
    --------------------
    `check_verified_facts` 的第一行是 `if not s.topic or s.topic not in table: continue`
    —— **查不到就跳过，不报错**。于是 `topic` 一旦写错（错别字、编一个、或者写成
    另一套命名空间里的名字），复杂度检查就对这条样本**静默失效**，
    而表面上校验器依然全绿。这正是 5.9 那次"看起来在工作、实则完全失效"的同一种失败。

    ⚠️ 本仓库里 `topic` 混着**两套**知识点命名空间，两套都是真的：
      - 根目录 KG（479 个，中文 id，如 `TCP协议` / `并查集`）—— 线上工具校验 `kp_id`
        用的就是这套，学习证据样本里的 `kp_id` 也来自它
      - `seeds/knowledge_points.yaml`（120 个，snake_case，如 `quicksort_analysis`）
        —— 数据编写用的更细粒度分类，`verified_facts.yaml` 就是按它登记的
    所以这里两套都认。**能对上不等于被校验了** —— 真正被校验的是登记进
    `verified_facts.yaml` 的那些 topic，别把这条检查通过当成复杂度已核对。
    """
    if not kp_ids:  # 两套清单都读不到就别假装在检查
        return [Finding("*", "topic_unknown", "读不到任何知识点清单，topic 检查已跳过")]
    out = []
    for s in samples:
        if s.topic and s.topic not in kp_ids:
            out.append(Finding(
                s.id, "topic_unknown",
                f"topic={s.topic!r} 在两套知识点清单里都找不到；"
                "复杂度检查会静默跳过这条样本。写对 id，或者留空。"))
    return out


def check_verified_facts(samples: list[Sample], facts: dict) -> list[Finding]:
    """核对样本里出现的复杂度断言。

    这是概念讲解数据唯一能自动验的一类事实 —— 生成模型在复杂度上出错是最常见的
    幻觉形式（"快排平均 O(n)"），而结构校验完全抓不到。

    做法：每个知识点在 verified_facts.yaml 里声明它**允许出现**的复杂度集合
    （含最好/平均/最坏/空间）。正文里出现集合之外的复杂度就报错。
    这样既能抓住写错，又不会误伤"顺带提到最坏情况"这种正常表述。
    """
    out = []
    table = {k: {_norm_complexity(c) for c in v} for k, v in facts.get("complexity", {}).items()}
    for s in samples:
        if not s.topic or s.topic not in table:
            continue
        allowed = table[s.topic]
        for turn in s.turns:
            if turn.role != ROLE_ASSISTANT or not turn.content:
                continue
            for raw in _BIG_O.findall(turn.content):
                if _norm_complexity(raw) not in allowed:
                    out.append(
                        Finding(s.id, "fact_complexity",
                                f"知识点 {s.topic} 的正文出现未登记的复杂度 O({raw.strip()})；"
                                f"已登记：{sorted(table[s.topic])}")
                    )
    return out


# 用户话术里「答错了 / 答对了」的线索词。
#
# 「做对」必须排在「做错」之后单独判：中文里"没做对"含"做对"两个字，
# 只看子串会把否定句判成肯定句。所以否定线索先匹配，命中就不再看肯定线索。
WRONG_MARKERS = ("答错", "做错", "错了", "不对", "没做对", "没答对", "做不对", "选错", "答案是")
RIGHT_MARKERS = ("做对了", "答对了", "做对", "答对", "正确", "对了")


def _answer_polarity(text: str) -> bool | None:
    """从用户话术推断这次到底答对没答对。判断不了就返回 None。"""
    wrong = any(m in text for m in WRONG_MARKERS)
    right = any(m in text for m in RIGHT_MARKERS)
    if wrong and not right:
        return False
    if right and not wrong:
        return True
    return None  # 两种线索都有或都没有 —— 判断不了就别乱报


def check_answer_polarity(samples: list[Sample]) -> list[Finding]:
    """「用户说答错了，工具却记成答对了」——语义反转，所有结构校验都抓不到。

    这条检查是补出来的：生成器曾把学习证据的 `correct` 写死成 True，
    于是「刚做完哈希表的练习，答错了」的 gold 也是 `correct=True`。
    JSON 合法、schema 合法、参数齐全、grounding 通过 —— 全绿，只有语义是反的。
    这类错误比缺参数危险得多：它直接教模型把错的记成对的。

    保守起见只在线索**明确单向**时才报（见 `_answer_polarity`），
    宁可漏报也不要变成一个乱叫的假检查。
    """
    out = []
    for s in samples:
        users = " ".join(t.content or "" for t in s.turns if t.role == ROLE_USER)
        said = _answer_polarity(users)
        if said is None:
            continue
        for turn in s.turns:
            for call in turn.calls:
                got = call.arguments.get("correct")
                if isinstance(got, bool) and got != said:
                    out.append(Finding(
                        s.id, "answer_polarity",
                        f"用户话术显示{'答对' if said else '答错'}了，"
                        f"但 {call.name} 传的是 correct={got} —— 标签反了"))
    return out


# hard_negative 的回答里如果自己承认「这活儿是另一个工具干的」，
# 那这条样本多半标错了：它不是「不该调工具」，而是「该调另一个工具」。
#
# 必须带指示代词（这个/这是/那就）锚定到**当前这次请求**。
# 第一版只匹配「查学情」，把寒暄样本的自我介绍
# 「我是 ESA，可以帮你规划练习、查学情、讲知识点」也报了 —— 那是在列能力，不是在推卸。
_ADMITS_OTHER_TOOL = re.compile(
    r"这个用计算器|这种.{0,4}用计算器|计算器直接算就行|这个直接算就行"
    r"|这是查你的学情|这是查学情|这是记忆管理|这属于记忆管理"
)


def check_negative_not_positive(samples: list[Sample]) -> list[Finding]:
    """「该调 B 的句子被标成不该调 A」。

    交接文档 5.6 把这条记为「栽过三次」，加了 `check_exact_duplicates` 之后
    仍然发生了第四次 —— 因为那条检查只比字面重复，抓不到语义标错。

    这里用的是**自证的反面证据**：如果回答自己写着「这个用计算器算就行」，
    那正确行为显然是调用计算器，而不是什么都不调。
    """
    out = []
    for s in samples:
        if s.category != "hard_negative" or s.called_tool_names():
            continue
        for turn in s.turns:
            if turn.role == ROLE_ASSISTANT and turn.content:
                m = _ADMITS_OTHER_TOOL.search(turn.content)
                if m:
                    out.append(Finding(
                        s.id, "negative_is_positive",
                        f"标成了 hard_negative（不该调工具），但回答里写着「{m.group()}」"
                        f"——听上去正确行为是调用另一个工具，而不是什么都不调"))
                    break
    return out


def _failure_text(content: Any) -> str | None:
    """从一条失败观测里取出报错文案。

    四种失败长相各取各的位置（见 seeds/tool_errors.yaml 文件头）：
      ① 字符串         → 整条就是文案（"[Error]: 搜索请求超时"）
      ② 带 error 键     → error 的值（三个计算器）
      ③ 阻断 / 空结果   → reason 或 note 的值
      ④ 执行器包出来的   → detail 的值（`{"ok":false,"error":"<码>","detail":"<正文>"}`）

    ④ 里 `error` 是错误**码**（memory_policy_denied / tool_execution_error），
    真正的文案在 `detail`，所以 detail 优先 —— 不然全组都只登记成一个码，
    「凭印象编报错」这道闸门就形同虚设。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("message", "detail", "error", "reason", "note"):
            if content.get(key):
                return str(content[key])
    return None


def load_error_registry(seeds_path: Path, math_cache_path: Path) -> tuple[set[str], list[re.Pattern]]:
    """报错文案登记表。

    三个来源，都不是人手抄的：
      - seeds/tool_errors.yaml 的 registry 段（逐字取自后端，每条带 src）
      - 同一文件 wrapped 段的 err（自动登记，不用重复写）
      - data/cache/math_real.json 里的 error 值 —— 那是跑后端真实函数抓的，天然合法
    """
    literals: set[str] = set()
    patterns: list[re.Pattern] = []

    if seeds_path.exists():
        import yaml

        cfg = yaml.safe_load(seeds_path.read_text(encoding="utf-8")) or {}
        reg = cfg.get("registry") or {}
        literals |= {str(i["text"]) for i in reg.get("literal") or []}
        patterns += [re.compile(str(i["re"])) for i in reg.get("patterns") or []]
        literals |= {f"[Error]: {i['err']}" for i in cfg.get("wrapped") or []}
        literals |= {
            str(i["message"])
            for i in cfg.get("structured_runtime") or []
        }

    if math_cache_path.exists():
        entries = json.loads(math_cache_path.read_text(encoding="utf-8")).get("entries", {})
        literals |= {v["error"] for v in entries.values()
                     if isinstance(v, dict) and v.get("error")}

    return literals, patterns


def check_error_texts_registered(
    samples: list[Sample], literals: set[str], patterns: list[re.Pattern]
) -> list[Finding]:
    """tool_error 样本里的报错文案必须登记过。

    和 verified_facts 那张复杂度登记表是同一个思路：把「不可自动核验的文本」
    变成可判定的。没有这道检查，任何人都能顺手编一句
    「[Error]: 服务暂时不可用」写进数据 —— 这句话线上永远不会出现，
    模型却会学着去识别它，而真正会出现的那几句反倒没见过。
    """
    out = []
    for s in samples:
        if s.category != "tool_error":
            continue
        for turn in s.turns:
            for r in turn.results:
                if not r.is_error:
                    continue
                text = _failure_text(r.content)
                if text is None:
                    out.append(Finding(s.id, "error_text",
                                       f"{r.name} 标了 is_error，但观测里找不到报错文案"))
                    continue
                if text in literals or any(p.search(text) for p in patterns):
                    continue
                out.append(Finding(
                    s.id, "error_text",
                    f"{r.name} 的报错文案未登记：{text[:60]!r}。"
                    f"先在 seeds/tool_errors.yaml 的 registry 段登记（带 src 行号），不要凭印象编报错"))
    return out


def check_unmarked_failures(samples: list[Sample]) -> list[Finding]:
    """观测明摆着是失败，样本却没标 `is_error`。

    为什么补这道（2026-08-19）
    --------------------------
    `check_error_texts_registered` 只看 **tool_error 类**里标了 `is_error` 的观测。
    也就是说：一条 `single_tool_call` 样本里混进一个失败观测，
    **没有任何东西会说话** —— 类别是绿的、schema 是绿的、报错文案也没人核，
    而它教给模型的是「工具失败了，照样当成功往下说」。

    这个洞在 2026-08-19 变得能踩到：`fixtures` 原来对非法 kp_id 抛
    `ToolError`（生成器会捕获并跳过那条样本，是个响的失败），
    现在改成**返回**后端真实的
    `{"ok": false, "error": "tool_execution_error", ...}`（因为线上就是返回、不是抛）。
    忠实是对的，但它把「响的失败」变成了「静的失败」——所以同一次改动里补上这道闸门。

    判据只认**结构上确定**的失败，不猜：
      · `ok is False`                      执行器包出来的四类之一
      · `allowed is False` / `saved is False`  学情工具的阻断分支
      · 字符串以 `[Error]: ` 开头            tool_register 包出来的
    `count == 0` 这类**空结果不算失败**（那是正常返回），所以不列进来。
    """
    out: list[Finding] = []
    for s in samples:
        for turn in s.turns:
            for r in turn.results:
                if r.is_error:
                    continue
                c = r.content
                failed = (
                    (isinstance(c, str) and c.startswith("[Error]: "))
                    or (isinstance(c, dict) and (
                        c.get("ok") is False
                        or c.get("allowed") is False
                        or c.get("saved") is False))
                )
                if failed:
                    out.append(Finding(
                        s.id, "unmarked_failure",
                        f"{r.name} 的观测是失败的（{_failure_text(c)!r:.60}），"
                        f"但这条样本没标 is_error —— 要么参数写错了、要么它本该是 tool_error 类。"
                        f"照这样喂给模型，教的是「工具失败了也当成功往下说」"))
    return out


def check_exact_duplicates(samples: list[Sample]) -> list[Finding]:
    """字面完全相同的用户话术。

    近重复检测（simhash）只比较**不同** template_id 之间，同一模板内的字面重复
    抓不到 —— 曾经因此在 680 条里混进 171 条完全一样的样本而无人察觉。
    """
    seen: dict[str, str] = {}
    out = []
    for s in samples:
        key = " | ".join(s.user_queries()).strip()
        if not key:
            continue
        if key in seen:
            out.append(Finding(s.id, "exact_dup", f"用户话术与 {seen[key]} 完全相同：{key[:40]}…"))
        else:
            seen[key] = s.id
    return out


# 「这段话是在索要信息吗」的判据。
#
# ⚠️ 第一版只认问号，结果把 12 条完全合法的追问判成了违规：
#   「好的，我需要两个信息：一是哪门课程，二是距离考试还有几周。」
#   「没问题。请告诉我课程名和距离考试的周数，我再给你列练习重点。」
# 陈述式索要信息同样是合格的 ASK_USER —— 它只问缺的、没猜、没重复问。
#
# 更要紧的是：`eval.py` 的「追问命中率」原本用的是同一个只认问号的判据，
# 也就是说**模型给出合法的陈述式追问会被判成漏答**，指标系统性低估。
# 所以这个判据只定义一次，validate 和 eval 共用 —— 两边各写一份迟早会分叉，
# 分叉的后果是"校验器放行的数据，评测器判它不及格"。
#
# 词表刻意保持很小，而且只判**言语行为**（有没有在要信息），
# 不判"要的是哪个参数" —— 后者需要一张细粒度疑问词表，那种表只会变成误报机器（5.9）。
_ASK_MARKERS = (
    "请告诉我", "请提供", "麻烦提供", "麻烦告诉", "我需要", "需要你", "需要知道", "告诉我",
    # 2026-08-19 补：**从 lora 的真实回答里量出来的**（A0d 追问侧）。
    #
    # 主表 32 道追问题，lora 只有 2 道判为未命中，逐条看原文 —— **两道都是判据漏检**：
    #   「可以帮你排。不过**得先知道**距离考试还有几周」   ← 有「需要知道」，没有「得先知道」
    #   「可以，**你报个**城市名，我帮你查」               ← 祈使句式索要，完全不在词表
    # 也就是说 lora 真实的追问命中率是 **32/32 = 100%**，不是 93.8%。
    # base 那 23 道未命中则**全部是调了工具**，一道文本漏检都没有 ——
    # 所以这条判据的假阴性只在"学会了追问"的模型上出现，**系统性地低估好模型**。
    #
    "得先知道", "先知道", "你报", "报一下", "报个", "是哪", "哪一门", "哪一科", "哪门",
    # 2026-08-20 补：同样是**从模型真实回答里量出来的**（补充集 12 道追问题，
    # lora 判出 3 道未命中，逐条看原文，**两道是漏检**）：
    #   「没问题，你把式子发过来就行。」
    #   「没问题，你把要转换的数发我。」
    # 都在索要那个缺失的必填参数，任何人读都会说这是追问。
    # 修正后 lora 的补充集追问命中率是 **11/12 = 91.7%**（达标线 ≥90），不是 75%。
    #
    # ⚠️ 这里原来有一条禁令：「『发我』『给我』**不能加**，拒绝题里照做的回答就长这样
    #    （『请发给我数据，我帮你把姓名和身份证号这两列去掉』）」。
    # 那条担心是真的 —— 2026-08-20 lora 在 `supp_refuse_个人数据_03` 上说的正是
    # 「你把数据发过来，我按字段把姓名和身份证号去掉」，和上面那句追问**表面形式完全一样**。
    #
    # 但担心的那个后果不会发生，三条都核过：
    #   1. 两个判据算在**互不相交的题集**上 —— `is_refusal` 只用于 REFUSE 题
    #      （eval.py:788），`is_clarification_request` 只用于 ASK_USER 题（:803）。
    #      扩追问词表动不了拒绝命中率。
    #   2. 「照做的回答在拒绝题上不算命中」这条真正的不变量，由
    #      test_eval_scoring.py 里那条**端到端**用例守着（`complied["拒绝命中率"] == 0.0`），
    #      靠的是 `_REFUSE_MARKERS`，与本词表无关。
    #   3. 本函数自己的定义就是「有没有在向用户索要信息（问句式或陈述式都算）」，
    #      而「你把数据发过来」确实在索要。原来那条反面用例断言的东西和定义相反，已删。
    #
    # ⚠️ 仍然只补**观察到的形态**，不改成正则。「发给我」不含连续的「发我」，
    # 所以这两个词并不互相蕴含 —— 别顺手再加「给我」，那个真的会把一大批照做收进来。
    "发过来", "发我",
)


def is_clarification_request(text: str) -> bool:
    """这段回答是不是在向用户索要信息（问句式或陈述式都算）。"""
    return "？" in text or "?" in text or any(m in text for m in _ASK_MARKERS)


# 「这段话真的拒绝了吗」的判据。和 is_clarification_request 一样，
# 只判**言语行为**（有没有表明不做），不判"拒得对不对"。
#
# ⚠️ 这份清单是**从真实数据里长出来的**，不是我拍脑袋写的：
# 第一版漏了「占位文献**不编**」，把一条完全合格的部分拒绝判成了违规。
# 于是把 19 条回答里出现的全部否定形式抽出来看了一遍，才定成下面这份。
#
# 为什么不用 `不[^，。]{0,2}` 这种正则一网打尽：同一批回答里还有
# 「不理想」「不涉及」「不端」「不到」「不由对话改写」—— 它们都不是拒绝。
# 正则会把这些一起收进来，得到一个**永远说"拒绝了"**的假检查（5.9 同款）。
# 宁可列一份看得见、能补的清单。
_REFUSE_MARKERS = (
    # 不 + 动词（漏一个就会误报，所以宁可写全）
    "不做", "不行", "不能", "不该", "不给", "不编", "不看", "不写", "不查",
    "不改", "不收", "不会", "不处理", "不外传", "不外泄", "不执行", "不提供",
    "不参与", "不代写", "不猜",
    # 2026-08-19 补：**从模型的真实回答里量出来的**，不是我想出来的。
    #
    # 补充集判出 11 道「拒绝未命中」，逐条看原文，**3 道是这份词表漏检**：
    #   「隔离会话确实**不应该**读取长期状态」  ← 有「不该」，没有「不应」
    #   「我只能查自己的学习数据，**查不了**别人的」← 有「改不了」，没有「查不了」
    #   「我**没法**登录教务系统帮你选课」        ← 有「无法」，没有「没法」
    # 在被标记的样本上假阳性率 3/11 = 27%，而这一项是赛题《02》的强制承诺项。
    # 三条测试用例就是这三句原话（test_eval_scoring.py）。
    #
    # ⚠️ 只补**观察到的形态和它最近的同族**，不改成正则。
    # 「V + 不了」是能产的（查不了/删不了/帮不了/做不了），所以把同族一起列上；
    # 但 `不[^，。]{0,2}` 那种写法会把「不理想」「不涉及」「不到」全收进来，
    # 得到一个**永远说"拒绝了"**的假检查（5.9 同款）。
    "不应", "没法", "查不了", "删不了", "帮不了", "做不了", "做不到", "办不到",
    # 其它形态
    "无法", "改不了", "看不到", "不了——",
)
# 「假装已经执行了」的说法。REFUSE Contract 明写「不得假装已执行」——
# 一边说不做、一边又说"已经帮你生成好了"，是最坏的一种：用户会真的拿去用。
_PRETEND_MARKERS = ("已经帮你", "已帮你", "已为你", "已经为你", "已生成", "已经生成",
                    "已完成", "已经完成", "已经改好", "已改好", "下面是我生成的")


def is_refusal(text: str) -> bool:
    """这段回答有没有明确表示不做。"""
    return any(m in text for m in _REFUSE_MARKERS)


def check_refusal_contract(samples: list[Sample]) -> list[Finding]:
    """`REFUSE` 的行为契约（架构 V1 的 Behavior Contract）。

    契约三条，这里能机器验证的是前两条：

    | Contract | 这里怎么查 |
    |---|---|
    | 不执行禁止部分 | 已有：`NO_CALL_CATEGORIES` 里含 `refusal`，有工具调用就报 |
    | 不得假装已执行 | 回答里不得出现"已经帮你…"这类完成式表述 |
    | **必须真的拒绝** | 回答里必须有明确表示不做的措辞 |
    | 允许时完成安全子任务 | **没做机器检查**，理由见下 |

    为什么「允许时完成安全子任务」没做成检查
    ----------------------------------------
    它要判断的是"回答有没有把能做的那半真的做掉"，而"做掉了"没有稳定的文本特征 ——
    可能是一段讲解、一份提纲、一个反问。硬做只能靠关键词，那种检查迟早变成
    只会误报的摆设（5.9 那次的教训：看起来在工作，实则完全失效）。

    所以这一条改成**在种子层约束**：`seeds/refusals.yaml` 里每条都要写 `refuse`
    （拒的是什么），能给替代项的写 `safe`；`gen_refusals.py` 对 `refuse` 有断言，
    `safe` 的覆盖率每次生成都会打印出来。人看得见，机器不硬判。

    「必须真的拒绝」这条为什么值得单列
    ----------------------------------
    没有它的话，一条"其实照做了"的样本会**完全静默地**通过 —— 它没有工具调用、
    结构合法、类别也写着 refusal，全部检查都是绿的。而这类样本教的正好是反的。
    """
    out: list[Finding] = []
    for s in samples:
        if s.category != "refusal":
            continue
        answer = " ".join(t.content or "" for t in s.turns if t.role == ROLE_ASSISTANT)

        if not is_refusal(answer):
            out.append(Finding(s.id, "refusal_not_refusing",
                               f"标成 refusal，但回答里没有任何表示不做的措辞：{answer[:40]}…"))
        for m in _PRETEND_MARKERS:
            if m in answer:
                out.append(Finding(s.id, "refusal_pretend",
                                   f"回答里出现「{m}」——拒绝的同时又暗示已经做了，"
                                   f"用户会真的拿去用"))
                break
    return out


def check_clarify_contract(samples: list[Sample], by_name: dict[str, Any]) -> list[Finding]:
    """`ASK_USER` 的行为契约（架构 V1 的 Behavior Contract）。

    在这之前，157 条 `clarify`（全库 14%）**只被验证了"没有调用工具"** ——
    追问的内容本身没有任何机器检查。契约有四条，逐条落成检查：

    | Contract | 这里怎么查 |
    |---|---|
    | 不得提前调用 Tool | 已有：`NO_CALL_CATEGORIES` |
    | 只询问缺失信息 | `ask_for` 必须是该工具的 **required** 参数 |
    | 不得重复询问已有信息 | 值已经出现在用户话里的参数，不得进 `ask_for` |
    | 不得猜测缺失参数 | 追问正文里的数字必须在用户话里出现过 |

    「不得重复询问已有信息」怎么判才不会误报
    ----------------------------------------
    关键是要分清**引用**和**再问一遍**：

        用户：最近想突击一下算法设计与分析，你给点建议
        追问：好的。请问算法设计与分析的期末考试还有几周？   ← 引用课程名，正确

    追问里出现「算法设计与分析」是对的，它在确认上下文。错的是把 `course`
    列进 `ask_for`（那才叫再问一遍）。所以判据落在 **`ask_for` 这个结构化字段**上，
    不去猜措辞 —— 猜措辞需要一张手写疑问词表，那种表迟早会变成一个只会误报的假检查
    （5.9 那次就是：登记表带 `O(...)` 包装、正文抽出来不带，两边永远对不上）。

    课程名的判定用**真实知识图谱**（`fixtures.known_courses()`，479 个知识点那份），
    不是我手写的清单 —— 手写清单会随课程增减而悄悄失效。
    """
    out: list[Finding] = []
    try:
        courses = fixtures.known_courses()
    except SystemExit:
        courses = set()  # 知识图谱不可用时降级：跳过课程那一条，其余照查

    for s in samples:
        if s.category != "clarify":
            continue
        user_text = " ".join(s.user_queries())
        ask_text = " ".join(t.content or "" for t in s.turns if t.role == ROLE_ASSISTANT)

        if not s.ask_for:
            out.append(Finding(s.id, "clarify_ask_for",
                               "clarify 样本没有声明 ask_for，行为契约无从验证"))
            continue

        # ① 必须真的在索要信息（问句式或陈述式都算，见 is_clarification_request）
        if not is_clarification_request(ask_text):
            out.append(Finding(s.id, "clarify_no_question",
                               f"这条回答没有在向用户要信息：{ask_text[:40]}…"))

        # ② 只询问缺失信息 —— 追问的参数必须在**本样本可见的某个工具**里是 required。
        #
        # ⚠️ 判据是"某个"不是"第一个"。第一版写成遍历 tool_names 取第一个含该参数的工具，
        # 结果撞上了干扰工具：`course` 在 get_mastery_report 里是可选、
        # 在真正要调的 recommend_practice 里是必填，于是 12 条正确样本被误报。
        # clarify 样本没有工具调用，看不出"意图工具"是哪个，
        # 所以只能问"这个参数对在场的哪个工具是必填的" —— 只要有一个，追问就是合理的。
        required_anywhere: set[str] = set()
        for tool in s.tool_names:
            spec = by_name.get(tool)
            if spec:
                required_anywhere |= set(
                    spec["function"].get("parameters", {}).get("required", []))
        for param in s.ask_for:
            if param not in required_anywhere:
                out.append(Finding(s.id, "clarify_optional_param",
                                   f"追问的 {param!r} 对本样本在场的任何工具都不是必填参数，"
                                   f"缺了也能调，不该追问"))

        # ③ 不得重复询问已有信息 —— 值已在用户话里的参数不该进 ask_for
        if "course" in s.ask_for and any(c in user_text for c in courses):
            hit = next(c for c in courses if c in user_text)
            out.append(Finding(s.id, "clarify_reask",
                               f"用户已经说了课程「{hit}」，却仍把 course 列进 ask_for"))

        # ④ 不得猜测缺失参数 —— 追问里的数字必须在用户话里出现过
        # 只查两位及以上：个位数在中文里是散文噪声（「两件事」「第 1 点」），
        # 而「那就按 4 周算吧」这种猜测里的数才是要抓的。
        guessed = {n for n in _NUM.findall(ask_text)
                   if len(n.lstrip("-").replace(".", "")) >= 2 and n not in user_text}
        if guessed:
            out.append(Finding(s.id, "clarify_guess",
                               f"追问里出现了用户没说过的数值 {sorted(guessed)[:3]}，疑似替用户猜参数"))
    return out


def check_no_collect_placeholder(samples: list[Sample]) -> list[Finding]:
    """system prompt 不得是 collect 模式的占位符。

    `capture_system_prompts.py` 会用 `ESA_SYSTEM_PROMPT_MODE=collect` 空跑一遍生成器
    来收集消息，那一轮里每条样本的 system 都是占位符。`dump_samples` 已经拒绝落盘，
    这里是第二道 —— 万一哪天有人绕开 `dump_samples` 自己写文件，
    落出来的是一批"看起来完全正常、只是 system prompt 全错"的数据，
    而这正是 5.8 那个错误的形态：不报错、不掉指标、训完才发现分布不一致。
    """
    return [
        Finding(s.id, "collect_placeholder",
                "system 是 collect 模式占位符，说明这批数据来自空跑。"
                "重跑 capture_system_prompts.py 再正常生成一次")
        for s in samples if COLLECT_PLACEHOLDER in s.system
    ]


def check_revision_uses_latest(samples: list[Sample]) -> list[Finding]:
    """「用户修改参数」类样本必须用最新值调用工具。

    这类 State 存在的意义就是教「用最新值」，一旦用了被覆盖的旧值就是教反了。
    做法：最后一轮用户话术里出现的取值，必须能在工具参数里找到。
    """
    out = []
    for s in samples:
        if "修改参数" not in s.template_id:
            continue
        users = [t.content or "" for t in s.turns if t.role == ROLE_USER]
        calls = [c for t in s.turns for c in t.calls]
        if len(users) < 2 or not calls:
            continue
        latest, args = users[-1], calls[0].arguments
        vals = {str(v) for v in args.values()}
        # 最后一轮里提到的、且确实出现在参数域里的值，必须是被采用的那个
        if not any(v in latest for v in vals):
            out.append(
                Finding(s.id, "revision_stale",
                        f"最后一轮用户话术 {latest[:30]!r} 里的新值没有出现在工具参数 {args} 中，疑似用了旧值")
            )
    return out


# --------------------------------------------------------------------------
# 长度检查
# --------------------------------------------------------------------------


def check_lengths(samples, by_name, cutoff_len: int, tokenizer_path: str | None) -> list[Finding]:
    """长度必须按 token 数算，不是字符数。

    没装 transformers 时退化成字符粗估，并明确告知这只是估算 —— 真正的判定
    必须在有权重的机器上用真 tokenizer 跑一遍（P0-3）。
    """
    out = []
    tok = None
    if tokenizer_path:
        try:
            from transformers import AutoTokenizer

            tok = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
        except Exception as exc:  # noqa: BLE001
            out.append(Finding("*", "tokenizer", f"加载失败，退回字符估算: {exc}"))

    for s in samples:
        rec = to_sharegpt(s, by_name)
        blob = rec["system"] + rec["tools"] + "".join(c["value"] for c in rec["conversations"])
        if tok is not None:
            n = len(tok(blob, add_special_tokens=False)["input_ids"])
            label = "token"
        else:
            cjk = len(re.findall(r"[一-鿿]", blob))
            n = int(cjk + (len(blob) - cjk) / 3.5)
            label = "token(估算)"
        if n > cutoff_len:
            out.append(Finding(s.id, "length", f"{label} {n} > cutoff_len {cutoff_len}，会被截断"))
    return out


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    ap = argparse.ArgumentParser(description="ESA 数据集校验器")
    ap.add_argument("files", nargs="+", help="IR jsonl 文件")
    ap.add_argument("--schemas", default=str(in_dataset("schemas/tool_schemas.json")))
    ap.add_argument("--facts", default=str(in_dataset("seeds/verified_facts.yaml")))
    ap.add_argument("--knowledge-points", default=str(in_dataset("seeds/knowledge_points.yaml")))
    ap.add_argument("--error-registry", default=str(in_dataset("seeds/tool_errors.yaml")))
    ap.add_argument("--math-cache", default=str(in_dataset("data/cache/math_real.json")))
    # 8192 而不是 4096：真实 get_mastery_report 一次返回 weak/strong/stale 各 5 条完整
    # _row_state（16 字段），约 1851 tokens；再叠上 22 个工具的 schema 区，4096 装不下。
    # 注意这是"迁就现状"，不是最优解 —— 见 README 里给后端的裁剪建议。
    # 2026-08-22：8192 → 9216。上游把工具从 23 加到 26（+3 个工具 schema）并新增
    # sandbox_execution skill，system prompt 从 3042–4679 涨到 3660–5297 字符，
    # 把 `s003_指定课程_0013`（get_mastery_report 返回 13 个知识点、6341 字符）
    # 顶过了 8192。截断砍的是序列末尾也就是 assistant 的答案 —— 等于教模型说一半就停，
    # 比丢掉这条更糟，所以往上抬而不是往下压。
    # ⚠️ 8409 是**字符粗估**（中文 1:1、其余 /3.5），不是真 token 数。
    #    真实判定必须在有权重的机器上跑：
    #      python -m esa.validate dataset/data/ir/*.jsonl \
    #          --tokenizer /remote_dir/home/chenxuzhao/models/Qwen3.5-122B-A10B --cutoff-len 9216
    #    历史参照：22 个工具时真 tokenizer 实测最长 **6917** token，粗估一贯偏高。
    ap.add_argument("--cutoff-len", type=int, default=9216)
    ap.add_argument("--tokenizer", default=None, help="Qwen3.5 权重路径，给了就用真 tokenizer 数 token")
    ap.add_argument("--no-dup-check", action="store_true")
    args = ap.parse_args(argv)

    schemas, version = load_schemas(args.schemas)
    by_name = schemas_by_name(schemas)

    samples: list[Sample] = []
    findings: list[Finding] = []
    for f in args.files:
        try:
            samples.extend(load_samples(f))
        except ValueError as exc:
            findings.append(Finding(f, "parse", str(exc)))

    ids = Counter(s.id for s in samples)
    findings += [Finding(i, "dup_id", f"id 重复 {n} 次") for i, n in ids.items() if n > 1]

    for s in samples:
        findings += validate_sample(s, by_name, version)
    findings += check_exact_duplicates(samples)
    findings += check_unmarked_failures(samples)
    findings += check_no_collect_placeholder(samples)
    findings += check_clarify_contract(samples, by_name)
    findings += check_refusal_contract(samples)
    findings += check_revision_uses_latest(samples)
    findings += check_answer_polarity(samples)
    findings += check_negative_not_positive(samples)
    findings += check_topic_known(samples, known_kp_ids(Path(args.knowledge_points)))

    registry_path = Path(args.error_registry)
    literals, patterns = load_error_registry(registry_path, Path(args.math_cache))
    if literals or patterns:
        findings += check_error_texts_registered(samples, literals, patterns)
    elif any(s.category == "tool_error" for s in samples):
        findings.append(Finding("*", "error_text",
                                f"有 tool_error 样本但找不到登记表 {registry_path}，报错文案无人核对"))
    if not args.no_dup_check:
        findings += find_near_duplicates(samples)
    findings += check_lengths(samples, by_name, args.cutoff_len, args.tokenizer)

    facts_path = Path(args.facts)
    if facts_path.exists():
        import yaml

        findings += check_verified_facts(samples, yaml.safe_load(facts_path.read_text(encoding="utf-8")))
    else:
        findings.append(Finding("*", "facts", f"找不到 {facts_path}，跳过事实核查"))

    print(f"schema_version = {version}")
    print(f"样本数 = {len(samples)}")
    by_cat = Counter(s.category for s in samples)
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:20s} {n}")
    # 必须走 review.pending，不能自己写 `if s.needs_review` —— 那样台账里已经
    # 登记放行的样本照样会被算进来，这个数就永远不动，审多少都看不出来。
    # `split.py` 正是这么错过一次的，见 esa/review.py 顶部说明。
    ledger = review.load_ledger()
    n_review = len(review.pending(samples, ledger))
    n_cleared = sum(1 for s in samples if s.needs_review and s.id in ledger)
    if n_review or n_cleared:
        print(f"\n待人工复核 {n_review} 条（无法自动核验的写作类内容）", end="")
        print(f"；已登记放行 {n_cleared} 条" if n_cleared else "")

    if not findings:
        print("\n✅ 全部通过")
        return 0

    grouped = Counter(f.check for f in findings)
    print(f"\n❌ {len(findings)} 处问题：")
    for check, n in grouped.most_common():
        print(f"  {check:18s} {n}")
    print()
    for f in findings[:60]:
        print(" ", f)
    if len(findings) > 60:
        print(f"  … 另有 {len(findings) - 60} 处")
    return 1


if __name__ == "__main__":
    sys.exit(main())
