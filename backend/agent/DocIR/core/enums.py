# backend/agent/DocIR/core/enums.py

"""

这个文件干什么：DocIR V0.2 的稳定枚举。

直白点说就是：把文字来源、元素角色、严重程度等固定选项集中列出来，避免各处随便写字符串。

DocIR V0.2 的稳定枚举。
"""

from enum import Enum


class TextOrigin(str, Enum):
    NATIVE_TEXT = "native_text"
    OCR_TEXT = "ocr_text"
    # MinerU auto 产物未保留足够证据时，只能确定文字来自
    # PDF 文本层或 OCR 之一，不应把这个事实直接改写成 OCR。
    NATIVE_OR_OCR_UNVERIFIED = "native_or_ocr_unverified"
    DOCUMENT_CAPTION = "document_caption"
    PARSER_DERIVED = "parser_derived"
    UNKNOWN = "unknown"


class ElementRole(str, Enum):
    BODY = "body"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    ASIDE = "aside"
    DISCARDED = "discarded"


class Severity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class ValidationStatus(str, Enum):
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"


class AssetKind(str, Enum):
    ORIGINAL = "original"
    PAGE_IMAGE = "page_image"
    FIGURE = "figure"
    TABLE = "table"
    RAW_ARTIFACT = "raw_artifact"
    DEBUG_ARTIFACT = "debug_artifact"
