# backend/scripts/dataset/tools/check_adapter_fresh.py

"""闸门：lora 评测前，确认 adapter 是**这次训练**产出的，不是上一轮的残留。

为什么要有这个（5.32 ②）
------------------------
`esa_eval_one.sh` 原来查 adapter 用的是 `[ -f "$A" ]`。而 `esa_lora_out/` 里
**本来就躺着上一轮的 adapter** —— 训练要是没写成功，闸门照样放行，
lora 评测会安安静静地测一遍旧模型，而且十二项指标全都长得很正常。
2026-08-20 那次是侥幸没踩（19:51:23 写入、19:52:15 训练结束）。

> **闸门查的必须是「对不对」，不是「在不在」。**

判据：adapter 的 mtime 必须晚于**本次训练作业的提交时刻**。

为什么写成 Python 而不是 shell 里几行
--------------------------------------
因为它要比较时间，而这个项目在时区上栽过（手册〇之六：集群是 UTC、
本地 UTC+8，差 8 小时，`squeue --start` 那次差点误判作业卡死）。
时间比较写在 shell 里既没法自测、又极容易把 8 小时的偏差吃进去而不自知 ——
**而这个方向的偏差是 fail-open 的**：把 UTC 串按 UTC+8 解析，提交时刻会早 8 小时，
于是一个提交前 8 小时内写下的旧 adapter 会被放行。正是闸门最不该有的失效方式。

所以：显式按 UTC 解析（解析不出来就**拒绝**，不放行），并把比较的两个时刻
原样打印出来，让人一眼能看出有没有偏。

用法
----
    python3 tools/check_adapter_fresh.py \\
        --adapter $HOME/esa_lora_out/adapter_model.safetensors \\
        --train-job 78907

自测（不碰 Slurm，直接喂一行假的 sacct 输出）：
    python3 tools/check_adapter_fresh.py --adapter X --train-job 1 \\
        --sacct-line "COMPLETED|2026-08-20T10:00:00" --adapter-mtime 1755684000
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

# sacct 一次取两列：状态 + 提交时刻。`-X` 只要主作业，不要 .batch/.extern 那些步骤行。
SACCT = ["sacct", "-n", "-X", "-P", "-o", "State,Submit", "-j"]


def parse_utc(text: str) -> int | None:
    """把 sacct 的时间串按 **UTC** 解析成 epoch 秒。解析不出来返回 None。

    ⚠️ 一定要显式给 UTC。不给的话 `datetime.fromisoformat` 产出 naive 时间，
    `.timestamp()` 会按**本机时区**解释它 —— 在 UTC+8 的机器上就偏 8 小时，
    而且偏的方向是让闸门变松（见模块头）。
    """
    text = text.strip()
    if not text or text in {"Unknown", "None", "N/A"}:
        return None
    try:
        naive = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return int(naive.replace(tzinfo=dt.timezone.utc).timestamp())


def fmt(epoch: float) -> str:
    """epoch → 可读的 UTC 串（比较用的两个时刻都按同一个基准印）。"""
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S UTC")


def sacct_line(job: str) -> str | None:
    """跑 sacct 取一行 `State|Submit`。跑不起来返回 None（**拒绝**，不放行）。"""
    try:
        r = subprocess.run(SACCT + [str(job)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.strip():
            return line.strip()
    return None


def check(adapter: Path, job: str, line: str | None, mtime: float | None, proof: Path | None = None) -> tuple[bool, list[str]]:
    """判定。返回 (通过与否, 要打印的行)。

    Args:
        adapter: Path => adapter 文件路径。
        job: str => 训练作业号。
        line: str | None => sacct 的 `State|Submit` 行；None 表示没取到。
        mtime: float | None => adapter 的 mtime（epoch 秒）；None 表示按文件现取。

    Returns:
        tuple[bool, list[str]] => 是否放行，以及逐行的说明。
    """
    out: list[str] = []
    if mtime is None:
        if not adapter.is_file():
            return False, [f"❌ adapter 不在（训练还没跑完？）：{adapter}"]
        mtime = adapter.stat().st_mtime

    if line is None:
        return False, [
            f"❌ sacct 查不到训练作业 {job} —— **拒绝放行**。",
            "   查不到就没法判断 adapter 是不是这次的，而放行的代价是",
            "   「安安静静测一遍旧模型，十二项指标全都长得很正常」。",
            f"   人工确认的话：sacct -X -j {job} -o State,Submit  再对比 stat -c %y 的 mtime。",
        ]

    parts = line.split("|")
    state, submit_raw = (parts + ["", ""])[:2]
    state = state.strip().split()[0] if state.strip() else ""
    submit = parse_utc(submit_raw)

    if state != "COMPLETED":
        # 🔴 2026-09-04 加的窄口子。起因：94421 训练**跑满了** 105 步、adapter 与
        # 输出目录 md5 一致，但作业最后一步另存时 /persist_data 满了（Errno 28），
        # 脚本 exit 1，于是 sacct 记成 FAILED。这道闸门据此判「这次训练没成功」——
        # 判错了，而重训要烧四小时 GPU。
        #
        # 但**不能**因此放宽成「FAILED 也放行」：这道闸门存在的理由正是
        # 「训练没写成功时别拿旧 adapter 去评测」（5.32 ②）。
        # 所以口子要同时满足两条，缺一不可：
        #   ① 调用方显式给 --completed-proof（不会顺手发生）
        #   ② 那份 trainer_state.json 自己证明跑满了：global_step == max_steps
        # 证据来自训练进程自己写的文件，比作业退出码更接近「训练有没有跑完」这件事。
        if proof is None:
            return False, [
                f"❌ 训练作业 {job} 的状态是 {state or '(空)'}，不是 COMPLETED —— 这次训练没成功",
                "   如果确认训练本身跑满了、只是作业最后一步（比如另存）失败，",
                "   用 --completed-proof <trainer_state.json> 再来一次；那份文件要能自证 "
                "global_step == max_steps。",
            ]
        done, why = _finished(proof)
        if not done:
            return False, [
                f"❌ 训练作业 {job} 的状态是 {state}，而 --completed-proof 也证明不了跑完：{why}",
            ]
        out.append(f"⚠️ 训练作业 {job} 状态是 {state}，但 {proof.name} 自证跑满（{why}）——")
        out.append("   按证据放行。**这条只对「训练跑完、收尾失败」成立**，别当成常规用法。")
    if submit is None:
        return False, [
            f"❌ sacct 给的提交时刻解析不出来：{submit_raw!r} —— **拒绝放行**。",
            "   （按 UTC 解析。解析不了就不猜，猜错的方向会让闸门变松。）",
        ]

    out.append(f"   训练作业 {job}：状态 {state}，提交于 {fmt(submit)}")
    out.append(f"   adapter mtime：            {fmt(mtime)}")
    if mtime <= submit:
        out.append(f"❌ adapter 比训练作业 {job} 的提交时刻还早 —— 这是**上一轮的残留**，")
        out.append("   拿它去评测等于测一遍旧模型。先确认训练真的写出了新 adapter。")
        return False, out
    out.append(f"✅ 闸门：adapter 晚于提交时刻 {int(mtime - submit)} 秒，是这次训练的产出")
    return True, out


def _finished(proof: Path) -> tuple[bool, str]:
    """读 trainer_state.json，判断这次训练是不是**跑满了**。

    判据是 `global_step == max_steps` —— 训练进程自己写的两个数。
    读不到、对不上、文件坏了，一律判「证明不了」，不猜。
    """
    import json  # noqa: PLC0415
    try:
        d = json.loads(proof.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"{proof} 读不出来（{exc}）"
    gs, ms = d.get("global_step"), d.get("max_steps")
    if not isinstance(gs, int) or not isinstance(ms, int) or ms <= 0:
        return False, f"global_step={gs!r} / max_steps={ms!r}，不是一对能比的数"
    if gs != ms:
        return False, f"global_step={gs} ≠ max_steps={ms}，训练没跑满"
    return True, f"global_step={gs} = max_steps={ms}"


def _tmp_state(global_step: int, max_steps: int) -> Path:
    """自测用：写一份临时 trainer_state.json，返回路径。"""
    import json      # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"global_step": global_step, "max_steps": max_steps}, fh)
    fh.close()
    return Path(fh.name)


def self_test() -> int:
    """把判据自己跑一遍。**在超算上跑这个**，那里才是真时区、真环境。

    为什么闸门要自带自测：这道闸门一年也响不了几次，平时全是 ✅ ——
    而「一个永远绿的检查」和「一个坏掉的检查」在日志里长得一模一样。
    `--self-test` 让它随时能证明自己还认得出坏情况。

    ⚠️ 第 5、6 条是时区用例，也是这里最要紧的两条：把 UTC 串按本机时区解析，
    提交时刻会**早 8 小时**，于是提交前 8 小时内写下的旧 adapter 会被放行 ——
    fail-open，闸门最不该有的失效方式。实测过：去掉 `tzinfo=utc` 之后，
    在 `TZ=Asia/Shanghai` 下第 6 条当场变成放行。
    """
    def at(y, mo, d, h, mi) -> int:
        return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp())

    fake = Path("/nonexistent/adapter.safetensors")
    submit = "COMPLETED|2026-08-20T10:00:00"
    cases = [
        ("adapter 晚于提交 → 放行",
         check(fake, "1", submit, at(2026, 8, 20, 11, 30))[0] is True),
        ("adapter 早于提交（上一轮残留）→ 拦下",
         check(fake, "1", submit, at(2026, 8, 20, 4, 0))[0] is False),
        ("训练作业 FAILED → 拦下",
         check(fake, "1", "FAILED|2026-08-20T10:00:00", at(2026, 8, 21, 0, 0))[0] is False),
        ("sacct 查不到 → 拦下（fail-closed，不是放行）",
         check(fake, "1", None, at(2026, 8, 21, 0, 0))[0] is False),
        ("提交时刻解析不了 → 拦下，不猜",
         check(fake, "1", "COMPLETED|Unknown", at(2026, 8, 21, 0, 0))[0] is False),
        ("时区：UTC 串按 UTC 解析，残留在任何 TZ 下都拦得住",
         parse_utc("2026-08-20T10:00:00") == at(2026, 8, 20, 10, 0)),
        # ── 2026-09-04 那个窄口子的三条反向验证 ──
        ("FAILED + 没给 proof → 仍然拦下",
         check(fake, "1", "FAILED|2026-08-20T10:00:00", at(2026, 8, 21, 0, 0),
               None)[0] is False),
        ("FAILED + proof 说没跑满 → 仍然拦下",
         check(fake, "1", "FAILED|2026-08-20T10:00:00", at(2026, 8, 21, 0, 0),
               _tmp_state(63, 105))[0] is False),
        ("FAILED + proof 自证跑满 → 放行（这才是那个口子）",
         check(fake, "1", "FAILED|2026-08-20T10:00:00", at(2026, 8, 21, 0, 0),
               _tmp_state(105, 105))[0] is True),
        ("FAILED + proof 跑满，但 adapter 早于提交 → 还是拦下（新增的口子不该盖住老判据）",
         check(fake, "1", "FAILED|2026-08-20T10:00:00", at(2026, 8, 20, 4, 0),
               _tmp_state(105, 105))[0] is False),
    ]
    ok = 0
    for name, passed in cases:
        print(f"{'✅' if passed else '❌'} {name}")
        ok += bool(passed)
    print(f"\n{ok} 通过 / {len(cases) - ok} 失败"
          f"（本机 TZ={dt.datetime.now().astimezone().tzname()}）")
    return 0 if ok == len(cases) else 1


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。"""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    if argv is None:
        argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    ap.add_argument("--self-test", action="store_true",
                    help="把判据自己跑一遍（六条，含两条时区用例），不碰 Slurm")
    ap.add_argument("--adapter", required=True, type=Path)
    ap.add_argument("--train-job", required=True)
    # 下面两个只给自测用：不碰 Slurm、不碰文件系统也能把判据跑一遍。
    ap.add_argument("--sacct-line", default=None,
                    help="自测用：直接给一行 'State|Submit'，不去跑 sacct")
    ap.add_argument("--adapter-mtime", default=None, type=float,
                    help="自测用：直接给 adapter 的 mtime（epoch 秒）")
    ap.add_argument("--completed-proof", default=None, type=Path,
                    help="训练跑满了但作业收尾失败时才用：指向那次训练的 trainer_state.json。"
                         "只有当它自证 global_step == max_steps 才放行，"
                         "**不是**「跳过状态检查」的开关")
    a = ap.parse_args(argv)

    line = a.sacct_line if a.sacct_line is not None else sacct_line(a.train_job)
    ok, lines = check(a.adapter, a.train_job, line, a.adapter_mtime, a.completed_proof)
    for text in lines:
        print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
