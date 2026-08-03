# backend/agent/DocIR/adapters/mineru/bundle.py

"""

这个文件干什么：发现并校验单个 MinerU 输出 bundle。

直白点说就是：找到同一次 MinerU 解析生成的几份文件，确认它们齐全后打包交给转换器。

发现并校验单个 MinerU 输出 bundle。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .models import RawMiddleDocument


@dataclass(frozen=True)
class MinerUBundle:
    root: Path
    middle_path: Path
    content_v2_path: Path
    model_path: Path | None
    middle: RawMiddleDocument
    content_v2: list


def _exactly_one(root: Path, suffix: str, *, required: bool = True) -> Path | None:
    matches = sorted(root.glob(f"*{suffix}"))
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise ValueError(f"MinerU bundle 要求恰好一个 *{suffix}，实际 {len(matches)} 个")
    return matches[0]


def load_bundle(root: Path) -> MinerUBundle:
    """加载 MinerU 目录；middle 和 content_list_v2 必需。"""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    middle_path = _exactly_one(root, "_middle.json")
    content_path = _exactly_one(root, "_content_list_v2.json")
    model_path = _exactly_one(root, "_model.json", required=False)
    middle = RawMiddleDocument.model_validate_json(middle_path.read_text(encoding="utf-8"))
    content_v2 = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(content_v2, list):
        raise TypeError("content_list_v2 顶层必须是页面数组")
    return MinerUBundle(root, middle_path, content_path, model_path, middle, content_v2)
