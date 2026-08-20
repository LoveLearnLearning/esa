# backend/scripts/dataset/esa/system_prompt.py

"""线上 system prompt —— **不复刻，查缓存**。

为什么这个文件不再有一行提示词正文
----------------------------------
它以前是一份手写复刻：把后端的 `SYSTEM_PROMPT`、`MATH_PRMOPT`、风格规则、Skill 索引
抄一遍再拼起来。2026-08-11 后端一改（删 MATH_PRMOPT、加确定性路由、Skill 9→11、
首句改成「辅助计算机专业学生」），这份复刻从 1,308 字符一夜之间对不上 3,145 字符的线上值，
**而且不会有任何报错** —— 所有校验照样是绿的。

这是同一个错误的第四次重演（交接文档 5.1 / 5.8 / 5.10 / 5.12）：
凭"看起来合理"断定线上长什么样，全部逃过校验。规矩是第五节第 4 条：
**凡是"线上长什么样"的问题，能跑就别想。**

所以现在的分工是：

    dataset/tools/capture_system_prompts.py   import 后端、跑生产 WorkspaceRuntime
              ↓  产出
    dataset/data/cache/system_prompts.json    {prompts, index, routes}
              ↓  查表
    这个文件                                   只做查表，查不到就抛错

**查不到一律抛错，绝不回退到手写版。** 回退等于把"数据和线上脱节"这件事重新变成静默失败。

缓存长什么样
------------
    {
      "_meta":   {...来源、后端 commit、渲染参数...},
      "prompts": {内容哈希: 提示词正文},
      "index":   {'["消息","风格","语调"]': 内容哈希},
      "routes":  {消息: {"skill_name": ..., "task_type": ..., "confidence": ...}}
    }

`index` 的键是 JSON 数组而不是 `消息|风格|语调` —— 消息里出现 `|` 时后者会撞键。

`routes` 单独存一份是因为**路由结果本身就是数据**：后端命中路由时会把 Skill 正文直接
注入 system prompt 并写明「无需再调用 load_skill」。生成器要据此判断某条样本该不该
再教模型调 `load_skill`（`gen_skills_rag.py` 用的就是它），否则样本会和自己的
system prompt 直接打架。

⚠️ 实测 `primary_kp_id` 恒为 `None`（我们不传 profile/history），所以提示词只随
「路由结果 + 风格 + 语调」变化。哪天开始传 profile 或 history，缓存键要跟着加维度 ——
`capture_system_prompts.py` 里有对应的断言会先炸给你看。

collect 模式
------------
生成器要什么消息，只有生成器自己知道。所以 `capture_system_prompts.py` 会先用
`ESA_SYSTEM_PROMPT_MODE=collect` 把七个生成器空跑一遍，把需要的键收齐，再去后端渲染。
collect 模式下本文件返回占位符、`ir.dump_samples` 拒绝落盘 —— 不会产出半成品数据。
"""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path

from .cache_contract import prompt_source_fingerprint, skill_source_hashes

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "dataset/data/cache/system_prompts.json"
# ⚠️ 上游原本写的是 `REPO_ROOT = ROOT.parents[1]`，那只在
# `<repo>/backend/scripts/dataset/` 这一种布局下成立；在独立工作副本
# （`~/Desktop/项目/dataset/`）下会算出 `/Users/apple`，闸门直接抛
# `FileNotFoundError`。改用 `paths.backend_repo()`，三种布局都认，
# 找不到就返回 None（发布出去的独立仓库里本来就没有后端源码）。
from .paths import backend_repo  # noqa: E402


def _source_check(kind: str, expected, compute):
    """比对缓存里记的源码指纹与当前后端源码。

    三种结果，**区别对待**：
      指纹一致        → 放行
      指纹不一致      → 抛 SystemPromptCacheMiss（缓存过期了，必须重抓）
      找不到后端源码  → **如实报「无法校验」并放行**

    第三种是关键：发布出去的独立仓库里没有 `backend/`，那不是错误。
    硬失败会让发布产物一跑就炸；静默放行又等于闸门不存在。
    所以打一行警告 —— 一个说不出话的检查，至少要说自己说不出话。
    """
    repo = backend_repo()
    if repo is None:
        if not _source_check.warned:
            print(f"⚠️  找不到后端源码，跳过{kind}缓存的过期校验。"
                  "（设 $ESA_BACKEND 指向后端 clone 可启用）")
            _source_check.warned = True
        return
    if not expected or expected != compute(repo):
        raise SystemPromptCacheMiss(
            f"{kind}缓存对应的生产源码已经变化。跑：\n"
            f"  python3 dataset/tools/capture_{'system_prompts' if kind == 'system prompt' else 'skill_bodies'}.py\n"
            "不要继续使用旧缓存。"
        )


_source_check.warned = False

# 渲染时固定住的参数。它们进缓存的 _meta，改了就得重抓。
USER_NAME = "同学"
DEFAULT_STYLE = "concise"
DEFAULT_TONE = "friendly"

MODE_ENV = "ESA_SYSTEM_PROMPT_MODE"
COLLECT_OUT_ENV = "ESA_SYSTEM_PROMPT_COLLECT_OUT"
COLLECT_MODE = "collect"

# collect 模式下返回的占位符。它绝不该出现在任何落盘数据里，
# 所以 validate.py 有一条检查专门拦它（check_no_collect_placeholder）。
COLLECT_PLACEHOLDER = "<<ESA_COLLECT_MODE_PLACEHOLDER__NOT_A_REAL_SYSTEM_PROMPT>>"

_collected: set[tuple[str, str, str]] = set()
_cache: dict | None = None


class SystemPromptCacheMiss(KeyError):
    """缓存里没有这条消息的提示词。

    这不是可以吞掉的错误：吞掉就意味着某条样本的 system prompt 和线上对不上，
    而这正是 5.8 那个错误的形态。
    """


def _is_collect() -> bool:
    """判断 `collect` 相关数据。"""
    return os.environ.get(MODE_ENV) == COLLECT_MODE


def index_key(message: str, style: str, tone: str) -> str:
    """建立索引 `key` 相关数据。

    Args:
        message: str => `message` 参数。
        style: str => `style` 参数。
        tone: str => `tone` 参数。

    Returns:
        str => 处理结果。
    """
    return json.dumps([message, style, tone], ensure_ascii=False, sort_keys=True)


def load_cache() -> dict:
    """加载 `cache` 相关数据。"""
    global _cache
    if _cache is None:
        if not CACHE.exists():
            raise SystemPromptCacheMiss(
                f"找不到 {CACHE.relative_to(ROOT)}。\n"
                "先跑：python3 dataset/tools/capture_system_prompts.py"
            )
        payload = json.loads(CACHE.read_text(encoding="utf-8"))
        _source_check("system prompt",
                      payload.get("_meta", {}).get("prompt_source_fingerprint"),
                      prompt_source_fingerprint)
        _cache = payload
    return _cache


def build_system_prompt(
    message: str,
    *,
    style: str = DEFAULT_STYLE,
    tone: str = DEFAULT_TONE,
) -> str:
    """取这条**首条用户消息**在线上对应的 system prompt。

    为什么参数是消息不是别的：后端每轮都用当前消息跑一次确定性路由，
    路由结果直接决定提示词内容（`backend/agent/agent.py:150-174`）。
    没有消息就算不出提示词。

    ⚠️ 多轮样本只有一个 system prompt，这里取的是**首轮**的路由结果；
    线上是每轮重算的（`agent.py:150` 每次 run 都跑一遍 route）。

    实测差异（2026-08-11，全库 1,117 条）：
      单轮样本 1,017 条 —— 不受影响，只有一轮，提示词本来就是对的
      多轮样本   100 条 —— 首轮与末轮路由相同 86 条、不同 14 条
      → 受影响 14/1117 = **1.3%**，且全部是"首轮命中 Skill、末轮未命中"，
        即样本里多带了一段 Skill 正文，不是少带或带错。

    这是 ShareGPT 格式的固有限制（一条样本只能有一个 system），不是可修的 bug。
    真要消掉只能把多轮样本拆成单轮，那会丢掉"从历史轮取参数"这个训练目标 ——
    代价比 1.3% 大得多。
    """
    if _is_collect():
        _collected.add((message, style, tone))
        return COLLECT_PLACEHOLDER

    cache = load_cache()
    key = index_key(message, style, tone)
    digest = cache["index"].get(key)
    if digest is None:
        raise SystemPromptCacheMiss(
            f"缓存里没有这条消息的 system prompt：\n  {key}\n"
            "说明种子库/生成逻辑改过而缓存没重抓。跑：\n"
            "  python3 dataset/tools/capture_system_prompts.py\n"
            "**不要**在这里回退到手写提示词 —— 那会让数据与线上脱节且不报错。"
        )
    return cache["prompts"][digest]


def routed_skill(message: str) -> str | None:
    """后端确定性路由对这条消息选中的 Skill；没命中返回 None。

    命中时后端会把该 Skill 正文直接注入 system prompt，并写明
    「该 Skill 由系统内部加载，无需再调用 load_skill」
    （`backend/agent/learning/pedagogy_router.py:52-62`）。
    所以命中的消息**不该**再教模型调 `load_skill`。
    """
    if _is_collect():
        _collected.add((message, DEFAULT_STYLE, DEFAULT_TONE))
        return None
    route = load_cache()["routes"].get(message)
    if route is None:
        raise SystemPromptCacheMiss(
            f"缓存里没有这条消息的路由结果：{message!r}\n"
            "跑：python3 dataset/tools/capture_system_prompts.py"
        )
    return route["skill_name"]


def skill_names() -> list[str]:
    """线上 `# 可用 Skills` 索引里的 Skill 名，按索引里的顺序（priority 降序）。

    源是 `skills_bodies.json` 而不是提示词缓存 —— 提示词缓存要靠空跑生成器才能建，
    而生成器又要用这个函数，会转不出来。Skill 清单本来就属于那次抓取。
    """
    path = ROOT / "dataset/data/cache/skills_bodies.json"
    if not path.exists():
        raise SystemPromptCacheMiss(
            f"找不到 {path.relative_to(ROOT)}。\n"
            "先跑：python3 dataset/tools/capture_skill_bodies.py"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    _source_check("Skill 正文",
                  payload.get("_meta", {}).get("source_sha256"),
                  skill_source_hashes)
    return list(payload["_meta"]["skill_names"])


def system_for(turns, *, tone: str = DEFAULT_TONE) -> str:
    """一条样本的 system prompt：按**首条用户消息**路由，按**末条回答长度**定风格。

    七个生成器原本各写一遍 `build_system_prompt(style=style_for_answer(turns[-1].content))`，
    现在收成一个函数 —— 加了「消息」这个参数之后，七处各改各的迟早会漏掉一处，
    而漏掉的那一处不会报错，只会悄悄用错风格（交接文档第零节第 3 条）。
    """
    users = [t.content or "" for t in turns if t.role == "user"]
    if not users:
        raise ValueError("样本里没有 user 轮，算不出 system prompt")
    answers = [t.content or "" for t in turns if t.role == "assistant"]
    return build_system_prompt(
        users[0],
        style=style_for_answer(answers[-1] if answers else ""),
        tone=tone,
    )


def style_for_answer(text: str) -> str:
    """按最终回答的长度反推该用哪种风格，保证 system prompt 与回答自洽。

    默认风格 concise 要求「回答控制在 3 句内」，而学情报告类回答天然是多行列表。
    如果一律用默认值，等于在教模型无视风格指令。
    """
    sentences = sum(text.count(c) for c in "。！？\n")
    return "detailed" if sentences > 3 or len(text) > 120 else "concise"


def _flush_collected() -> None:
    """collect 模式退出时把收集到的键写出去，供 capture 脚本读取。"""
    if not _is_collect():
        return
    out = os.environ.get(COLLECT_OUT_ENV)
    if not out:
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[list[str]] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    merged = {tuple(k) for k in existing} | _collected
    path.write_text(
        json.dumps(sorted(list(k) for k in merged), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


atexit.register(_flush_collected)
