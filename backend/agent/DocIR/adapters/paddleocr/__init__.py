# backend/agent/DocIR/adapters/paddleocr/__init__.py

"""Public API for the local GPU PP-StructureV3-to-DocIR adapter."""

from .api import convert_source, materialize_bundle
from .bundle import PaddleOCRBundle, load_bundle
from .converter import convert_bundle, file_sha256
from .models import PaddleOCRAdapterConfig
from .runtime import run_paddleocr

__all__ = [
    "PaddleOCRAdapterConfig",
    "PaddleOCRBundle",
    "convert_bundle",
    "convert_source",
    "file_sha256",
    "load_bundle",
    "materialize_bundle",
    "run_paddleocr",
]
