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
from datetime import datetime

from backend.agent.memories.memory_models import (
    ProfileField,
    ProfileOrigin,
    ProfileQuery,
    ProfileSnapshot,
)


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
        # user_id -> (input_hash, snapshot) 简单缓存 避免同一轮重复构建
        self._cache: dict[str, tuple[str, ProfileSnapshot]] = {}

    # ------------------------------------------------------------------ 主入口

    def build(self, query: ProfileQuery) -> ProfileSnapshot:
        """主入口 基于查询参数构建本轮 ProfileSnapshot

        流程:
            1. 取 UserRecord 不存在返回空快照
            2. 取 MemorySettings 不存在默认两个开关都 True
            3. 计算输入哈希 命中缓存直接返回
            4. 分别组装四个分节(explicit/preferences/learning/inferred)
            5. 汇总 source_memory_ids 写缓存返回

        Args:
            query: ProfileQuery => 本轮画像查询参数

        Returns:
            ProfileSnapshot => 本轮结构化画像快照
        """
        user = self._user_store.get_by_id(query.user_id)
        if user is None:
            return self._empty_snapshot(query.user_id)

        settings = self._user_store.get_memory_settings(query.user_id)
        if settings is None:
            # 用户存在但无 settings 行 视为全开 与 UserStore 懒迁移前保持一致
            settings = _DefaultSettings()

        input_hash = self._compute_hash(user, query, settings)
        cached = self._cache.get(query.user_id)
        if cached is not None and cached[0] == input_hash:
            return cached[1]

        # 重建 版本号自增
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
            generated_at=datetime.now(),
        )

        self._cache[query.user_id] = (input_hash, snapshot)
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
        lowered_texts = [t.lower() for t in candidate_texts]
        for kp in knowledge_points:
            kp_name = kp.get("name") or ""
            if not kp_name:
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

        Args:
            user: UserRecord         => 用户数据对象
            settings: MemorySettings => 记忆开关

        Returns:
            list[ProfileField] => 未被抑制的推断模式
        """
        if not getattr(settings, "inferred_profile_enabled", True):
            return []

        # 1. 取被抑制的 field_key 集合
        suppressed: set[str] = set()
        try:
            suppressed_rows = self._profile_store.list_dimensions(
                user.id,
                status_filter="suppressed",
            )
        except Exception:
            suppressed_rows = []

        for row in suppressed_rows or []:
            field_key = row.get("field_key") if isinstance(row, dict) else None
            if field_key:
                suppressed.add(field_key)

        # 2. 取全部 CoreMemory
        try:
            memories = self._core_memory.get_all(user.username)
        except Exception:
            memories = []

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
                pass

        return fields

    # ------------------------------------------------------------------ 缓存与哈希

    def _compute_hash(self, user, query: ProfileQuery, settings) -> str:
        """计算本轮输入哈希 用于缓存命中判断

        哈希键:
            user.id + preferred_style + custom_instruction + current_week
            + learning_profile_enabled + inferred_profile_enabled
            + group_id + current_message[:100]

        Args:
            user: UserRecord         => 用户数据对象
            query: ProfileQuery      => 本轮查询参数
            settings: MemorySettings => 记忆开关

        Returns:
            str => md5 十六进制字符串
        """
        parts = [
            str(user.id),
            str(getattr(user, "preferred_style", "") or ""),
            str(getattr(user, "custom_instruction", "") or ""),
            str(getattr(user, "current_week", "") or ""),
            str(getattr(settings, "learning_profile_enabled", True)),
            str(getattr(settings, "inferred_profile_enabled", True)),
            str(query.group_id or ""),
            str(query.current_message or "")[:100],
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
