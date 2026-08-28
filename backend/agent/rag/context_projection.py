"""Deterministic post-retrieval projection of the model-facing result channel."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.agent.rag.context_routing import (
    MetadataProfile,
    RetrievalProjectionContext,
)
from backend.agent.rag.retrieval.context import estimate_tokens
from backend.agent.rag.unified_retrieval import (
    CONTRACT_VERSION as UNIFIED_CONTRACT_VERSION,
)
from backend.core.utils.models import ToolExecutionResult


logger = logging.getLogger(__name__)
DEFAULT_MODEL_TOKEN_BUDGET = 2_048
MODEL_CONTEXT_CONTRACT_VERSION = "retrieve_knowledge.model_context.v1"


@dataclass(frozen=True, slots=True)
class CanonicalRetrievalItem:
    """Schema-tolerant fields required to build one model view."""

    content: str
    chunk_id: str
    scope: str | None
    source_ref: str
    source: str | None
    author: str | None
    document_id: str | None
    section: str | None
    page: int | None
    location: Any
    preview_url: str | None
    quote_eligible: bool
    citation_mode: str
    raw_model: Mapping[str, Any]
    raw_display: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectedRetrievalContext:
    """Canonical projection prior to choosing its model representation."""

    source_contract_version: str
    profile: MetadataProfile
    results: tuple[Mapping[str, Any], ...]
    ref_registry: Mapping[str, Mapping[str, Any]]
    missing_metadata: tuple[str, ...]
    retrieval_metadata: Mapping[str, Any]


class CanonicalMetadataAdapter:
    """Adapt the current unified model/display projections without DocIR coupling."""

    @staticmethod
    def _items(value: Any) -> list[Mapping[str, Any]]:
        if not isinstance(value, Mapping):
            return []
        results = value.get("results", [])
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            return []
        return [item for item in results if isinstance(item, Mapping)]

    def adapt(self, result: ToolExecutionResult) -> tuple[CanonicalRetrievalItem, ...]:
        model_items = self._items(result.model_content)
        display_items = self._items(result.display_content)
        display_by_key: dict[tuple[str | None, str], Mapping[str, Any]] = {}
        display_by_chunk: dict[str, Mapping[str, Any]] = {}
        for item in display_items:
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            scope = str(item["scope"]) if item.get("scope") is not None else None
            display_by_key[(scope, chunk_id)] = item
            display_by_chunk.setdefault(chunk_id, item)

        adapted: list[CanonicalRetrievalItem] = []
        for index, item in enumerate(model_items, start=1):
            chunk_id = str(item.get("chunk_id") or f"result-{index}")
            scope = str(item["scope"]) if item.get("scope") is not None else None
            display = display_by_key.get((scope, chunk_id), display_by_chunk.get(chunk_id, {}))
            source = display.get("source", display.get("document_name"))
            section = display.get("section")
            if isinstance(section, (list, tuple)):
                section = " / ".join(str(value) for value in section)
            page = display.get("page")
            if isinstance(page, bool) or not isinstance(page, int):
                page = None
            quote_eligible = bool(
                item.get("quote_eligible", display.get("quote_eligible", False))
            )
            adapted.append(
                CanonicalRetrievalItem(
                    content=str(item.get("content") or ""),
                    chunk_id=chunk_id,
                    scope=scope,
                    source_ref=str(
                        item.get("source_ref")
                        or display.get("source_ref")
                        or chunk_id
                    ),
                    source=str(source) if source is not None else None,
                    author=(
                        str(display["author"])
                        if display.get("author") is not None
                        else None
                    ),
                    document_id=(
                        str(display["document_id"])
                        if display.get("document_id") is not None
                        else None
                    ),
                    section=str(section) if section is not None else None,
                    page=page,
                    location=display.get("location"),
                    preview_url=(
                        str(display["preview_url"])
                        if display.get("preview_url") is not None
                        else None
                    ),
                    quote_eligible=quote_eligible,
                    citation_mode=str(
                        item.get("citation_mode")
                        or (
                            "verbatim_allowed"
                            if quote_eligible
                            else "paraphrase_only_unverified"
                        )
                    ),
                    raw_model=dict(item),
                    raw_display=dict(display),
                )
            )
        return tuple(adapted)


class MetadataProjector:
    """Pure profile-based field selection over a canonical retrieval result."""

    def __init__(self, adapter: CanonicalMetadataAdapter | None = None) -> None:
        self.adapter = adapter or CanonicalMetadataAdapter()

    def project(
        self,
        result: ToolExecutionResult,
        profile: MetadataProfile,
    ) -> ProjectedRetrievalContext:
        source_contract_version = ""
        if isinstance(result.model_content, Mapping):
            raw_version = result.model_content.get("contract_version")
            if isinstance(raw_version, str):
                source_contract_version = raw_version
        items = self.adapter.adapt(result)
        missing: list[str] = []
        projected: list[Mapping[str, Any]] = []
        registry: dict[str, Mapping[str, Any]] = {}

        for index, item in enumerate(items, start=1):
            ref = f"C{index}"
            view: dict[str, Any] = {
                "ref": ref,
                "content": item.content,
                # This field is required for the existing citation safety policy.
                "citation_mode": item.citation_mode,
            }
            if profile in {
                MetadataProfile.SOURCE,
                MetadataProfile.LOCATION,
            }:
                view["source"] = item.source
                if item.source is None:
                    missing.append(f"{ref}.source")
                if item.author is not None:
                    view["author"] = item.author
            if profile is MetadataProfile.LOCATION:
                view.update({"section": item.section, "page": item.page})
                # A page number is sufficient for model answering. Preserve the
                # potentially large bbox/geometry only in display/audit; expose
                # a locator to the model only when no page number is available.
                if item.page is None:
                    view["location"] = item.location
                if item.section is None:
                    missing.append(f"{ref}.section")
                if item.page is None:
                    missing.append(f"{ref}.page")
                    if item.location is None:
                        missing.append(f"{ref}.location")
            if profile is MetadataProfile.FULL:
                metadata = dict(item.raw_model)
                metadata.pop("content", None)
                metadata.update(item.raw_display)
                view["metadata"] = metadata
            projected.append(view)
            registry[ref] = {
                "source_ref": item.source_ref,
                "chunk_id": item.chunk_id,
                "scope": item.scope,
                "document_id": item.document_id,
                "source": item.source,
                "section": item.section,
                "page": item.page,
                "location": item.location,
                "preview_url": item.preview_url,
                "quote_eligible": item.quote_eligible,
                "citation_mode": item.citation_mode,
            }

        retrieval_metadata: dict[str, Any] = {}
        if profile is MetadataProfile.FULL and isinstance(result.model_content, Mapping):
            retrieval_metadata = dict(result.model_content)
            retrieval_metadata.pop("results", None)
            retrieval_metadata.pop("contract_version", None)
        return ProjectedRetrievalContext(
            source_contract_version=source_contract_version,
            profile=profile,
            results=tuple(projected),
            ref_registry=registry,
            missing_metadata=tuple(dict.fromkeys(missing)),
            retrieval_metadata=retrieval_metadata,
        )


class ContextSerializer:
    """Choose the stable model representation for a projected result."""

    mode = "compact_json.v1"

    def serialize(self, projected: ProjectedRetrievalContext) -> dict[str, Any]:
        if projected.source_contract_version != UNIFIED_CONTRACT_VERSION:
            raise ValueError("unsupported retrieval source contract")
        payload: dict[str, Any] = {
            "contract_version": MODEL_CONTEXT_CONTRACT_VERSION,
            "source_contract_version": projected.source_contract_version,
            "profile": projected.profile.value,
            "results": [dict(item) for item in projected.results],
        }
        if projected.retrieval_metadata:
            payload["retrieval_metadata"] = dict(projected.retrieval_metadata)
        return payload

    def serialize_compact_text(self, projected: ProjectedRetrievalContext) -> str:
        """Benchmark alternative; production keeps structured compact JSON."""

        blocks: list[str] = []
        for item in projected.results:
            lines = [f"[{item['ref']}]", str(item.get("content", ""))]
            metadata = [
                f"{key}={item[key]}"
                for key in ("source", "author", "section", "page", "location", "citation_mode")
                if key in item
            ]
            if metadata:
                lines.append("; ".join(metadata))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


def _serialized_tokens(
    value: Any,
    counter: Callable[[str], int] | None,
) -> tuple[int, str]:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if counter is not None:
        try:
            return counter(serialized), "agent_tokenizer"
        except Exception:  # noqa: BLE001 - observability must not break retrieval
            logger.exception("metadata projection token counter failed; using fallback")
    return estimate_tokens(serialized), "fallback"


def projection_fallback_result(
    result: ToolExecutionResult,
    context: RetrievalProjectionContext,
    reason: str,
) -> ToolExecutionResult:
    """Keep the old model/display result while recording a safe degradation."""

    if not isinstance(result.audit_metadata, Mapping):
        return result
    audit = dict(result.audit_metadata)
    source_contract_version = None
    if isinstance(result.model_content, Mapping):
        raw_version = result.model_content.get("contract_version")
        if isinstance(raw_version, str):
            source_contract_version = raw_version
    projection_audit: dict[str, Any] = {
        "enabled": True,
        "status": "fallback",
        "fallback_reason": reason,
        "model_contract_version": MODEL_CONTEXT_CONTRACT_VERSION,
        "source_contract_version": source_contract_version,
        "query": context.route_input.current_user_message,
        "recent_user_messages": list(context.route_input.recent_user_messages),
    }
    if context.decision is not None:
        projection_audit.update(
            {
                "profile": context.decision.profile.value,
                "predicted_profile": context.decision.profile.value,
                "corrected_profile": None,
                "router_type": context.decision.router_type,
                "router_version": context.decision.router_version,
                "reason_code": context.decision.reason_code,
            }
        )
    audit["metadata_projection"] = projection_audit
    return ToolExecutionResult(result.model_content, result.display_content, audit)


class MetadataProjectionMiddleware:
    """Apply projection to model_content and preserve the other two channels."""

    def __init__(
        self,
        projector: MetadataProjector | None = None,
        serializer: ContextSerializer | None = None,
    ) -> None:
        self.projector = projector or MetadataProjector()
        self.serializer = serializer or ContextSerializer()

    def apply(
        self,
        result: ToolExecutionResult,
        context: RetrievalProjectionContext,
        *,
        token_counter: Callable[[str], int] | None = None,
    ) -> ToolExecutionResult:
        if not context.enabled:
            return result
        if context.decision is None:
            return projection_fallback_result(
                result,
                context,
                context.fallback_reason or "route_decision_missing",
            )
        if not isinstance(result.audit_metadata, Mapping):
            return result

        source_contract_version = None
        if isinstance(result.model_content, Mapping):
            raw_version = result.model_content.get("contract_version")
            if isinstance(raw_version, str):
                source_contract_version = raw_version
        if source_contract_version is None:
            return projection_fallback_result(
                result,
                context,
                "source_contract_version_missing",
            )
        if source_contract_version != UNIFIED_CONTRACT_VERSION:
            return projection_fallback_result(
                result,
                context,
                f"unsupported_source_contract_version:{source_contract_version}",
            )

        projected = self.projector.project(result, context.decision.profile)
        model_content = self.serializer.serialize(projected)
        before_tokens, counter_name = _serialized_tokens(
            result.model_content,
            token_counter,
        )
        after_tokens, after_counter_name = _serialized_tokens(
            model_content,
            token_counter if counter_name == "agent_tokenizer" else None,
        )
        if after_counter_name != counter_name:
            before_tokens, counter_name = _serialized_tokens(result.model_content, None)
        saved_tokens = before_tokens - after_tokens
        limit = DEFAULT_MODEL_TOKEN_BUDGET
        if isinstance(result.model_content, Mapping):
            budget = result.model_content.get("budget")
            if isinstance(budget, Mapping):
                configured_limit = budget.get("limit")
                if (
                    isinstance(configured_limit, int)
                    and not isinstance(configured_limit, bool)
                    and configured_limit > 0
                ):
                    limit = configured_limit
        if after_tokens > limit:
            fallback = projection_fallback_result(
                result,
                context,
                "projected_model_budget_exceeded",
            )
            if isinstance(fallback.audit_metadata, Mapping):
                audit = dict(fallback.audit_metadata)
                metadata = dict(audit["metadata_projection"])
                metadata.update(
                    {
                        "before_tokens": before_tokens,
                        "candidate_after_tokens": after_tokens,
                        "limit": limit,
                        "counter": counter_name,
                        "serializer": self.serializer.mode,
                        "missing_metadata": list(projected.missing_metadata),
                        "ref_registry": {
                            key: dict(value)
                            for key, value in projected.ref_registry.items()
                        },
                    }
                )
                audit["metadata_projection"] = metadata
                return ToolExecutionResult(
                    fallback.model_content,
                    fallback.display_content,
                    audit,
                )
            return fallback
        audit = dict(result.audit_metadata)
        audit["metadata_projection"] = {
            "enabled": True,
            "status": "applied",
            "model_contract_version": MODEL_CONTEXT_CONTRACT_VERSION,
            "source_contract_version": source_contract_version,
            "profile": context.decision.profile.value,
            "predicted_profile": context.decision.profile.value,
            "corrected_profile": None,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "saved_tokens": saved_tokens,
            "saving_ratio": (
                round(saved_tokens / before_tokens, 6) if before_tokens else 0.0
            ),
            "counter": counter_name,
            "serializer": self.serializer.mode,
            "router_type": context.decision.router_type,
            "router_version": context.decision.router_version,
            "reason_code": context.decision.reason_code,
            "matched_rule": context.decision.matched_rule,
            "confidence": context.decision.confidence,
            "query": context.route_input.current_user_message,
            "recent_user_messages": list(
                context.route_input.recent_user_messages
            ),
            "missing_metadata": list(projected.missing_metadata),
            "ref_registry": {
                key: dict(value) for key, value in projected.ref_registry.items()
            },
        }
        logger.info(
            "metadata projection applied profile=%s before_tokens=%s after_tokens=%s "
            "saved_tokens=%s router=%s serializer=%s",
            context.decision.profile.value,
            before_tokens,
            after_tokens,
            saved_tokens,
            context.decision.router_type,
            self.serializer.mode,
        )
        return ToolExecutionResult(model_content, result.display_content, audit)
