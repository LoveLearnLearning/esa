"""Tenant-bound request tests for the personal Qdrant adapter."""

from __future__ import annotations

from typing import Any, ClassVar

from backend.agent.rag.chunk import Chunk, ContentRole
from backend.agent.rag.indexes import PersonalQdrantIndex


class CapturingPersonalQdrant(PersonalQdrantIndex):
    calls: ClassVar[list[tuple[str, str, dict[str, Any] | None]]] = []

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if path.endswith("/points/query"):
            return {"result": {"points": []}}
        if path.endswith("/points/count"):
            return {"result": {"count": 0}}
        if path.endswith("/points/scroll"):
            return {"result": {"points": []}}
        return {"status": "ok"}


def _chunk(chunk_id: str = "chunk-one") -> Chunk:
    # model_construct keeps this request-shape test independent of DocIR
    # locator fixtures; production chunks have already passed model validation.
    return Chunk.model_construct(
        chunk_id=chunk_id,
        chunk_revision_id="revision",
        document_order=0,
        document_id="document",
        source_version_id="source",
        parse_revision_id="parse",
        section_id="section",
        section_path=("Heading",),
        element_ids=("element",),
        kind_counts={"paragraph": 1},
        content_role=ContentRole.BODY,
        retrieval_enabled=True,
        dense_text="Heading\nbody",
        bm25_body="body",
        bm25_heading="Heading",
        body_char_count=4,
        evidence=(),
    )


def _matches(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        item["key"]: item["match"]
        for item in payload["filter"]["must"]
    }


def test_point_identity_and_payload_are_tenant_scoped():
    index = CapturingPersonalQdrant("http://qdrant", "personal")
    first = index._point(
        _chunk(), [1.0, 0.0], user_id="u1", file_id="f1",
        generation_id="g1", ingestion_revision=1,
    )
    second = index._point(
        _chunk(), [1.0, 0.0], user_id="u2", file_id="f2",
        generation_id="g1", ingestion_revision=1,
    )
    assert first["id"] != second["id"]
    assert first["payload"] | {
        "scope": "personal",
        "user_id": "u1",
        "file_id": "f1",
        "kb_generation_id": "g1",
        "ingestion_revision": 1,
        "visible": False,
    } == first["payload"]


def test_all_query_routes_merge_tenant_generation_visibility_and_roles():
    CapturingPersonalQdrant.calls.clear()
    index = CapturingPersonalQdrant("http://qdrant", "personal")
    kwargs = {
        "user_id": "u1",
        "generation_id": "g1",
        "content_roles": frozenset({ContentRole.BODY}),
    }
    index.dense([1.0], 5, **kwargs)
    index.bm25_body("query", 5, **kwargs)
    index.bm25_heading("query", 5, **kwargs)
    queries = [call for call in index.calls if call[1].endswith("/points/query")]
    assert len(queries) == 3
    for _method, _path, payload in queries:
        assert payload is not None
        matches = _matches(payload)
        assert matches == {
            "scope": {"value": "personal"},
            "user_id": {"value": "u1"},
            "kb_generation_id": {"value": "g1"},
            "visible": {"value": True},
            "content_role": {"any": ["body"]},
        }


def test_count_hide_and_delete_reuse_the_same_tenant_filter():
    CapturingPersonalQdrant.calls.clear()
    index = CapturingPersonalQdrant("http://qdrant", "personal")
    index.count(user_id="u1", generation_id="g1", file_id="f1")
    index.set_file_visibility(
        user_id="u1", generation_id="g1", file_id="f1", visible=False
    )
    index.delete_file(user_id="u1", generation_id="g1", file_id="f1")
    for _method, _path, payload in index.calls:
        assert payload is not None
        matches = _matches(payload)
        assert matches["scope"] == {"value": "personal"}
        assert matches["user_id"] == {"value": "u1"}
        assert matches["kb_generation_id"] == {"value": "g1"}
        assert matches["file_id"] == {"value": "f1"}


def test_evidence_query_adds_sqlite_live_file_allowlist():
    CapturingPersonalQdrant.calls.clear()
    index = CapturingPersonalQdrant("http://qdrant", "personal")

    index.query_points(
        [1.0],
        index.dense_name,
        5,
        user_id="u1",
        generation_id="g1",
        file_ids=("live-2", "live-1"),
    )

    payload = CapturingPersonalQdrant.calls[-1][2]
    assert payload is not None
    assert _matches(payload)["file_id"] == {"any": ["live-1", "live-2"]}


def test_snapshot_privacy_verifier_uses_user_and_file_for_count_and_scroll():
    CapturingPersonalQdrant.calls.clear()
    index = CapturingPersonalQdrant("http://qdrant", "temporary-verification")

    assert index.maintenance_file_absent(user_id="u1", file_id="deleted") is True

    requests = [
        payload
        for _method, path, payload in index.calls
        if path.endswith(("/points/count", "/points/scroll"))
    ]
    assert len(requests) == 2
    for payload in requests:
        assert payload is not None
        matches = _matches(payload)
        assert matches == {
            "scope": {"value": "personal"},
            "user_id": {"value": "u1"},
            "file_id": {"value": "deleted"},
        }


def test_user_purge_delete_and_verification_never_require_generation_ids():
    CapturingPersonalQdrant.calls.clear()
    index = CapturingPersonalQdrant("http://qdrant", "personal")

    index.maintenance_delete_user(user_id="u1")
    assert index.maintenance_user_absent(user_id="u1") is True

    requests = [
        payload
        for _method, path, payload in index.calls
        if path.endswith(("/points/delete?wait=true", "/points/count", "/points/scroll"))
    ]
    assert len(requests) == 3
    for payload in requests:
        assert payload is not None
        assert _matches(payload) == {
            "scope": {"value": "personal"},
            "user_id": {"value": "u1"},
        }
