"""验证账号状态对登录和现有会话的约束。"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from backend.core.services.auth_service import AuthService
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.web.webAPI import create_app


def _app(tmp_path):
    database = tmp_path / "auth-status.db"
    user_store = UserStore(database)
    session_store = SessionStore(database)
    application = create_app(
        app_lifespan=None,
        trusted_hosts=("testserver",),
        forwarded_allow_ips=("testclient",),
        enable_legacy_routes=False,
    )
    application.state.user_store = user_store
    application.state.session_store = session_store
    application.state.auth = AuthService(user_store, session_store)
    return application


def _register(application, username: str):
    user = application.state.auth.register(
        username,
        "correct-password",
        email=f"{username}@example.test",
        email_verified_at="2026-09-05T00:00:00+00:00",
    )
    assert user is not None
    return user


def test_inactive_user_cannot_log_in(tmp_path) -> None:
    application = _app(tmp_path)
    user = _register(application, "inactive-login")
    application.state.user_store.execute(
        "UPDATE users SET status = ? WHERE id = ?",
        ("disabled", user.id),
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "inactive-login", "password": "correct-password"},
        )

    assert response.status_code == 401
    assert application.state.session_store.query_all("SELECT * FROM sessions") == []


@pytest.mark.parametrize("account_removed", [False, True])
def test_existing_session_is_revoked_when_user_becomes_invalid(tmp_path, account_removed) -> None:
    application = _app(tmp_path)
    user = _register(application, "inactive-session")

    with TestClient(application) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "inactive-session", "password": "correct-password"},
        )
        assert login.status_code == 200
        token = login.json()["session_id"]

        if account_removed:
            application.state.user_store.execute("DELETE FROM users WHERE id = ?", (user.id,))
        else:
            application.state.user_store.execute(
                "UPDATE users SET status = ? WHERE id = ?",
                ("disabled", user.id),
            )

        response = client.get(
            "/api/workspaces",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert application.state.session_store.get(token) is None
