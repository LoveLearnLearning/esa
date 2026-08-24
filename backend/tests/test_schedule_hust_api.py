from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_store import UserStore
from backend.core.timetable.hust import HustChallengePublic, HustFetchedSchedule
from backend.core.timetable.models import TimetableEntryDraft
from backend.core.timetable.parser import ParsedTimetable
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.routers import schedule_hust
from backend.core.web.schedule_hust_schemas import HustChallengeCompleteRequest


class _FakeImporter:
    def __init__(self) -> None:
        self.complete_arguments = None

    async def start_challenge(self, **_kwargs):
        return HustChallengePublic(
            challenge_id="challenge-1",
            captcha_image_base64="R0lGODlh",
            captcha_mime_type="image/gif",
            expires_at="2026-08-12T00:05:00+00:00",
            recommended_semester_name="推荐学期",
            recommended_start_date="2026-09-07",
            recommended_end_date="2027-01-24",
        )

    async def complete_challenge(self, **kwargs):
        self.complete_arguments = kwargs
        start = kwargs["semester_start"]
        end = kwargs["semester_end"]
        return HustFetchedSchedule(
            semester_name=kwargs["semester_name"],
            external_id=f"{start.isoformat()}_{end.isoformat()}",
            start_date=start,
            end_date=end,
            total_weeks=20,
            parsed=ParsedTimetable(
                entries=[
                    TimetableEntryDraft(
                        course_name="计算机网络",
                        course_code="CS302",
                        teacher="刘老师",
                        location="东九楼",
                        date="2026-09-07",
                        start_time="08:00",
                        end_time="09:35",
                        week_number=1,
                        weekday=1,
                        source_event_id="network-1",
                    ),
                    TimetableEntryDraft(
                        course_name="计算机网络",
                        course_code="CS302",
                        teacher="刘老师",
                        location="东九楼",
                        date="2026-09-14",
                        start_time="08:00",
                        end_time="09:35",
                        week_number=2,
                        weekday=1,
                        source_event_id="network-2",
                    ),
                    TimetableEntryDraft(
                        course_name="计算机网络",
                        course_code="CS302",
                        teacher="刘老师",
                        location="东九楼",
                        date="2026-09-28",
                        start_time="08:00",
                        end_time="09:35",
                        week_number=4,
                        weekday=1,
                        source_event_id="network-4",
                    ),
                ],
                skipped_entries=0,
                warnings=[],
            ),
        )


def _app(tmp_path, monkeypatch):
    database = tmp_path / "hust-api.db"
    user_store = UserStore(database)
    user = UserRecord(
        id="user-id", username="alice", password_hash="hash", status="active"
    )
    assert user_store.create(user)
    importer = _FakeImporter()
    app = FastAPI()
    app.state.user_store = user_store
    app.state.schedule_store = ScheduleStore(database)
    app.state.user_course_store = UserCourseStore(database)
    app.state.hust_importer = importer
    app.include_router(schedule_hust.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="session", user_id=user.id
    )
    monkeypatch.setattr(schedule_hust.kg_store, "resolve_course_name", lambda name: name)
    return app, importer


def test_hust_challenge_and_complete_use_existing_schedule_store(tmp_path, monkeypatch):
    app, importer = _app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        challenge = client.post("/me/schedule/import/hust/challenge", json={})
        assert challenge.status_code == 200
        assert challenge.json()["challenge_id"] == "challenge-1"

        completed = client.post(
            "/me/schedule/import/hust/complete",
            json={
                "challenge_id": "challenge-1",
                "username": "u20260001",
                "password": "not-stored",
                "captcha": "1234",
                "semester_name": "用户选择学期",
                "start_date": "2026-09-07",
                "end_date": "2027-01-24",
                "target": "new",
                "table_name": "华科大二上",
            },
        )

    assert completed.status_code == 200, completed.text
    body = completed.json()
    # 第 1-2 周与第 4 周不连续，必须保留为两个规则，不能误扩成第 1-4 周。
    assert body["imported_count"] == 2
    assert body["courses"][0]["name"] == "计算机网络"
    assert body["courses"][0]["start_period"] == 1
    assert body["courses"][0]["end_period"] == 2
    assert body["courses"][0]["start_week"] == 1
    assert body["courses"][0]["end_week"] == 2
    assert body["courses"][1]["start_week"] == 4
    assert body["courses"][1]["end_week"] == 4
    assert any(table["name"] == "华科大二上" for table in body["tables"])
    assert app.state.schedule_store.get_settings("user-id")["term_start_date"] == "2026-09-07"
    assert app.state.user_store.get_by_id("user-id").total_weeks == 20
    assert app.state.user_course_store.list_for_user("user-id")[0]["name"] == "计算机网络"
    assert importer.complete_arguments["semester_start"] == date(2026, 9, 7)


def test_password_schema_never_reveals_secret() -> None:
    secret = "SENSITIVE_" * 40
    request = HustChallengeCompleteRequest.model_validate(
        {
            "challenge_id": "challenge-1",
            "username": "u20260001",
            "password": secret,
            "captcha": "1234",
        }
    )
    assert request.password.get_secret_value() == secret
    assert secret not in repr(request)


def test_cross_field_validation_does_not_echo_password(tmp_path, monkeypatch) -> None:
    app, _ = _app(tmp_path, monkeypatch)
    secret = "NEVER_ECHO_THIS_PASSWORD"
    with TestClient(app) as client:
        response = client.post(
            "/me/schedule/import/hust/complete",
            json={
                "challenge_id": "challenge-1",
                "username": "u20260001",
                "password": secret,
                "captcha": "1234",
                "start_date": "2026-09-07",
            },
        )
    assert response.status_code == 422
    assert secret not in response.text
