"""Stable payload and filter contract for the unified knowledge collection."""

from __future__ import annotations

from typing import Any, Literal


UNIFIED_COLLECTION_SCHEMA_VERSION = "esa-unified-knowledge-0.1"
PUBLIC_SCOPE: Literal["public"] = "public"
PERSONAL_SCOPE: Literal["personal"] = "personal"

# Qdrant can filter an unindexed payload field, but these fields are on every
# online authorization or lifecycle path and must have deterministic indexes.
UNIFIED_PAYLOAD_INDEXES: tuple[tuple[str, str], ...] = (
    ("scope", "keyword"),
    ("visible", "bool"),
    ("content_role", "keyword"),
    ("index_generation_id", "keyword"),
    ("kb_generation_id", "keyword"),
    ("user_id", "keyword"),
    ("knowledge_base_id", "keyword"),
    ("file_id", "keyword"),
    ("document_id", "keyword"),
)


def match_value(key: str, value: object) -> dict[str, Any]:
    """Build one exact Qdrant payload match condition."""

    return {"key": key, "match": {"value": value}}


def match_any(key: str, values: list[str]) -> dict[str, Any]:
    """Build one Qdrant any-of payload match condition."""

    return {"key": key, "match": {"any": values}}


def public_filter(
    *,
    generation_id: str | None = None,
    visible: bool | None = True,
) -> dict[str, Any]:
    """Return the mandatory lifecycle/query boundary for public points."""

    must = [match_value("scope", PUBLIC_SCOPE)]
    if generation_id is not None:
        if not generation_id:
            raise ValueError("public generation_id cannot be blank")
        must.append(match_value("index_generation_id", generation_id))
    if visible is not None:
        must.append(match_value("visible", visible))
    return {"must": must}
