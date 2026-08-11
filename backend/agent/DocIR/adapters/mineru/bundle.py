# backend/agent/DocIR/adapters/mineru/bundle.py

"""
这个文件干什么：发现并校验单个 MinerU 输出 bundle。

直白点说就是：找到同一次 MinerU 解析生成的几份文件，确认它们齐全后打包交给转换器。

发现并校验单个 MinerU 输出 bundle。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import RawMiddleDocument


@dataclass(frozen=True)
class RawV2Group:
    """V2 外层数组中的原始 group；位置是唯一稳定的 group anchor。"""

    group_index: int
    payload: Any

    @property
    def blocks(self) -> list[Any] | None:
        return self.payload if isinstance(self.payload, list) else None


@dataclass(frozen=True)
class MinerUBundle:
    root: Path
    middle_path: Path
    content_v2_path: Path
    model_path: Path | None
    middle: RawMiddleDocument
    content_v2: list[Any]
    content_list_path: Path | None = None
    content_list: Any = None
    model: Any = None
    middle_raw: dict[str, Any] | None = None

    @property
    def backend(self) -> str | None:
        return self.middle.backend

    @property
    def version_name(self) -> str | None:
        return self.middle.version_name

    @property
    def v2_groups(self) -> tuple[RawV2Group, ...]:
        return tuple(
            RawV2Group(group_index=index, payload=payload)
            for index, payload in enumerate(self.content_v2)
        )

    @property
    def raw_json_artifacts(self) -> dict[str, Any]:
        """返回 loader 实际保存的 raw JSON；path 用于区分 absent 与 JSON null。"""

        artifacts: dict[str, Any] = {
            "middle": self.middle_raw,
            "content_list_v2": self.content_v2,
        }
        if self.content_list_path is not None:
            artifacts["content_list"] = self.content_list
        if self.model_path is not None:
            artifacts["model"] = self.model
        return artifacts


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
    content_list_path = _exactly_one(root, "_content_list.json", required=False)
    model_path = _exactly_one(root, "_model.json", required=False)
    middle_raw = json.loads(middle_path.read_text(encoding="utf-8"))
    if not isinstance(middle_raw, dict):
        raise TypeError("middle.json 顶层必须是对象")
    middle = RawMiddleDocument.model_validate(middle_raw)
    content_v2 = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(content_v2, list):
        raise TypeError("content_list_v2 顶层必须是页面数组")
    content_list = (
        json.loads(content_list_path.read_text(encoding="utf-8"))
        if content_list_path is not None
        else None
    )
    model = (
        json.loads(model_path.read_text(encoding="utf-8"))
        if model_path is not None
        else None
    )
    return MinerUBundle(
        root=root,
        middle_path=middle_path,
        content_v2_path=content_path,
        model_path=model_path,
        middle=middle,
        content_v2=content_v2,
        content_list_path=content_list_path,
        content_list=content_list,
        model=model,
        middle_raw=middle_raw,
    )
