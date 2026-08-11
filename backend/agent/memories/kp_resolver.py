"""Resolve natural-language mentions to concrete knowledge graph IDs."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from backend.agent.memories.paths import KNOWLEDGE_ALIASES_YAML


@dataclass(frozen=True, slots=True)
class KnowledgePointMatch:
    kp_id: str
    name: str
    course: str
    score: float
    matched_by: str
    matched_text: str


class KnowledgePointResolver:
    """Deterministically resolve a message to at most a few KG points."""

    MAX_RESULTS = 3
    MIN_SCORE = 0.85

    def __init__(self, kg_store):
        self._kg_store = kg_store
        self._aliases = self._load_aliases()

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\s+", "", text)
        return re.sub(r"[，。！？、；：,.!?;:'\"`()（）\[\]{}]", "", text)

    @staticmethod
    def _load_aliases() -> dict[str, list[str]]:
        if not KNOWLEDGE_ALIASES_YAML.exists():
            return {}

        data = yaml.safe_load(
            KNOWLEDGE_ALIASES_YAML.read_text(encoding="utf-8")
        ) or {}
        raw = data.get("aliases", {})
        if not isinstance(raw, dict):
            return {}

        result: dict[str, list[str]] = {}
        for kp_id, aliases in raw.items():
            if not isinstance(aliases, list):
                continue
            result[str(kp_id)] = [
                str(alias) for alias in aliases if str(alias).strip()
            ]
        return result

    def resolve(
        self,
        text: str,
        *,
        limit: int = MAX_RESULTS,
    ) -> list[KnowledgePointMatch]:
        original = text or ""
        normalized = self._normalize(original)
        if not normalized:
            return []

        results: list[KnowledgePointMatch] = []
        for point in self._kg_store.list_all():
            kp_id = str(point["id"])
            name = str(point["name"])
            candidates = [("id", kp_id), ("name", name)]
            candidates.extend(
                ("alias", alias) for alias in self._aliases.get(kp_id, [])
            )

            best_score = 0.0
            best_type = ""
            best_text = ""
            for candidate_type, candidate in candidates:
                candidate_normalized = self._normalize(candidate)
                if not candidate_normalized:
                    continue

                score = 0.0
                if len(candidate_normalized) == 1:
                    if normalized == candidate_normalized:
                        score = 1.0
                elif normalized == candidate_normalized:
                    score = 1.0
                elif candidate_normalized in normalized:
                    score = 0.95 if candidate_type == "alias" else 0.90

                if candidate.isascii():
                    # ASCII aliases, especially short acronyms such as DP, must
                    # never inherit the generic substring score (for example,
                    # the adjacent letters in "endpoint").
                    score = 0.0
                    if re.search(
                        rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])",
                        original,
                        flags=re.IGNORECASE,
                    ):
                        score = (
                            1.0
                            if original.strip().casefold() == candidate.casefold()
                            else 0.96
                        )

                if score > best_score:
                    best_score = score
                    best_type = candidate_type
                    best_text = candidate

            if best_score >= self.MIN_SCORE:
                results.append(
                    KnowledgePointMatch(
                        kp_id=kp_id,
                        name=name,
                        course=str(point["course"]),
                        score=best_score,
                        matched_by=best_type,
                        matched_text=best_text,
                    )
                )

        results.sort(
            key=lambda item: (item.score, len(item.matched_text)),
            reverse=True,
        )
        return results[: max(1, limit)]
