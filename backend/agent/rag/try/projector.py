"""Metadata/context projection prototype (方案 A, with small fixed profiles)."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from adapters import CanonicalChunk, adapt_result
from router import ContextRouter, Profile, RouteDecision


def _model_item(chunk: CanonicalChunk, profile: Profile, ref: str) -> dict[str, Any]:
    result: dict[str, Any] = {"ref": ref, "content": chunk.content}
    if profile in (Profile.SOURCE, Profile.LOCATION, Profile.FULL):
        result.update({"source": chunk.document_name, "author": chunk.author})
    if profile in (Profile.LOCATION, Profile.FULL):
        result.update({"section": chunk.section, "page": chunk.page, "locator": chunk.locator})
    if profile is Profile.FULL:
        # FULL is a debug profile, not the default. Keep the complete per-hit
        # record visible to a diagnostic model while audit retains the envelope.
        result["metadata"] = dict(chunk.raw)
    return result


def project_for_model(payload: Mapping[str, Any], profile: Profile = Profile.MINIMAL) -> dict[str, Any]:
    """Return model/display/audit channels and a ref→provenance registry.

    The input is never mutated.  ``audit_metadata.full_retrieval`` is a deep
    enough JSON copy of the original payload for replay/inspection purposes.
    """

    chunks = adapt_result(payload)
    refs = {chunk.chunk_id: f"C{index}" for index, chunk in enumerate(chunks, start=1)}
    results = [_model_item(chunk, profile, refs[chunk.chunk_id]) for chunk in chunks]
    registry = {
        refs[chunk.chunk_id]: {
            "chunk_id": chunk.chunk_id,
            "evidence_id": chunk.evidence_id,
            "document_name": chunk.document_name,
            "section": chunk.section,
            "page": chunk.page,
            "author": chunk.author,
            "source_url": chunk.source_url,
            "quote_eligible": chunk.quote_eligible,
            "citation_mode": chunk.citation_mode,
            "locator": chunk.locator,
            "metadata": dict(chunk.raw),
        }
        for chunk in chunks
    }
    model_content = {"profile": profile.value, "results": results}
    display = {
        "results": [
            {"ref": refs[c.chunk_id], "chunk_id": c.chunk_id, **dict(c.raw)}
            for c in chunks
        ]
    }
    return {
        "model_content": model_content,
        "display_content": display,
        "audit_metadata": {
            "projection_profile": profile.value,
            "ref_registry": registry,
            "full_retrieval": copy.deepcopy(payload),
        },
    }


def project_for_query(
    payload: Mapping[str, Any],
    query: str,
    router: ContextRouter,
) -> tuple[RouteDecision, dict[str, Any]]:
    """Thin seam for replacing the rule router with a fine-tuned one later."""

    decision = router.route(query)
    return decision, project_for_model(payload, decision.profile)
