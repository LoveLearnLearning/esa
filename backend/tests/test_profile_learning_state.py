from backend.agent.memories.memory_models import ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.utils.models import MemorySettings, UserRecord


class UserStore:
    def __init__(self):
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
        return self.user

    def get_memory_settings(self, user_id):
        return MemorySettings(user_id=user_id)


class MasteryStore:
    DEFAULT_MASTERY = 50.0

    def __init__(self, records=None):
        self.records = records or {}

    def get(self, user_name, kp_id):
        return self.records.get(kp_id)


class KGStore:
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
        return self.points.get(kp_id)

    def get_prerequisites(self, kp_id, max_depth=3):
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
    def get_summary(self, user_name, *, kp_id=None, limit=20):
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
    def get_next_profile_version(self, user_id):
        return 1

    def list_dimensions(self, user_id, status_filter=None):
        return []


def _build(records=None):
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
    value = _build({"二叉树": {"mastery_level": 30, "practice_count": 2}})
    assert value["mastery"]["has_record"] is True
    assert value["mastery"]["level"] == 30.0


def test_recorded_weak_prerequisite_is_distinguished():
    value = _build({"递归": {"mastery_level": 20, "practice_count": 1}})
    assert value["prerequisites"][0]["status"] == "weak"
    assert value["prerequisites"][0]["mastery_level"] == 20.0


def test_unseen_prerequisite_is_unknown_not_weak():
    value = _build()
    assert value["prerequisites"][0]["status"] == "unknown"
    assert value["prerequisites"][0]["mastery_level"] is None
