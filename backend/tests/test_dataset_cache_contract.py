"""Regression tests for generated Skill and system-prompt cache freshness."""

from __future__ import annotations

import json
from pathlib import Path

from backend.scripts.dataset.esa.cache_contract import (
    prompt_source_fingerprint,
    skill_source_hashes,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPOSITORY_ROOT / "backend/scripts/dataset/data/cache"


def test_system_prompt_cache_matches_current_production_sources():
    payload = json.loads(
        (CACHE_ROOT / "system_prompts.json").read_text(encoding="utf-8")
    )
    assert payload["_meta"]["prompt_source_fingerprint"] == (
        prompt_source_fingerprint(REPOSITORY_ROOT)
    )


def test_skill_body_cache_matches_recursive_skill_sources():
    payload = json.loads(
        (CACHE_ROOT / "skills_bodies.json").read_text(encoding="utf-8")
    )
    assert payload["_meta"]["source_sha256"] == skill_source_hashes(
        REPOSITORY_ROOT
    )
