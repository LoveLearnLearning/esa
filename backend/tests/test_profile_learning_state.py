# backend/tests/test_profile_learning_state.py

"""验证 `profile_learning_state` 相关行为与回归场景。"""

from backend.agent.memories.memory_models import ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.utils.models import MemorySettings, UserRecord


class UserStore:
    """封装 `user store` 数据持久化操作。"""
    def __init__(self):
        """初始化 `UserStore` 实例。"""
        self.user = UserRecord(
            id="u1",
            username="alice",
            password_hash="h",
            status="active",
            preferred_style="concise",
            preferred_tone="friendly",
            custom_instruction="",
            major="cs",
            grade="大二",
            current_week=3,
            total_weeks=18,
        )

    def get_by_id(self, user_id):
        """获取 `by id` 相关数据。"""
        return self.user

    def get_memory_settings(self, user_id):
        """获取 `memory settings` 相关数据。"""
        return MemorySettings(user_id=user_id)


class MasteryStore:
    """封装 `mastery store` 数据持久化操作。"""
    DEFAULT_MASTERY = 50.0

    def __init__(self, records=None):
        """初始化 `MasteryStore` 实例。"""
        self.records = records or {}

    def get(self, user_name, kp_id):
        """获取 `get` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。

        Returns:
            object => 处理结果。
        """
        return self.records.get(kp_id)


class KGStore:
    """封装 `k g store` 数据持久化操作。"""
    points = {
        "二叉树": {
            "id": "二叉树",
            "name": "二叉树",
            "course": "数据结构",
        },
        "递归": {
            "id": "递归",
            "name": "递归",
            "course": "算法设计与分析",
        },
    }

    def get_point(self, kp_id):
        """获取 `point` 相关数据。"""
        return self.points.get(kp_id)

    def get_prerequisites(self, kp_id, max_depth=3):
        """获取 `prerequisites` 相关数据。

        Args:
            kp_id: object => kp ID。
            max_depth: object => `max_depth` 参数。

        Returns:
            object => 处理结果。
        """
        point = self.points[kp_id]
        results = [
            {
                "kp_id": kp_id,
                "name": point["name"],
                "course": point["course"],
                "depth": 0,
                "weight": 0.0,
            }
        ]
        if kp_id == "二叉树":
            results.append(
                {
                    "kp_id": "递归",
                    "name": "递归",
                    "course": "算法设计与分析",
                    "depth": 1,
                    "weight": 0.1,
                }
            )
        return results


class EvidenceStore:
    """封装 `evidence store` 数据持久化操作。"""
    def get_summary(self, user_name, *, kp_id=None, limit=20):
        """获取 `summary` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。
            limit: object => 返回数量上限。

        Returns:
            object => 处理结果。
        """
        return {
            "evidence_count": 0,
            "correct_rate": None,
            "avg_hint_level": None,
            "independent_rate": None,
            "avg_explanation_score": None,
            "avg_transfer_score": None,
            "recent_misconceptions": [],
        }


class ProfileStore:
    """封装 `profile store` 数据持久化操作。"""
    def get_next_profile_version(self, user_id):
        """获取 `next profile version` 相关数据。"""
        return 1

    def list_dimensions(self, user_id, status_filter=None):
        """列出 `dimensions` 相关数据。

        Args:
            user_id: object => 用户 ID。
            status_filter: object => `status_filter` 参数。

        Returns:
            object => 处理结果。
        """
        return []


def _build(records=None):
    """构建 `build` 相关数据。"""
    builder = ProfileBuilder(
        UserStore(),
        MasteryStore(records),
        KGStore(),
        ProfileStore(),
        EvidenceStore(),
    )
    snapshot = builder.build(
        ProfileQuery(
            user_id="u1",
            username="alice",
            current_message="讲讲二叉树",
            resolved_kp_ids=["二叉树"],
        )
    )
    assert len(snapshot.relevant_learning_state) == 1
    return snapshot.relevant_learning_state[0].value


def test_unseen_point_is_present_but_marked_without_mastery_record():
    """验证 `unseen_point_is_present_but_marked_without_mastery_record` 场景。"""
    value = _build()
    assert value["mastery"] == {
        "has_record": False,
        "level": None,
        "status": "unseen",
        "retention": None,
        "evidence_confidence": 0.0,
        "needs_review": False,
        "practice_count": 0,
    }


def test_recorded_mastery_is_present_in_learning_state():
    """验证 `recorded_mastery_is_present_in_learning_state` 场景。"""
    value = _build({"二叉树": {"mastery_level": 30, "practice_count": 2}})
    assert value["mastery"]["has_record"] is True
    assert value["mastery"]["level"] == 30.0


def test_recorded_weak_prerequisite_is_distinguished():
    """验证 `recorded_weak_prerequisite_is_distinguished` 场景。"""
    value = _build({"递归": {"mastery_level": 20, "practice_count": 1}})
    assert value["prerequisites"][0]["status"] == "weak"
    assert value["prerequisites"][0]["mastery_level"] == 20.0


def test_unseen_prerequisite_is_unknown_not_weak():
    """验证 `unseen_prerequisite_is_unknown_not_weak` 场景。"""
    value = _build()
    assert value["prerequisites"][0]["status"] == "unknown"
    assert value["prerequisites"][0]["mastery_level"] is None
