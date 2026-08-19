# backend/agent/memories/profile_builder.py

"""结构化用户画像构建器。

ProfileBuilder 只组装结构化画像，不直接读取 CoreMemory。长期原始记忆只能通过
memory tools 按需读取；这里允许读取 ProfileStore 中已经结构化、可审核、未过期的
画像维度。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.agent.memories.memory_models import (
    ProfileField,
    ProfileOrigin,
    ProfileQuery,
    ProfileSnapshot,
)

logger = logging.getLogger(__name__)


@dataclass
class ProfileMetrics:
    """封装 `ProfileMetrics` 的状态与行为。"""
    build_total: int = 0
    build_latency_ms_sum: float = 0.0
    build_latency_ms_max: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    suppress_count: int = 0
    restore_count: int = 0
    store_error_count: int = 0
    token_used_sum: int = 0
    token_used_max: int = 0

    @property
    def cache_hit_ratio(self) -> float:
        """处理 `cache_hit_ratio` 相关逻辑。"""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0

    @property
    def avg_build_latency_ms(self) -> float:
        """处理 `avg_build_latency_ms` 相关逻辑。"""
        return self.build_latency_ms_sum / self.build_total if self.build_total else 0.0

    def snapshot(self) -> dict:
        """处理 `snapshot` 相关逻辑。"""
        return {
            "build_total": self.build_total,
            "avg_build_latency_ms": round(self.avg_build_latency_ms, 2),
            "max_build_latency_ms": round(self.build_latency_ms_max, 2),
            "cache_hit_ratio": round(self.cache_hit_ratio, 4),
            "suppress_count": self.suppress_count,
            "restore_count": self.restore_count,
            "store_error_count": self.store_error_count,
            "token_used_sum": self.token_used_sum,
            "token_used_max": self.token_used_max,
        }

    def to_prometheus(self) -> str:
        """转换 `prometheus` 相关数据。"""
        lines = [
            "# HELP profile_build_total Total number of profile builds",
            "# TYPE profile_build_total counter",
            f"profile_build_total {self.build_total}",
            "# HELP profile_build_latency_ms_avg Average build latency in ms",
            "# TYPE profile_build_latency_ms_avg gauge",
            f"profile_build_latency_ms_avg {self.avg_build_latency_ms:.2f}",
            "# HELP profile_build_latency_ms_max Max build latency in ms",
            "# TYPE profile_build_latency_ms_max gauge",
            f"profile_build_latency_ms_max {self.build_latency_ms_max:.2f}",
            "# HELP profile_cache_hit_ratio Cache hit ratio (0.0-1.0)",
            "# TYPE profile_cache_hit_ratio gauge",
            f"profile_cache_hit_ratio {self.cache_hit_ratio:.4f}",
            "# HELP profile_cache_hits Cache hit count",
            "# TYPE profile_cache_hits counter",
            f"profile_cache_hits {self.cache_hits}",
            "# HELP profile_cache_misses Cache miss count",
            "# TYPE profile_cache_misses counter",
            f"profile_cache_misses {self.cache_misses}",
            "# HELP profile_suppress_total Total suppress operations",
            "# TYPE profile_suppress_total counter",
            f"profile_suppress_total {self.suppress_count}",
            "# HELP profile_restore_total Total restore operations",
            "# TYPE profile_restore_total counter",
            f"profile_restore_total {self.restore_count}",
            "# HELP profile_store_errors Total store errors",
            "# TYPE profile_store_errors counter",
            f"profile_store_errors {self.store_error_count}",
            "# HELP profile_token_used_sum Total prompt-profile characters emitted",
            "# TYPE profile_token_used_sum counter",
            f"profile_token_used_sum {self.token_used_sum}",
            "# HELP profile_token_used_max Max prompt-profile characters emitted",
            "# TYPE profile_token_used_max gauge",
            f"profile_token_used_max {self.token_used_max}",
        ]
        return "\n".join(lines) + "\n"


class ProfileBuilder:
    """封装 `ProfileBuilder` 的状态与行为。"""
    CACHE_TTL_SECONDS = 60

    def __init__(
        self,
        user_store,
        mastery_store,
        kg_store,
        profile_store,
        evidence_store,
    ):
        """初始化 `ProfileBuilder` 实例。"""
        self._user_store = user_store
        self._mastery_store = mastery_store
        self._kg_store = kg_store
        self._profile_store = profile_store
        self._evidence_store = evidence_store
        self._version_counter = 0
        self._cache: dict[str, tuple[str, ProfileSnapshot, datetime]] = {}
        self._metrics = ProfileMetrics()

    @property
    def metrics(self) -> ProfileMetrics:
        """处理 `metrics` 相关逻辑。"""
        return self._metrics

    def get_metrics_snapshot(self) -> dict:
        """获取 `metrics snapshot` 相关数据。"""
        return self._metrics.snapshot()

    def get_metrics_prometheus(self) -> str:
        """获取 `metrics prometheus` 相关数据。"""
        return self._metrics.to_prometheus()

    def invalidate(self, user_id: str) -> None:
        """处理 `invalidate` 相关逻辑。"""
        self._cache.pop(user_id, None)

    def build(self, query: ProfileQuery) -> ProfileSnapshot:
        """构建 `build` 相关数据。

        Args:
            query: ProfileQuery => 查询文本。

        Returns:
            ProfileSnapshot => 处理结果。
        """
        start_ts = time.monotonic()
        user = self._user_store.get_by_id(query.user_id)
        if user is None:
            return self._empty_snapshot(query.user_id)
        if not getattr(user, "profile_enabled", True):
            return self._empty_snapshot(query.user_id)

        settings = self._user_store.get_memory_settings(query.user_id)
        if settings is None:
            settings = _DefaultSettings()

        input_hash = self._compute_hash(user, query, settings)
        now = datetime.now()
        cached = self._cache.get(query.user_id)
        if cached is not None and cached[0] == input_hash and cached[2] > now:
            self._metrics.cache_hits += 1
            return cached[1]

        self._metrics.cache_misses += 1
        try:
            profile_version = self._profile_store.get_next_profile_version(user.id)
        except Exception:
            logger.warning(
                "ProfileStore 版本持久化失败，回退进程内版本号 user=%s",
                user.id,
                exc_info=True,
            )
            self._metrics.store_error_count += 1
            self._version_counter += 1
            profile_version = self._version_counter

        explicit_context = self._build_explicit_context(user)
        response_preferences = self._build_response_preferences(user, query)
        relevant_learning_state = self._build_relevant_learning_state(user, query, settings)
        inferred_patterns = self._build_inferred_patterns(user, settings)

        sections = (
            explicit_context,
            response_preferences,
            relevant_learning_state,
            inferred_patterns,
        )
        source_memory_ids: list[str] = []
        seen_source_ids: set[str] = set()
        for section in sections:
            for item in section:
                for source_id in item.source_memory_ids:
                    source_id = str(source_id)
                    if source_id not in seen_source_ids:
                        seen_source_ids.add(source_id)
                        source_memory_ids.append(source_id)

        snapshot = ProfileSnapshot(
            user_id=user.id,
            profile_version=profile_version,
            explicit_context=explicit_context,
            response_preferences=response_preferences,
            active_goals=[],
            active_projects=[],
            relevant_learning_state=relevant_learning_state,
            relevant_constraints=[],
            inferred_patterns=inferred_patterns,
            source_memory_ids=source_memory_ids,
            generated_at=now,
        )

        self._cache[query.user_id] = (
            input_hash,
            snapshot,
            now + timedelta(seconds=self.CACHE_TTL_SECONDS),
        )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        profile_prompt = snapshot.to_prompt_json()
        self._metrics.build_total += 1
        self._metrics.build_latency_ms_sum += elapsed_ms
        self._metrics.build_latency_ms_max = max(self._metrics.build_latency_ms_max, elapsed_ms)
        self._metrics.token_used_sum += len(profile_prompt)
        self._metrics.token_used_max = max(self._metrics.token_used_max, len(profile_prompt))
        return snapshot

    def _build_explicit_context(self, user) -> list[ProfileField]:
        """构建 `explicit context` 相关数据。"""
        fields = [
            ProfileField("major", user.major, ProfileOrigin.EXPLICIT_SETTING, 1.0),
        ]
        if getattr(user, "grade", ""):
            fields.append(
                ProfileField("grade", user.grade, ProfileOrigin.EXPLICIT_SETTING, 1.0)
            )
        fields.extend(
            [
                ProfileField(
                    "current_week",
                    user.current_week,
                    ProfileOrigin.EXPLICIT_SETTING,
                    1.0,
                ),
                ProfileField(
                    "total_weeks",
                    user.total_weeks,
                    ProfileOrigin.EXPLICIT_SETTING,
                    1.0,
                ),
            ]
        )
        return fields

    def _build_response_preferences(self, user, query: ProfileQuery) -> list[ProfileField]:
        """构建 `response preferences` 相关数据。"""
        preferred_style = query.group_style or user.preferred_style
        preferred_tone = query.group_tone or user.preferred_tone
        merged_instruction = user.custom_instruction or ""
        if query.group_custom_instruction:
            merged_instruction = (
                f"{merged_instruction}\n{query.group_custom_instruction}"
                if merged_instruction
                else query.group_custom_instruction
            )
        return [
            ProfileField(
                "preferred_style",
                preferred_style,
                ProfileOrigin.EXPLICIT_SETTING,
                1.0,
            ),
            ProfileField(
                "preferred_tone",
                preferred_tone,
                ProfileOrigin.EXPLICIT_SETTING,
                1.0,
            ),
            ProfileField(
                "custom_instruction",
                merged_instruction,
                ProfileOrigin.EXPLICIT_SETTING,
                1.0,
            ),
        ]

    def _build_relevant_learning_state(
        self,
        user,
        query: ProfileQuery,
        settings,
    ) -> list[ProfileField]:
        """构建 `relevant learning state` 相关数据。"""
        if not getattr(settings, "learning_profile_enabled", True):
            return []

        kp_ids = query.resolved_kp_ids[:3]
        if not kp_ids:
            return []

        fields: list[ProfileField] = []
        for kp_id in kp_ids:
            point = self._kg_store.get_point(kp_id)
            if point is None:
                continue
            mastery = self._mastery_store.get(user.username, kp_id)
            has_mastery_record = mastery is not None
            mastery_level = (
                float(mastery["mastery_level"])
                if mastery is not None
                else None
            )
            practice_count = (
                int(mastery["practice_count"]) if mastery is not None else 0
            )

            evidence = self._evidence_store.get_summary(
                user.username,
                kp_id=kp_id,
                limit=20,
            )
            prerequisites = self._kg_store.get_prerequisites(kp_id, max_depth=3)
            prerequisite_items = []
            for prereq in prerequisites:
                if prereq["kp_id"] == kp_id:
                    continue
                prereq_mastery = self._mastery_store.get(
                    user.username,
                    prereq["kp_id"],
                )

                if prereq_mastery is None:
                    status = "unknown"
                    prereq_level = None
                else:
                    prereq_level = float(prereq_mastery["mastery_level"])
                    status = "weak" if prereq_level < 50.0 else "known"

                prerequisite_items.append(
                    {
                        "kp_id": prereq["kp_id"],
                        "name": prereq["name"],
                        "course": prereq["course"],
                        "depth": prereq["depth"],
                        "mastery_level": prereq_level,
                        "status": status,
                    }
                )

            fields.append(
                ProfileField(
                    field=f"knowledge.{kp_id}",
                    value={
                        "kp_id": kp_id,
                        "name": point["name"],
                        "course": point["course"],
                        "mastery": {
                            "has_record": has_mastery_record,
                            "level": mastery_level,
                            "status": (
                                mastery.get("status", "learning")
                                if mastery is not None
                                else "unseen"
                            ),
                            "retention": (
                                mastery.get("retention")
                                if mastery is not None
                                else None
                            ),
                            "evidence_confidence": (
                                mastery.get("evidence_confidence", 0.0)
                                if mastery is not None
                                else 0.0
                            ),
                            "needs_review": (
                                bool(mastery.get("needs_review", False))
                                if mastery is not None
                                else False
                            ),
                            "practice_count": practice_count,
                        },
                        "evidence": {
                            "count": evidence["evidence_count"],
                            "correct_rate": evidence["correct_rate"],
                            "avg_hint_level": evidence["avg_hint_level"],
                            "independent_rate": evidence["independent_rate"],
                            "avg_explanation_score": evidence[
                                "avg_explanation_score"
                            ],
                            "avg_transfer_score": evidence["avg_transfer_score"],
                            "recent_misconceptions": evidence[
                                "recent_misconceptions"
                            ],
                        },
                        "prerequisites": prerequisite_items,
                        "weak_prerequisites": [
                            item["name"]
                            for item in prerequisite_items
                            if item["status"] == "weak"
                        ],
                    },
                    origin=ProfileOrigin.DERIVED_LEARNING_STATE,
                    confidence=0.95 if has_mastery_record else 0.65,
                )
            )
        return fields

    def _build_inferred_patterns(self, user, settings) -> list[ProfileField]:
        """从 ProfileStore 读取结构化画像，不读取 raw CoreMemory。

        ProfileStore 是结构化画像的审核边界。这里只读取 status=active、未过期且来源为
        inferred_pattern / confirmed_memory / explicit_memory 的维度。
        """
        if not getattr(settings, "inferred_profile_enabled", True):
            return []

        try:
            rows = self._profile_store.list_dimensions(
                user.id,
                status_filter="active",
            )
        except Exception:
            logger.exception(
                "ProfileStore 不可用 fail-closed: 跳过结构化画像 user=%s",
                user.id,
            )
            return []

        allowed_origins = {
            ProfileOrigin.INFERRED_PATTERN.value,
            ProfileOrigin.CONFIRMED_MEMORY.value,
            ProfileOrigin.EXPLICIT_MEMORY.value,
        }
        fields: list[ProfileField] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            field_key = str(row.get("field_key") or "").strip()
            origin_value = str(row.get("origin") or "").strip()
            if not field_key or origin_value not in allowed_origins:
                continue
            try:
                origin = ProfileOrigin(origin_value)
            except ValueError:
                continue
            try:
                confidence = max(0.0, min(1.0, float(row.get("confidence", 0.7))))
            except (TypeError, ValueError):
                confidence = 0.7

            last_confirmed_at = None
            if row.get("last_confirmed_at"):
                try:
                    last_confirmed_at = datetime.fromisoformat(
                        str(row["last_confirmed_at"])
                    )
                except ValueError:
                    pass

            fields.append(
                ProfileField(
                    field=field_key,
                    value=row.get("value"),
                    origin=origin,
                    confidence=confidence,
                    source_memory_ids=[
                        str(item) for item in (row.get("source_memory_ids") or [])
                    ],
                    last_confirmed_at=last_confirmed_at,
                )
            )
        return fields

    @staticmethod
    def _compact_recent_messages(messages: list[dict] | None) -> list[dict[str, str]]:
        """处理 `_compact_recent_messages` 相关逻辑。"""
        compact: list[dict[str, str]] = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            compact.append(
                {
                    "role": str(message.get("role") or ""),
                    "name": str(message.get("name") or ""),
                    "content": content,
                }
            )
        return compact

    def _profile_store_revision(self, user_id: str) -> object:
        """把影响画像结果的 ProfileStore 版本信息纳入 cache key。"""
        try:
            rows = self._profile_store.list_dimensions(user_id)
        except Exception:
            return "unavailable"

        revision = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            revision.append(
                {
                    "field_key": row.get("field_key"),
                    "origin": row.get("origin"),
                    "status": row.get("status"),
                    "version": row.get("version"),
                    "updated_at": row.get("updated_at"),
                    "expires_at": row.get("expires_at"),
                }
            )
        revision.sort(key=lambda item: str(item.get("field_key") or ""))
        return revision

    def _compute_hash(self, user, query: ProfileQuery, settings) -> str:
        """对所有会影响 ProfileSnapshot 的显式输入做 canonical hash。

        旧实现遗漏 preferred_tone、grade、total_weeks、group overrides、recent_messages
        以及 active ProfileStore revision，可能在 60 秒 TTL 内返回错误旧画像。
        """
        payload = {
            "user": {
                "id": user.id,
                "username": user.username,
                "preferred_style": getattr(user, "preferred_style", ""),
                "preferred_tone": getattr(user, "preferred_tone", ""),
                "custom_instruction": getattr(user, "custom_instruction", ""),
                "major": getattr(user, "major", ""),
                "grade": getattr(user, "grade", ""),
                "current_week": getattr(user, "current_week", None),
                "total_weeks": getattr(user, "total_weeks", None),
                "profile_enabled": getattr(user, "profile_enabled", True),
            },
            "settings": {
                "learning_profile_enabled": getattr(
                    settings, "learning_profile_enabled", True
                ),
                "inferred_profile_enabled": getattr(
                    settings, "inferred_profile_enabled", True
                ),
            },
            "query": {
                "conversation_id": query.conversation_id,
                "group_id": query.group_id,
                "current_message": query.current_message,
                "recent_messages": self._compact_recent_messages(query.recent_messages),
                "resolved_kp_ids": list(query.resolved_kp_ids),
                "group_style": query.group_style,
                "group_tone": query.group_tone,
                "group_custom_instruction": query.group_custom_instruction,
            },
            "profile_store_revision": self._profile_store_revision(user.id),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _empty_snapshot(user_id: str) -> ProfileSnapshot:
        """处理 `_empty_snapshot` 相关逻辑。"""
        return ProfileSnapshot(user_id=user_id, profile_version=0)


class _DefaultSettings:
    """保存 `default settings` 配置。"""
    learning_profile_enabled = True
    inferred_profile_enabled = True
