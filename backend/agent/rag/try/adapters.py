"""Small, schema-tolerant adapter used only by the projection experiment.

The production DocIR schema is intentionally not imported here.  This keeps the
experiment runnable with a replayed JSON response while documenting the fields
that are currently observed in ``Evidence``/``SearchHit`` and display results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CanonicalChunk:
    """Stable fields consumed by the projector, plus the untouched raw record."""

    chunk_id: str
    content: str
    evidence_id: str
    document_name: str | None
    section: str | None
    page: int | None
    author: str | None
    source_url: str | None
    quote_eligible: bool
    citation_mode: str
    locator: Any
    raw: Mapping[str, Any]


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _page(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Mapping):
        return _page(value.get("page") or value.get("page_number") or value.get("page_no"))
    return None


def _primary_evidence(item: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = item.get("evidence")
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping):
        return evidence[0]
    return {}


def adapt_result(payload: Mapping[str, Any]) -> list[CanonicalChunk]:
    """Map current result variants to a small canonical list.

    Accepted inputs are a full three-channel payload, its ``model_content``
    mapping, or a plain ``{"results": [...]}`` response.  Unknown fields are
    retained in ``raw`` and never discarded by this adapter.
    """

    model = payload.get("model_content") if isinstance(payload.get("model_content"), Mapping) else payload
    display = payload.get("display_content") if isinstance(payload.get("display_content"), Mapping) else {}
    audit = payload.get("audit_metadata") if isinstance(payload.get("audit_metadata"), Mapping) else {}
    model_items = model.get("results", []) if isinstance(model, Mapping) else []
    display_items = display.get("results", []) if isinstance(display, Mapping) else []
    display_by_id = {str(x.get("chunk_id")): x for x in display_items if isinstance(x, Mapping)}

    # The audit response is the authoritative provenance fallback when display
    # fields are missing (for example, older replay captures).
    evidence_by_chunk: dict[str, Mapping[str, Any]] = {}
    response = audit.get("response", {}) if isinstance(audit, Mapping) else {}
    for hit in response.get("hits", []) if isinstance(response, Mapping) else []:
        if not isinstance(hit, Mapping):
            continue
        for evidence in hit.get("evidence", []) or []:
            if isinstance(evidence, Mapping):
                evidence_by_chunk.setdefault(str(hit.get("chunk_id") or evidence.get("chunk_id")), evidence)

    chunks: list[CanonicalChunk] = []
    for index, raw_item in enumerate(model_items, start=1):
        if not isinstance(raw_item, Mapping):
            continue
        item = dict(raw_item)
        chunk_id = str(_first(item.get("chunk_id"), item.get("id"), f"chunk-{index}"))
        shown = display_by_id.get(chunk_id, {})
        evidence = _first(_primary_evidence(item), evidence_by_chunk.get(chunk_id), {})
        if not isinstance(evidence, Mapping):
            evidence = {}
        merged = {**evidence, **shown, **item}
        document_name = _first(merged.get("document_name"), merged.get("source"), merged.get("document"))
        section = _first(merged.get("section"), merged.get("section_path"))
        if isinstance(section, (list, tuple)):
            section = " / ".join(str(x) for x in section)
        locator = _first(merged.get("location"), merged.get("locator"), merged.get("locators"))
        chunks.append(
            CanonicalChunk(
                chunk_id=chunk_id,
                content=str(_first(item.get("content"), merged.get("evidence_text"), "")),
                evidence_id=str(_first(item.get("source_ref"), merged.get("evidence_id"), chunk_id)),
                document_name=str(document_name) if document_name is not None else None,
                section=str(section) if section is not None else None,
                page=_page(_first(merged.get("page"), locator)),
                author=str(merged["author"]) if merged.get("author") is not None else None,
                source_url=str(_first(merged.get("source_url"), merged.get("preview_url"))) if _first(merged.get("source_url"), merged.get("preview_url")) is not None else None,
                quote_eligible=bool(_first(item.get("quote_eligible"), merged.get("quote_eligible"), False)),
                citation_mode=str(_first(item.get("citation_mode"), "paraphrase_only_unverified")),
                locator=locator,
                raw=merged,
            )
        )
    return chunks

