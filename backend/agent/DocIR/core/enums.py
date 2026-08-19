# backend/agent/DocIR/core/enums.py

"""

这个文件干什么：DocIR 的稳定枚举。

直白点说就是：把文字来源、元素角色、严重程度等固定选项集中列出来，避免各处随便写字符串。

DocIR 的稳定枚举。
"""

from enum import Enum


class TextOrigin(str, Enum):
    """封装 `TextOrigin` 的状态与行为。"""
    NATIVE_TEXT = "native_text"
    OCR_TEXT = "ocr_text"
    # MinerU auto 产物未保留足够证据时，只能确定文字来自
    # PDF 文本层或 OCR 之一，不应把这个事实直接改写成 OCR。
    NATIVE_OR_OCR_UNVERIFIED = "native_or_ocr_unverified"
    DOCUMENT_CAPTION = "document_caption"
    PARSER_DERIVED = "parser_derived"
    # 由视觉语言模型基于受 SHA-256 约束的视觉 Asset 生成；它可以用于
    # 检索和理解，但不是源文档逐字文字。
    VLM_DERIVED = "vlm_derived"
    UNKNOWN = "unknown"


class ElementRole(str, Enum):
    """封装 `ElementRole` 的状态与行为。"""
    BODY = "body"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    ASIDE = "aside"
    VLM_DESCRIPTION = "vlm_description"
    DISCARDED = "discarded"


class Severity(str, Enum):
    """封装 `Severity` 的状态与行为。"""
    WARNING = "warning"
    ERROR = "error"


class ValidationStatus(str, Enum):
    """封装 `ValidationStatus` 的状态与行为。"""
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"


class AssetKind(str, Enum):
    """封装 `AssetKind` 的状态与行为。"""
    ORIGINAL = "original"
    PAGE_IMAGE = "page_image"
    FIGURE = "figure"
    TABLE = "table"
    RAW_ARTIFACT = "raw_artifact"
    DEBUG_ARTIFACT = "debug_artifact"
