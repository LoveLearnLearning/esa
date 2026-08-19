# backend/agent/DocIR/adapters/docling/__init__.py

"""Public API for the local CUDA Docling-to-DocIR adapter."""

from .api import convert_source, materialize_bundle
from .bundle import DoclingBundle, load_bundle
from .converter import convert_bundle, file_sha256
from .models import DoclingAdapterConfig
from .runtime import run_docling

__all__ = [
    "DoclingAdapterConfig",
    "DoclingBundle",
    "convert_bundle",
    "convert_source",
    "file_sha256",
    "load_bundle",
    "materialize_bundle",
    "run_docling",
]
