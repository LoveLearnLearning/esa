from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord


def test_user_course_store_keeps_association_not_kg_copy(tmp_path):
    database = tmp_path / "users.db"
    users = UserStore(database)
    user = UserRecord(
        id="user-1",
        username="alice",
        password_hash="hash",
        status="active",
    )
    assert users.create(user)
    store = UserCourseStore(database)

    assert store.upsert(
        user_id=user.id,
        name="数据结构",
        canonical_course="数据结构",
        source="timetable",
    )
    assert store.upsert(
        user_id=user.id,
        name="日语口语训练",
        canonical_course=None,
        source="timetable",
    )

    rows = store.list_for_user(user.id)
    assert [row["name"] for row in rows] == ["数据结构", "日语口语训练"]
    assert rows[0]["canonical_course"] == "数据结构"
    assert rows[1]["canonical_course"] is None
    assert store.delete(user_id=user.id, name="数据结构")
