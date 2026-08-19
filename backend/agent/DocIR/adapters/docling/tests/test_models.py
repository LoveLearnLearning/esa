# backend/agent/DocIR/adapters/docling/tests/test_models.py

"""Adapter configuration boundary tests."""

import pytest

from backend.agent.DocIR.adapters.docling import DoclingAdapterConfig


def test_cuda_is_required_by_contract() -> None:
    """验证 `cuda_is_required_by_contract` 场景。"""
    assert DoclingAdapterConfig().device == "cuda"
    assert DoclingAdapterConfig(device="cuda:1").device == "cuda:1"
    with pytest.raises(ValueError, match="cuda"):
        DoclingAdapterConfig(device="cpu")
