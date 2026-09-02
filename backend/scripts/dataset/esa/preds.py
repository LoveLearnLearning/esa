"""预测文件与评测集指纹 —— **只用标准库**。

为什么单独一个模块：`measure_verbosity` 这类轻工具只需要下面两个函数，
可 `esa/eval.py` 顶上有 `from jsonschema import Draft7Validator`、
`transformers` 等一串重依赖。2026-08-26 在集群上就是这么炸的：

    from esa.eval import fingerprint_of, load_preds_file
      → esa/eval.py:37  ModuleNotFoundError: No module named 'jsonschema'

**轻工具不该因为借两个函数就把整条依赖链拖进来。**
所以把它们下沉到这里，`eval.py` 从这里 import —— 实现仍然只有一份（5.54），
但轻工具不再需要 `jsonschema`。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fingerprint_of(path: Path) -> str:
    """按路径算评测集指纹。`eval_fingerprint` 和外部工具共用这一份实现。

    ⚠️ 别在别处再写一遍 —— 同一个概念两处各算一遍，就等于没有它（5.54）。
    """
    raw = path.read_bytes()
    n = sum(1 for line in raw.splitlines() if line.strip())
    return f"{hashlib.sha256(raw).hexdigest()[:16]}#{n}"


def load_preds_file(path: Path) -> tuple[dict, dict[str, str]]:
    """按路径读预测文件，返回 `(_meta, {id: raw})`。

    🔴 **首行是指纹行，没有 `id`**（见 eval.py 里 predict 那段的注释）。直接
    `row["id"]` 会 KeyError —— 2026-08-26 外部工具自己写了一遍读取就栽在这里。
    要读预测文件就用这个函数，别再写第二份。
    """
    meta: dict = {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "_meta" in row:
            meta = row["_meta"]
        elif "id" in row:
            out[row["id"]] = row["raw"]
    return meta, out
