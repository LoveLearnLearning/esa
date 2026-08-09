from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord


def _user(user_id: str, username: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        username=username,
        password_hash="hash",
        status="active",
    )


def test_schedule_is_persisted_per_user(tmp_path):
    database = tmp_path / "schedule.db"
    users = UserStore(database)
    alice = _user("alice-id", "alice")
    bob = _user("bob-id", "bob")
    assert users.create(alice)
    assert users.create(bob)
    store = ScheduleStore(database)

    saved = store.upsert_course(
        alice.id,
        {
            "name": "数据结构",
            "teacher": "张老师",
            "location": "A101",
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "start_week": 1,
            "end_week": 18,
            "color_value": 0xFF2563EB,
        },
    )
    store.save_settings(
        alice.id,
        {
            "morning_period_count": 5,
            "afternoon_period_count": 4,
            "evening_period_count": 2,
            "morning_start_minutes": 480,
            "afternoon_start_minutes": 840,
            "evening_start_minutes": 1140,
            "period_duration_minutes": 45,
            "break_duration_minutes": 10,
            "term_start_date": "2026-09-07",
        },
    )

    assert store.list_courses(alice.id)[0]["name"] == "数据结构"
    assert store.list_courses(bob.id) == []
    assert store.get_settings(alice.id)["morning_period_count"] == 5
    assert store.get_settings(alice.id)["term_start_date"] == "2026-09-07"
    assert store.get_settings(bob.id)["morning_period_count"] == 4
    assert store.delete_course(alice.id, saved["id"])
