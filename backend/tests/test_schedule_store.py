# backend/tests/test_schedule_store.py

"""验证 `schedule_store` 相关行为与回归场景。"""

from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord


def _user(user_id: str, username: str) -> UserRecord:
    """处理 `_user` 相关逻辑。"""
    return UserRecord(
        id=user_id,
        username=username,
        password_hash="hash",
        status="active",
    )


def test_schedule_is_persisted_per_user(tmp_path):
    """验证 `schedule_is_persisted_per_user` 场景。"""
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


def _course(name: str, weekday: int, periods: tuple[int, int], weeks=(1, 18)) -> dict:
    """处理 `_course` 相关逻辑。"""
    return {
        "name": name,
        "weekday": weekday,
        "start_period": periods[0],
        "end_period": periods[1],
        "start_week": weeks[0],
        "end_week": weeks[1],
    }


def test_import_skips_duplicates_and_time_conflicts(tmp_path):
    """验证 `import_skips_duplicates_and_time_conflicts` 场景。"""
    database = tmp_path / "schedule.db"
    users = UserStore(database)
    alice = _user("alice-id", "alice")
    assert users.create(alice)
    store = ScheduleStore(database)
    store.upsert_course(alice.id, _course("数据结构", 1, (1, 2)))

    imported, skipped = store.import_courses(
        alice.id,
        [
            _course("数据结构", 1, (1, 2)),  # 与已有完全相同：静默跳过
            _course("概率论", 1, (2, 3)),  # 与已有节次重叠：冲突跳过
            _course("操作系统", 2, (1, 2)),  # 不冲突：导入
            _course("体育", 2, (1, 2)),  # 与本批已导入冲突：跳过
            _course("数据结构实验", 1, (1, 2), weeks=(19, 20)),  # 周次不重叠：导入
        ],
    )

    assert [item["name"] for item in imported] == ["操作系统", "数据结构实验"]
    assert [item["name"] for item in skipped] == ["概率论", "体育"]
    assert len(store.list_courses(alice.id)) == 3


def test_multiple_schedule_tables_scope_courses(tmp_path):
    """验证 `multiple_schedule_tables_scope_courses` 场景。"""
    database = tmp_path / "schedule.db"
    users = UserStore(database)
    alice = _user("alice-id", "alice")
    assert users.create(alice)
    store = ScheduleStore(database)

    default_id = store.ensure_active_table(alice.id)
    store.upsert_course(alice.id, _course("数据结构", 1, (1, 2)))
    new_table = store.create_table(alice.id, "大二上", activate=True)

    # 新表激活后为空，同一时段的课不再与旧表冲突
    assert store.ensure_active_table(alice.id) == new_table["id"]
    assert store.list_courses(alice.id, new_table["id"]) == []
    imported, skipped = store.import_courses(alice.id, [_course("英语", 1, (1, 2))])
    assert [item["name"] for item in imported] == ["英语"]
    assert skipped == []
    assert len(store.list_courses(alice.id)) == 2

    # 切回默认表只看到原来的课
    assert store.activate_table(alice.id, default_id)
    assert [
        item["name"] for item in store.list_courses(alice.id, default_id)
    ] == ["数据结构"]

    # 删除激活表会回退到另一张，最后一张不允许删
    assert store.activate_table(alice.id, new_table["id"])
    removed = store.delete_table(alice.id, new_table["id"])
    assert [item["name"] for item in removed] == ["英语"]
    tables = store.list_tables(alice.id)
    assert [table["id"] for table in tables] == [default_id]
    assert tables[0]["is_active"]
    try:
        store.delete_table(alice.id, default_id)
        raise AssertionError("应拒绝删除最后一张课程表")
    except ValueError:
        pass


def test_existing_courses_migrate_into_default_table(tmp_path):
    """验证 `existing_courses_migrate_into_default_table` 场景。"""
    database = tmp_path / "schedule.db"
    users = UserStore(database)
    alice = _user("alice-id", "alice")
    assert users.create(alice)
    store = ScheduleStore(database)
    store.upsert_course(alice.id, _course("数据结构", 1, (1, 2)))

    # 模拟老库：清掉 table_id 后重新初始化，课程应归入自动创建的默认课表
    store.execute("UPDATE schedule_courses SET table_id = NULL", ())
    store.execute("DELETE FROM schedule_tables", ())
    reopened = ScheduleStore(database)
    tables = reopened.list_tables(alice.id)
    assert len(tables) == 1
    courses = reopened.list_courses(alice.id, tables[0]["id"])
    assert [item["name"] for item in courses] == ["数据结构"]
