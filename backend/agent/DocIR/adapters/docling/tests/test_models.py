"""Adapter configuration boundary tests."""

import pytest

from backend.agent.DocIR.adapters.docling import DoclingAdapterConfig


def test_cuda_is_required_by_contract() -> None:
    assert DoclingAdapterConfig().device == "cuda"
    assert DoclingAdapterConfig(device="cuda:1").device == "cuda:1"
    with pytest.raises(ValueError, match="cuda"):
        DoclingAdapterConfig(device="cpu")

