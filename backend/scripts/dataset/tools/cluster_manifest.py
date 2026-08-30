"""集群文件清单：记下**我们在超算上有什么**，并能查出它被谁动过。

    # 在集群上跑，把输出贴回来
    python3 tools/cluster_manifest.py --scan

    # 在本机跑，与仓库里的基线比对
    python3 tools/cluster_manifest.py --check <贴回来的输出文件>
    python3 tools/cluster_manifest.py --check <文件> --save     # 认可当前状态，更新基线

为什么需要它
------------
助手**连不上超算**，集群上的状态只存在于某一次对话里；而超算是**共享账号**，
文件会被别人改、被别人删 —— `esa_lora_out/`（65 MB 的 adapter）就这么没过一次，
是隔了几天才发现的，当时的结论是「恢复只能重训」。

所以这张清单要回答四个问题：**有哪些文件、在哪、叫什么、有没有被动过。**

设计取舍
--------
· **只跟踪我们关心的那些**（下面 `TRACKED`），不遍历整个家目录 ——
  模型权重几百 GB，遍历一次的代价远大于收益。
· **小文件算哈希，大文件只记大小和 mtime**。哈希才能发现"内容变了但大小没变"，
  而对 65 MB 的 adapter 权重来说每次全量哈希不划算（阈值 `HASH_MAX`）。
· **目录 mtime 不可信**：它只在增删条目时变，**就地覆盖文件不会改目录 mtime** ——
  5.48 就是栽在这上面（据目录 mtime 判断 checkpoint 归属，结论完全反了）。
  所以这里只记文件，不记目录。
· 输出**一行一个文件、纯文本**，因为它唯一的回传通路是"贴回来"。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HOME = "/persist_data/home/chenxuzhao"
DS = f"{HOME}/esa-data/backend/scripts/dataset"
HASH_MAX = 4 * 1024 * 1024      # 超过这个大小只记 size+mtime

TRACKED = [
    f"{HOME}/LlamaFactory/esa_*.yaml",
    f"{HOME}/esa_*.sh",
    f"{HOME}/esa_results/*.json",
    f"{HOME}/esa_results/*.jsonl",
    f"{HOME}/esa_results/*.stale-*",
    f"{HOME}/esa_results/adapter_*/adapter_config.json",
    f"{HOME}/esa_results/adapter_*/adapter_model.safetensors",
    f"{DS}/tools/*.py",
    f"{DS}/esa/*.py",
    f"{DS}/data/eval/*.jsonl",
    f"{DS}/data/eval/*.json",
    f"{DS}/data/dpo/*",
    f"{DS}/schemas/*.json",
]

BASELINE = Path(__file__).resolve().parents[1] / "docs" / "集群清单.json"


def entry(path: Path) -> str:
    st = path.stat()
    if st.st_size <= HASH_MAX:
        h = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    else:
        h = f"（{st.st_size}B 未哈希）"
    return f"{st.st_size}\t{int(st.st_mtime)}\t{h}"


def scan() -> dict[str, str]:
    import glob  # noqa: PLC0415
    out: dict[str, str] = {}
    for pat in TRACKED:
        for f in sorted(glob.glob(pat)):
            p = Path(f)
            if p.is_file():
                try:
                    out[f] = entry(p)
                except OSError as e:
                    out[f] = f"读不到：{e}"
    return out


def parse_pasted(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("/"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 4:
            out[parts[0]] = "\t".join(parts[1:4])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="集群文件清单：扫描 / 比对")
    ap.add_argument("--scan", action="store_true", help="在集群上跑，打印清单")
    ap.add_argument("--check", help="在本机跑，比对贴回来的清单与基线")
    ap.add_argument("--save", action="store_true", help="连同 --check：认可当前状态，更新基线")
    args = ap.parse_args()

    if args.scan:
        got = scan()
        print(f"# 集群清单　{len(got)} 个文件　（路径\\t大小\\tmtime\\tsha256前16）")
        for k, v in sorted(got.items()):
            print(f"{k}\t{v}")
        print("# 清单结束——整段贴回给助手")
        return 0

    if not args.check:
        ap.error("要么 --scan（集群上），要么 --check <文件>（本机）")

    got = parse_pasted(args.check)
    if not got:
        sys.exit(f"❌ {args.check} 里没解析出任何条目（要以 / 开头、制表符分隔）")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))["files"] if BASELINE.exists() else {}

    added = sorted(set(got) - set(base))
    gone = sorted(set(base) - set(got))
    changed, touched = [], []
    for k in sorted(set(got) & set(base)):
        gs, gm, gh = got[k].split("\t")
        bs, bm, bh = base[k].split("\t")
        if gh != bh or gs != bs:
            changed.append((k, f"{bs}B/{bh} → {gs}B/{gh}"))
        elif gm != bm:
            touched.append(k)      # 内容没变、只是 mtime 变了

    if not base:
        print(f"（本机还没有基线，本次 {len(got)} 个文件将作为第一版）")
    print(f"新增 {len(added)}　消失 {len(gone)}　🔴内容变了 {len(changed)}　仅时间变了 {len(touched)}")
    for k in gone:
        print(f"  🔴 消失　{k}")
    for k, d in changed:
        print(f"  🔴 变了　{k}\n           {d}")
    for k in added:
        print(f"  ＋ 新增　{k}")
    if touched:
        print(f"  · 仅 mtime 变（内容相同）{len(touched)} 个，多半是被重新拷贝过")

    if gone or changed:
        print("\n⚠️ 共享账号——「消失」和「内容变了」都可能是别人动的。"
              "确认之后再 --save，别把别人的改动当成我们的基线。")
    if args.save:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(
            {"_note": "集群文件基线。由 tools/cluster_manifest.py --scan 产出、--check --save 更新。",
             "_updated": os.environ.get("MANIFEST_DATE", ""),
             "files": got}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"→ 基线已更新：{BASELINE}（{len(got)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
