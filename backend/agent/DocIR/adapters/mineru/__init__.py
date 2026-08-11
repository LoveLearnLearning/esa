# backend/agent/DocIR/adapters/mineru/__init__.py

"""

这个文件干什么：集中导出 MinerU bundle 加载、转换和文件哈希能力。

直白点说就是：把 MinerU 文件读取和转换功能集中摆到一个入口，外部不用钻进内部模块。
"""

from .bundle import MinerUBundle, RawV2Group, load_bundle
from .converter import convert_bundle, file_sha256, source_media_type

__all__ = [
    "MinerUBundle",
    "RawV2Group",
    "convert_bundle",
    "file_sha256",
    "load_bundle",
    "source_media_type",
]
