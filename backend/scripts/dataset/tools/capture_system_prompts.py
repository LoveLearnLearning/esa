# backend/scripts/dataset/tools/capture_system_prompts.py

"""抓取**线上真实 system prompt**，落成缓存。

为什么不复刻
------------
`esa/system_prompt.py` 以前是一份手写复刻。2026-08-11 后端一改（删 MATH_PRMOPT、
加确定性路由、Skill 9→11、首句改成「辅助计算机专业学生」），复刻从 1,308 字符
对不上 3,145 字符的线上值，**而且所有校验照样是绿的**。

这是交接文档第五节第 4 条规矩：**凡是"线上长什么样"的问题，能跑就别想。**
和 `capture_math_outputs.py` 完全同一个套路 —— import 后端，跑真实函数。

跑的是什么
----------
逐条调用生产使用的 `WorkspaceRuntime.prepare_evaluation()`。路由、能力裁剪、Skill
autoload、上下文信任分层和最终渲染全部由生产编译器完成；本脚本只构造一个无画像、
无历史、无附件的 learning turn，并读取生成结果的第一条 system message。

消息从哪来
----------
只有生成器自己知道它要哪些消息。所以先用 `ESA_SYSTEM_PROMPT_MODE=collect`
把七个生成器空跑一遍（collect 模式下 `dump_samples` 拒绝落盘，不会产出半成品），
把 (消息, 风格, 语调) 收齐，再拿去后端渲染。

用法
----
    python3 dataset/tools/capture_system_prompts.py                # 默认用本地 ~/esa
    python3 dataset/tools/capture_system_prompts.py --repo <路径>
    python3 dataset/tools/capture_system_prompts.py --keys <file>  # 跳过空跑，用现成的键
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "dataset"))
import backend_repo  # noqa: E402
from esa.cache_contract import prompt_source_fingerprint  # noqa: E402

OUT = ROOT / "dataset/data/cache/system_prompts.json"
GENERATORS = ROOT / "dataset/generators"

# 和 esa/system_prompt.py 里的常量保持一致。渲染参数变了缓存必须重抓。
USER_NAME = "同学"
DEFAULT_STYLE = "concise"
DEFAULT_TONE = "friendly"
# 每条消息都把两种风格都渲染出来：style_for_answer 是按回答长度反推的，
# 回答一改风格就跟着变，全渲染出来就不用为这种小改动重抓。
STYLES = ("concise", "detailed")

def generator_scripts() -> list[Path]:
    """`generators/gen_*.py` 全部自动发现。

    ⚠️ 这里原本是一份写死的名单。新增 `gen_refusals.py` 时它没被算进去，
    于是那个生成器要的消息一条都没进缓存，正式跑的时候直接抛
    `SystemPromptCacheMiss` —— 而且报错信息指向缓存，不指向这份名单，
    排查起来会绕远路。

    这是交接文档第零节第 3 条那个坑的又一个入口：**同一件事写在两个地方**。
    改成扫目录之后，加生成器就不用记得回来改这里了。
    """
    return sorted(GENERATORS.glob("gen_*.py"))


def collect_keys() -> list[tuple[str, str, str]]:
    """空跑七个生成器，收集它们需要的 (消息, 风格, 语调)。"""
    with tempfile.TemporaryDirectory(prefix="esa_sp_collect_") as tmp_dir:
        tmp = Path(tmp_dir) / "keys.json"
        env = {
            **os.environ,
            "ESA_SYSTEM_PROMPT_MODE": "collect",
            "ESA_SYSTEM_PROMPT_COLLECT_OUT": str(tmp),
            "PYTHONPATH": str(ROOT / "dataset"),
            "PYTHONIOENCODING": "utf-8",
        }
        scripts = generator_scripts()
        print(f"空跑 {len(scripts)} 个生成器收集消息（collect 模式，不落盘）：")
        for script in scripts:
            proc = subprocess.run(
                [sys.executable, str(script)], env=env, cwd=ROOT,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                # 空跑失败要吵。静默跳过等于少收一批消息，
                # 到正式生成时才炸，而且看不出少的是哪一批。
                raise SystemExit(
                    f"{script.name} 空跑失败（退出码 {proc.returncode}）：\n"
                    f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
                )
            print(f"  {script.name} OK")

        if not tmp.exists():
            raise SystemExit(
                "没有收集到任何消息 —— 生成器可能没再调 build_system_prompt"
            )
        keys = [tuple(k) for k in json.loads(tmp.read_text(encoding="utf-8"))]
        print(f"收集到 {len(keys)} 组键、{len({k[0] for k in keys})} 条不同的消息")
        return keys


def load_keys(path: Path) -> list[tuple[str, str, str]]:
    """Load either a collected key list or an existing prompt cache index."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("index"), dict):
        return [tuple(json.loads(key)) for key in payload["index"]]
    return [tuple(key) for key in payload]


def load_backend(repo: Path):
    """import 后端，返回渲染一条 system prompt 所需的全部零件。"""
    sys.path.insert(0, str(repo))
    try:
        from backend.agent.learning.pedagogy_router import PedagogyRouter  # noqa: PLC0415
        from backend.agent.tools.bootstrap import register_builtin_tools  # noqa: PLC0415
        from backend.agent.tools.context import AgentRuntimeDependencies  # noqa: PLC0415
        from backend.agent.workspaces.models import AgentTurnInput  # noqa: PLC0415
        from backend.agent.workspaces.runtime import WorkspaceRuntime  # noqa: PLC0415
        from backend.core.router.basic_router import route_workspace  # noqa: PLC0415
        from backend.core.router.context import ConversationContext, RoutingContext  # noqa: PLC0415
        from backend.core.router.models import TrustedIdentity  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            f"无法 import 后端 prompt 组装链：{exc}\n"
            "先 pip install 后端依赖再重试。"
            "注意不要改用本地手写版顶替 —— 那正是这个脚本要修掉的问题。"
        ) from exc

    register_builtin_tools()
    identity = TrustedIdentity("dataset-user", USER_NAME, "student")
    conversation_id = "dataset-learning-conversation"
    route = route_workspace(
        identity,
        RoutingContext(
            ConversationContext(
                conversation_id,
                identity.user_id,
                "learning",
            )
        ),
    )
    runtime = WorkspaceRuntime(AgentRuntimeDependencies())
    profile = runtime.profiles.resolve(route.agent_profile_id, route.workspace_type)
    capabilities = runtime.capabilities.compile(
        skill_scopes=route.skill_scopes,
        tool_scopes=route.tool_scopes,
        profile_fingerprint=f"{profile.profile_id}:{profile.version}",
        policy_versions=(
            profile.profile_policy,
            profile.memory_policy_id,
            profile.action_policy,
        ),
        resource_capabilities=route.resource_scope.capabilities,
        conversation_mode="normal",
        has_research_project=False,
        has_attachments=False,
    )
    return {
        "router": PedagogyRouter,
        "runtime": runtime,
        "route": route,
        "identity": identity,
        "conversation_id": conversation_id,
        "AgentTurnInput": AgentTurnInput,
        "skills_context": capabilities.capabilities.skill_index,
        "skills_detail": [
            (skill.name, skill.description)
            for skill in capabilities.skills.definitions
        ],
    }


def render(be, message: str, style: str, tone: str) -> tuple[str, object]:
    """跑一次生产 Workspace 编译链，返回 (提示词正文, 路由决策)。"""
    decision = be["router"].route(message)
    turn = be["AgentTurnInput"](
        route=be["route"],
        identity=be["identity"],
        conversation_id=be["conversation_id"],
        current_message=message,
        user_preferences={
            "preferred_style": style,
            "preferred_tone": tone,
        },
        request_metadata={"request_id": "dataset-prompt-capture"},
    )
    spec = be["runtime"].prepare_evaluation(turn)
    text = str(spec.messages[0]["content"])
    return text, decision


def main() -> int:
    """运行当前模块的命令行入口。"""
    ap = argparse.ArgumentParser(description="抓取线上真实 system prompt")
    ap.add_argument("--repo", help="本地后端仓库副本；默认 ~/esa")
    ap.add_argument("--download", action="store_true", help="强制下载快照（抓不到本地改动，慎用）")
    ap.add_argument(
        "--keys",
        action="append",
        help="现成的键文件；可重复传入并合并，给了就跳过空跑",
    )
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    if args.keys:
        keys = sorted(
            {
                key
                for key_path in args.keys
                for key in load_keys(Path(key_path))
            }
        )
        print(f"用现成键文件：{len(keys)} 组")
    else:
        keys = collect_keys()

    messages = sorted({k[0] for k in keys})
    tones = sorted({k[2] for k in keys}) or [DEFAULT_TONE]

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        be = load_backend(backend.path)

        prompts: dict[str, str] = {}
        index: dict[str, str] = {}
        routes: dict[str, dict] = {}
        route_counter: Counter[str] = Counter()

        for message in messages:
            for style in STYLES:
                for tone in tones:
                    text, decision = render(be, message, style, tone)
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                    prompts[digest] = text
                    index[json.dumps([message, style, tone], ensure_ascii=False, sort_keys=True)] = digest
            # 路由只看消息，与风格/语调无关 —— 这一点由下面的断言守住。
            routes[message] = {
                "skill_name": decision.skill_name,
                "task_type": decision.task_type,
                "confidence": decision.confidence,
            }
            route_counter[decision.skill_name or "（未命中）"] += 1

            # 我们不传 profile / history，所以这两项必须恒为空。
            # 哪天开始传了，缓存键要跟着加维度 —— 让它在这里先炸，别等数据错了才发现。
            assert decision.primary_kp_id is None, (
                f"primary_kp_id 不再恒为 None（{decision.primary_kp_id!r}），"
                "说明路由多了一个输入维度，缓存键必须跟着加"
            )
            assert decision.teaching_depth == "standard", (
                f"teaching_depth 不再恒为 standard（{decision.teaching_depth!r}），同上"
            )

        payload = {
            "_meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "prompt_source_fingerprint": prompt_source_fingerprint(
                    backend.path
                ),
                "note": (
                    "由 dataset/tools/capture_system_prompts.py 调用生产 "
                    "WorkspaceRuntime.prepare_evaluation 产出，禁止手改"
                ),
                "render_params": {
                    "user_name": USER_NAME,
                    "styles": list(STYLES),
                    "tones": tones,
                    "profile": None,
                    "history": None,
                    "workspace_type": "learning",
                },
                "skill_names": [name for name, _ in be["skills_detail"]],
                "skills_index_block": be["skills_context"],
            },
            "prompts": prompts,
            "index": index,
            "routes": routes,
        }
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    print(f"\n{len(messages)} 条消息 x {len(STYLES)} 风格 x {len(tones)} 语调 "
          f"= {len(index)} 次渲染 → 只有 {len(prompts)} 种不同的提示词")
    print(f"缓存 {size_kb:.0f}KB → {backend_repo.display_path(out_path, ROOT)}")
    print(f"  来源：{backend.describe()}")
    print(f"  长度：{min(len(p) for p in prompts.values())}–{max(len(p) for p in prompts.values())} 字符")
    print("  路由命中分布：")
    for name, n in route_counter.most_common():
        print(f"    {name:26s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
