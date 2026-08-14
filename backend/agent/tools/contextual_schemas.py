"""Register schemas for tools whose handlers require trusted turn context."""

from __future__ import annotations

import json
from pathlib import Path

from backend.agent.tools.tools import tr

CONTEXTUAL_TOOL_NAMES = frozenset(
    {
        "load_skill", "save_core_memory", "propose_core_memory",
        "search_core_memories",
        "get_core_memories", "delete_core_memory", "recommend_practice",
        "get_mastery_report",
        "get_mastery_level", "get_weak_prerequisites", "get_review_timing",
        "record_answer", "record_learning_evidence",
        "get_learning_evidence_summary", "parse_pdf_attachment",
        "parse_word_attachment", "parse_presentation_attachment",
        "parse_spreadsheet_attachment", "parse_image_attachment",
    }
)


def register_contextual_schemas() -> None:
    schemas = json.loads(
        (Path(__file__).with_name("tool_schemas.json")).read_text(encoding="utf-8")
    )
    for schema in schemas:
        name = schema.get("function", {}).get("name")
        if name not in CONTEXTUAL_TOOL_NAMES:
            continue

        def unavailable(**_arguments):
            raise RuntimeError("contextual tool requires BoundToolExecutor")

        tr.register(schema)(unavailable)
