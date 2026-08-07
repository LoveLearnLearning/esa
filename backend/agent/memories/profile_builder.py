# backend/agent/memories/profile_builder.py

"""
结构化用户画像构建器。

ProfileBuilder 取代旧的 build_user_profile_context() (扁平字符串)
基于多个数据源每轮重新组装出结构化的 ProfileSnapshot
每个 ProfileField 携带 origin/confidence/source 用于追溯可信度与覆盖优先级。

数据源:
    - UserRecord          => 显式上下文 + 响应偏好
    - MemorySettings      => 控制学习画像/推断画像开关
    - KnowledgeGraphStore => 命中当前问题的知识点
    - MasteryStore        => 命中知识点掌握度 + 薄弱前置 (按 username 索引)
    - CoreMemory          => 推断模式 (语言/偏好/目标/项目/环境/事实)
    - ProfileStore        => 被用户抑制的 field_key 不再回填到推断画像
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
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
    """画像系统可观测性指标 (P1-5)

    进程内计数器 可通过 get_metrics() 快照导出。
    生产环境可由 Prometheus 定期 scrape 或写入 SQLite metrics 表。
    """

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
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    @property
    def avg_build_latency_ms(self) -> float:
        return self.build_latency_ms_sum / self.build_total if self.build_total > 0 else 0.0

    def snapshot(self) -> dict:
        """返回当前指标的快照 dict"""
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
        """返回 Prometheus 文本展示格式 供 /internal/metrics/prometheus 端点

        多 Worker 部署时 各进程独立计数 Prometheus 通过 scrape 各 Worker 端口聚合。
        """
        lines: list[str] = [
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
            "# HELP profile_token_used_sum Total tokens used in prompts",
            "# TYPE profile_token_used_sum counter",
            f"profile_token_used_sum {self.token_used_sum}",
            "# HELP profile_token_used_max Max tokens used in single build",
            "# TYPE profile_token_used_max gauge",
            f"profile_token_used_max {self.token_used_max}",
        ]
        return "\n".join(lines) + "\n"


# CoreMemory.category 到画像 field_key 的映射
# 未在表中的类别回退到 "user_fact"
CATEGORY_MAP: dict[str, str] = {
    "language": "preferred_code_language",
    "preference": "answer_structure_preference",
    "goal": "active_goal",
    "project": "active_project",
    "environment": "environment_constraint",
    "general": "user_fact",
}


class ProfileBuilder:
    """
    结构化用户画像构建器。

    每轮基于 ProfileQuery 调用 build() 返回 ProfileSnapshot
    支持基于输入哈希的简单缓存 避免同一轮重复构建。
    """

    # 学习画像单轮最多注入条目数(命中知识点 + 前置) 控制单轮 token 预算
    LEARNING_STATE_MAX_ITEMS: int = 8
    # 缓存 TTL (秒) 多 Worker 场景下保证缓存最终一致性 (P1-6)
    CACHE_TTL_SECONDS: int = 60
    # 知识点名称最小匹配长度 避免"图"等单字误匹配 (P2-14)
    KP_MIN_MATCH_LENGTH: int = 2

    def __init__(self, user_store, mastery_store, kg_store, core_memory, profile_store):
        """
        Args:
            user_store: UserStore              => 用户表读写
            mastery_store: MasteryStore         => 掌握度数据层 (按 username 索引)
            kg_store: KnowledgeGraphStore       => 知识图谱数据层
            core_memory: CoreMemory             => 核心记忆 (按 username 索引)
            profile_store: ProfileStore         => 结构化画像持久化层
        """
        self._user_store = user_store
        self._mastery_store = mastery_store
        self._kg_store = kg_store
        self._core_memory = core_memory
        self._profile_store = profile_store
        # 简单的内存 profile_version 计数器 每次重建自增
        self._version_counter: int = 0
        # user_id -> (input_hash, snapshot, expires_at) 缓存 避免同一轮重复构建
        # TTL 保证多 Worker 场景下缓存最终一致 (P1-6)
        self._cache: dict[str, tuple[str, ProfileSnapshot, datetime]] = {}
        # 可观测性指标 (P1-5)
        self._metrics = ProfileMetrics()

    @property
    def metrics(self) -> ProfileMetrics:
        """暴露指标对象 供外部读取或 Prometheus scrape"""
        return self._metrics

    def get_metrics_snapshot(self) -> dict:
        """返回当前指标的快照 dict"""
        return self._metrics.snapshot()

    def get_metrics_prometheus(self) -> str:
        """返回 Prometheus 文本展示格式 供 /internal/metrics/prometheus 端点"""
        return self._metrics.to_prometheus()

    def invalidate(self, user_id: str) -> None:
        """失效指定用户的缓存快照

        在 suppress_dimension / restore_dimension / update_memory_settings 后调用
        确保下一轮 build() 重新构建 而非返回含已删除字段的旧快照。
        多 Worker 场景下各进程缓存独立 此方法仅失效当前进程
        _compute_hash 中的 suppressed_hash + CACHE_TTL 提供跨 Worker 的最终一致性兜底。
        """
        self._cache.pop(user_id, None)

    # ------------------------------------------------------------------ 主入口

    def build(self, query: ProfileQuery) -> ProfileSnapshot:
        """主入口 基于查询参数构建本轮 ProfileSnapshot

        流程:
            1. 取 UserRecord 不存在返回空快照
            2. 取 MemorySettings 不存在默认两个开关都 True
            3. 计算输入哈希 命中缓存(且未过期)直接返回
            4. 分别组装四个分节(explicit/preferences/learning/inferred)
            5. 汇总 source_memory_ids 写缓存(带 TTL)返回

        Args:
            query: ProfileQuery => 本轮画像查询参数

        Returns:
            ProfileSnapshot => 本轮结构化画像快照
        """
        start_ts = time.monotonic()

        user = self._user_store.get_by_id(query.user_id)
        if user is None:
            return self._empty_snapshot(query.user_id)

        settings = self._user_store.get_memory_settings(query.user_id)
        if settings is None:
            # 用户存在但无 settings 行 视为全开 与 UserStore 懒迁移前保持一致
            settings = _DefaultSettings()

        input_hash = self._compute_hash(user, query, settings)
        now = datetime.now()

        # TTL 缓存检查: 命中且未过期才返回 (P1-6)
        cached = self._cache.get(query.user_id)
        if cached is not None and cached[0] == input_hash and cached[2] > now:
            self._metrics.cache_hits += 1
            return cached[1]

        self._metrics.cache_misses += 1

        # 重建 版本号从 ProfileStore 持久化获取 重启不归零
        try:
            profile_version = self._profile_store.get_next_profile_version(user.id)
        except Exception:
            # ProfileStore 不可用时回退到内存计数器 不阻塞画像构建
            logger.warning("ProfileStore 版本持久化失败 回退内存计数器 user=%s", user.id)
            self._metrics.store_error_count += 1
            self._version_counter += 1
            profile_version = self._version_counter

        explicit_context = self._build_explicit_context(user)
        response_preferences = self._build_response_preferences(user, query)
        relevant_learning_state = self._build_relevant_learning_state(
            user,
            query,
            settings,
        )
        inferred_patterns = self._build_inferred_patterns(user, settings)

        # 汇总所有引用的记忆 ID
        source_memory_ids: list[str] = []
        for section in (
            explicit_context,
            response_preferences,
            relevant_learning_state,
            inferred_patterns,
        ):
            for profile_field in section:
                source_memory_ids.extend(profile_field.source_memory_ids)

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

        # 写缓存 带 TTL 过期时间 (P1-6)
        expires_at = now + timedelta(seconds=self.CACHE_TTL_SECONDS)
        self._cache[query.user_id] = (input_hash, snapshot, expires_at)

        # 记录指标 (P1-5)
        elapsed_ms = (time.monotonic() - start_ts) * 1000
        self._metrics.build_total += 1
        self._metrics.build_latency_ms_sum += elapsed_ms
        self._metrics.build_latency_ms_max = max(self._metrics.build_latency_ms_max, elapsed_ms)
        token_used = len(snapshot.to_prompt_json())
        self._metrics.token_used_sum += token_used
        self._metrics.token_used_max = max(self._metrics.token_used_max, token_used)

        return snapshot

    # ------------------------------------------------------------------ 显式上下文

    def _build_explicit_context(self, user) -> list[ProfileField]:
        """从 UserRecord 抽取显式档案字段

        全部 origin=EXPLICIT_SETTING confidence=1.0
        grade 为空字符串时跳过 避免注入无意义字段。

        Args:
            user: UserRecord => 用户数据对象

        Returns:
            list[ProfileField] => major/grade(非空时)/current_week/total_weeks
        """
        fields: list[ProfileField] = []

        fields.append(
            ProfileField(
                field="major",
                value=user.major,
                origin=ProfileOrigin.EXPLICIT_SETTING,
                confidence=1.0,
            )
        )

        # 年级为空字符串时跳过
        if getattr(user, "grade", ""):
            fields.append(
                ProfileField(
                    field="grade",
                    value=user.grade,
                    origin=ProfileOrigin.EXPLICIT_SETTING,
                    confidence=1.0,
                )
            )

        fields.append(
            ProfileField(
                field="current_week",
                value=user.current_week,
                origin=ProfileOrigin.EXPLICIT_SETTING,
                confidence=1.0,
            )
        )

        fields.append(
            ProfileField(
                field="total_weeks",
                value=user.total_weeks,
                origin=ProfileOrigin.EXPLICIT_SETTING,
                confidence=1.0,
            )
        )

        return fields

    # ------------------------------------------------------------------ 响应偏好

    def _build_response_preferences(
        self,
        user,
        query: ProfileQuery,
    ) -> list[ProfileField]:
        """组装响应偏好字段 preferred_style/preferred_tone/custom_instruction

        群组覆盖规则:
            - group_style/group_tone 非 None 时覆盖个人值 origin 仍记 EXPLICIT_SETTING
            - group_custom_instruction 非空时追加到个人 custom_instruction 之后

        覆盖只作用于本轮 snapshot 不修改 UserRecord 全局设置。

        Args:
            user: UserRecord        => 用户数据对象
            query: ProfileQuery     => 本轮查询参数 含群组覆盖

        Returns:
            list[ProfileField] => 风格/语气/自定义指令 全部 confidence=1.0
        """
        fields: list[ProfileField] = []

        # preferred_style: 群组覆盖优先 否则用个人值
        preferred_style = (
            query.group_style if query.group_style else user.preferred_style
        )
        fields.append(
            ProfileField(
                field="preferred_style",
                value=preferred_style,
                origin=ProfileOrigin.EXPLICIT_SETTING,
                confidence=1.0,
            )
        )

        # preferred_tone: 同上
        preferred_tone = query.group_tone if query.group_tone else user.preferred_tone
        fields.append(
            ProfileField(
                field="preferred_tone",
                value=preferred_tone,
                origin=ProfileOrigin.EXPLICIT_SETTING,
                confidence=1.0,
            )
        )

        # custom_instruction: 个人指令 + 群组指令(非空时追加)
        merged_instruction = user.custom_instruction or ""
        group_instruction = query.group_custom_instruction or ""
        if group_instruction:
            if merged_instruction:
                merged_instruction = f"{merged_instruction}\n{group_instruction}"
            else:
                merged_instruction = group_instruction

        fields.append(
            ProfileField(
                field="custom_instruction",
                value=merged_instruction,
                origin=ProfileOrigin.EXPLICIT_SETTING,
                confidence=1.0,
            )
        )

        return fields

    # ------------------------------------------------------------------ 学情状态

    def _build_relevant_learning_state(
        self,
        user,
        query: ProfileQuery,
        settings,
    ) -> list[ProfileField]:
        """组装与当前问题相关的知识点掌握度

        关键改进 (相对旧 build_user_profile_context):
            - 仅注入当前消息/最近消息命中的知识点 不再全局注入 Top3
            - 命中知识点 + 其薄弱前置 最多 LEARNING_STATE_MAX_ITEMS 条
            - learning_profile_enabled=False 时返回空列表
            - 无命中时返回空列表 (不回退到全局 Top3)

        Args:
            user: UserRecord         => 用户数据对象
            query: ProfileQuery      => 本轮查询参数 含 current_message/recent_messages
            settings: MemorySettings => 记忆开关

        Returns:
            list[ProfileField] => 命中知识点 + 薄弱前置 origin=DERIVED_LEARNING_STATE
        """
        if not getattr(settings, "learning_profile_enabled", True):
            return []

        # 命中的知识点 id 集合 顺序保留首次命中顺序
        matched_kp_ids: list[str] = []
        seen: set[str] = set()

        knowledge_points = self._kg_store.list_all()
        if not knowledge_points:
            return []

        # 合并待匹配文本: 当前消息 + 最近消息内容
        candidate_texts: list[str] = []
        if query.current_message:
            candidate_texts.append(query.current_message)
        for msg in query.recent_messages or []:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str) and content:
                candidate_texts.append(content)

        if not candidate_texts:
            return []

        # 大小写不敏感的子串匹配
        # P2-14: 要求知识点名称长度 >= KP_MIN_MATCH_LENGTH 避免"图"等单字误匹配
        # "图" 会命中所有含"图"的消息文本 导致图论/图遍历/图像处理等无关知识点被注入
        lowered_texts = [t.lower() for t in candidate_texts]
        for kp in knowledge_points:
            kp_name = kp.get("name") or ""
            if not kp_name or len(kp_name) < self.KP_MIN_MATCH_LENGTH:
                continue
            kp_name_lower = kp_name.lower()
            if any(kp_name_lower in text for text in lowered_texts):
                kp_id = kp.get("id") or ""
                if kp_id and kp_id not in seen:
                    seen.add(kp_id)
                    matched_kp_ids.append(kp_id)

        if not matched_kp_ids:
            # 无命中 回退为空 (旧的全局 Top3 注入已按 spec 移除)
            return []

        fields: list[ProfileField] = []

        for kp_id in matched_kp_ids:
            if len(fields) >= self.LEARNING_STATE_MAX_ITEMS:
                break

            mastery = self._mastery_store.get(user.username, kp_id)
            if mastery is not None:
                fields.append(
                    ProfileField(
                        field=kp_id,
                        value={
                            "mastery_level": mastery.get("mastery_level"),
                            "practice_count": mastery.get("practice_count"),
                        },
                        origin=ProfileOrigin.DERIVED_LEARNING_STATE,
                        confidence=0.9,
                    )
                )

            # 追加该知识点的薄弱前置 (无论 mastery 是否存在 都查前置)
            weak_prereqs = self._mastery_store.get_weak_prerequisites(
                user.username,
                kp_id,
                self._kg_store,
            )
            for prereq in weak_prereqs or []:
                if len(fields) >= self.LEARNING_STATE_MAX_ITEMS:
                    break
                prereq_kp_id = prereq.get("kp_id") or ""
                if not prereq_kp_id:
                    continue
                fields.append(
                    ProfileField(
                        field=prereq_kp_id,
                        value={
                            "name": prereq.get("name"),
                            "course": prereq.get("course"),
                            "depth": prereq.get("depth"),
                            "mastery_level": prereq.get("mastery_level"),
                        },
                        origin=ProfileOrigin.DERIVED_LEARNING_STATE,
                        confidence=0.9,
                    )
                )

        return fields

    # ------------------------------------------------------------------ 推断模式

    def _build_inferred_patterns(self, user, settings) -> list[ProfileField]:
        """由 CoreMemory 推断画像模式 并回写 ProfileStore

        流程:
            1. inferred_profile_enabled=False 时返回空
            2. 取 ProfileStore 中被 suppress 的 field_key 集合
            3. 取该用户全部 CoreMemory
            4. 按 category 映射到 field_key (默认 user_fact) 跳过被抑制的
            5. 构造 ProfileField (origin=INFERRED_PATTERN confidence=0.7)
            6. 同步 upsert_dimension 写回 ProfileStore

        安全策略 (fail-closed):
            当 ProfileStore 不可用时 不返回任何推断字段 避免被抑制的敏感字段泄漏。
            当 CoreMemory 不可用时 返回空 而非冒用旧数据。

        Args:
            user: UserRecord         => 用户数据对象
            settings: MemorySettings => 记忆开关

        Returns:
            list[ProfileField] => 未被抑制的推断模式
        """
        if not getattr(settings, "inferred_profile_enabled", True):
            return []

        # 1. 取被抑制的 field_key 集合
        # fail-closed: ProfileStore 不可用时返回空 避免被抑制字段泄漏
        suppressed: set[str] = set()
        try:
            suppressed_rows = self._profile_store.list_dimensions(
                user.id,
                status_filter="suppressed",
            )
        except Exception:
            logger.exception(
                "ProfileStore 不可用 fail-closed: 跳过全部推断字段 user=%s",
                user.id,
            )
            return []

        for row in suppressed_rows or []:
            field_key = row.get("field_key") if isinstance(row, dict) else None
            if field_key:
                suppressed.add(field_key)

        # 2. 取全部 CoreMemory
        # CoreMemory 不可用时返回空 而非冒用旧数据
        try:
            memories = self._core_memory.get_all(user.username)
        except Exception:
            logger.exception(
                "CoreMemory 不可用 跳过推断字段 user=%s",
                user.username,
            )
            return []

        fields: list[ProfileField] = []
        for memory in memories or []:
            if not isinstance(memory, dict):
                continue

            category = memory.get("category") or "general"
            field_key = CATEGORY_MAP.get(category, "user_fact")

            # 被用户抑制的 field_key 跳过 永不出现在推断画像中
            if field_key in suppressed:
                continue

            content = memory.get("content")
            memory_id = memory.get("id")
            source_ids = [str(memory_id)] if memory_id is not None else []

            fields.append(
                ProfileField(
                    field=field_key,
                    value=content,
                    origin=ProfileOrigin.INFERRED_PATTERN,
                    confidence=0.7,
                    source_memory_ids=source_ids,
                )
            )

            # 同步回写 ProfileStore 失败不影响本轮画像返回
            try:
                self._profile_store.upsert_dimension(
                    user.id,
                    field_key,
                    content,
                    origin="inferred_pattern",
                    confidence=0.7,
                    source_memory_ids=source_ids,
                    status="active",
                )
            except Exception:
                logger.warning(
                    "ProfileStore upsert 失败 field_key=%s user=%s",
                    field_key,
                    user.id,
                    exc_info=True,
                )

        return fields

    # ------------------------------------------------------------------ 缓存与哈希

    def _compute_hash(self, user, query: ProfileQuery, settings) -> str:
        """计算本轮输入哈希 用于缓存命中判断

        哈希键:
            user.id + preferred_style + custom_instruction + current_week
            + learning_profile_enabled + inferred_profile_enabled
            + group_id + current_message[:100]
            + suppressed_fields_hash (从 ProfileStore 实时查询)

        suppressed_fields_hash 保证用户删除推断字段后
        即使进程内 invalidate 未跨 Worker 传播 哈希也会变化 从而失效缓存。

        Args:
            user: UserRecord         => 用户数据对象
            query: ProfileQuery      => 本轮查询参数
            settings: MemorySettings => 记忆开关

        Returns:
            str => md5 十六进制字符串
        """
        # 实时查询被抑制字段 拼入哈希 保证 suppress 后缓存失效
        try:
            suppressed_rows = self._profile_store.list_dimensions(
                user.id,
                status_filter="suppressed",
            )
            suppressed_keys = sorted(
                row.get("field_key", "")
                for row in (suppressed_rows or [])
                if isinstance(row, dict)
            )
            suppressed_hash = ",".join(suppressed_keys)
        except Exception:
            # ProfileStore 不可用时用空串 哈希仍可计算 build 内部 fail-closed 兜底
            suppressed_hash = "unavailable"

        parts = [
            str(user.id),
            str(getattr(user, "preferred_style", "") or ""),
            str(getattr(user, "custom_instruction", "") or ""),
            str(getattr(user, "current_week", "") or ""),
            str(getattr(settings, "learning_profile_enabled", True)),
            str(getattr(settings, "inferred_profile_enabled", True)),
            str(query.group_id or ""),
            str(query.current_message or "")[:100],
            suppressed_hash,
        ]
        payload = "|".join(parts)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def _empty_snapshot(self, user_id: str) -> ProfileSnapshot:
        """用户不存在时返回的空快照

        Args:
            user_id: str => 用户 id

        Returns:
            ProfileSnapshot => 所有分节为空的快照 profile_version=0
        """
        return ProfileSnapshot(
            user_id=user_id,
            profile_version=0,
            explicit_context=[],
            response_preferences=[],
            active_goals=[],
            active_projects=[],
            relevant_learning_state=[],
            relevant_constraints=[],
            inferred_patterns=[],
            source_memory_ids=[],
            generated_at=datetime.now(),
        )


class _DefaultSettings:
    """settings 缺失时的回退值 与 UserStore 懒迁移前保持一致 两个开关都为 True"""

    learning_profile_enabled: bool = True
    inferred_profile_enabled: bool = True
