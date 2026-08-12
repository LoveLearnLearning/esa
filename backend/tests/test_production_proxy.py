from fastapi import Request
from fastapi.testclient import TestClient

from backend.core.services.email_verification_service import (
    EmailDeliveryError,
    EmailVerificationService,
    VerificationPolicy,
)
from backend.core.services.auth_service import AuthService
from backend.core.stores.email_verification_store import EmailVerificationStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.web.webAPI import create_app


class _FakeEmailSender:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    async def send_code(
        self,
        *,
        email: str,
        code: str,
        ttl_minutes: int,
        idempotency_key: str,
    ) -> None:
        del ttl_minutes, idempotency_key
        self.codes[email] = code

    async def close(self) -> None:
        return None


def _app(
    tmp_path,
    *,
    enable_legacy_routes: bool = False,
    forwarded_allow_ips: tuple[str, ...] = ("testclient",),
):
    database = tmp_path / "production-proxy.db"
    user_store = UserStore(database)
    session_store = SessionStore(database)

    app = create_app(
        app_lifespan=None,
        cors_allowed_origins=("https://esa.lovelearnlearning.cn",),
        trusted_hosts=("esa.lovelearnlearning.cn", "testserver"),
        forwarded_allow_ips=forwarded_allow_ips,
        enable_legacy_routes=enable_legacy_routes,
    )
    app.state.user_store = user_store
    app.state.session_store = session_store
    app.state.user_presence_store = UserPresenceStore(database)
    app.state.auth = AuthService(user_store, session_store)
    sender = _FakeEmailSender()
    app.state.test_email_sender = sender
    app.state.email_verification_store = EmailVerificationStore(database)
    app.state.email_verification_service = EmailVerificationService(
        store=app.state.email_verification_store,
        sender=sender,
        digest_secret="test-secret-that-is-at-least-32-characters",
        policy=VerificationPolicy(cooldown_seconds=1),
    )
    return app


def test_api_auth_contract_and_health(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)

    health = client.get("/api/health")
    sent = client.post(
        "/api/auth/email/send-code",
        json={"email": "Alice@Example.com"},
    )
    code = app.state.test_email_sender.codes["alice@example.com"]
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "Alice@Example.com",
            "verification_code": code,
            "username": "alice",
            "password": "correct-password",
        },
    )
    logged_in = client.post(
        "/api/auth/login",
        json={"username": "alice@example.com", "password": "correct-password"},
    )
    rejected = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    wrong_method = client.get("/api/auth/login")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert sent.status_code == 202
    assert registered.status_code == 201
    assert registered.json()["email"] == "alice@example.com"
    assert logged_in.status_code == 200
    assert logged_in.json()["email"] == "alice@example.com"
    assert rejected.status_code == 401
    assert wrong_method.status_code == 405
    assert all(path.startswith("/api/") for path in app.openapi()["paths"])

    token = logged_in.json()["session_id"]
    logged_out = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logged_out.status_code == 204


def test_registration_code_is_single_use(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    email = "single@example.com"

    assert client.post(
        "/api/auth/email/send-code", json={"email": email}
    ).status_code == 202
    code = app.state.test_email_sender.codes[email]
    body = {
        "email": email,
        "verification_code": code,
        "username": "single",
        "password": "correct-password",
    }

    assert client.post("/api/auth/register", json=body).status_code == 201
    body["username"] = "another"
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_legacy_user_can_bind_email_and_keep_username_login(tmp_path):
    app = _app(tmp_path)
    legacy = app.state.auth.register("legacy", "correct-password")
    assert legacy is not None and legacy.email is None
    client = TestClient(app)

    login = client.post(
        "/api/auth/login",
        json={"username": "legacy", "password": "correct-password"},
    )
    token = login.json()["session_id"]
    headers = {"Authorization": f"Bearer {token}"}
    email = "legacy@example.com"
    assert client.post(
        "/api/auth/email/bind/send-code", json={"email": email}, headers=headers
    ).status_code == 202
    code = app.state.test_email_sender.codes[email]

    bound = client.post(
        "/api/auth/email/bind",
        json={"email": email, "verification_code": code},
        headers=headers,
    )
    assert bound.status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"username": "legacy", "password": "correct-password"},
    ).status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"username": email, "password": "correct-password"},
    ).status_code == 200


def test_legacy_username_containing_at_sign_still_logs_in(tmp_path):
    app = _app(tmp_path)
    assert app.state.auth.register("legacy@example", "correct-password") is not None

    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "legacy@example", "password": "correct-password"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "legacy@example"


def test_cors_preflight_allows_only_configured_origin(tmp_path):
    client = TestClient(_app(tmp_path))
    headers = {
        "Origin": "https://esa.lovelearnlearning.cn",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }

    allowed = client.options("/api/auth/login", headers=headers)
    rejected = client.options(
        "/api/auth/login",
        headers={**headers, "Origin": "https://attacker.example"},
    )

    assert allowed.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://esa.lovelearnlearning.cn"
    )
    assert "POST" in allowed.headers["access-control-allow-methods"]
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_trusted_proxy_updates_scheme_client_and_preserves_host(tmp_path):
    app = _app(tmp_path)

    @app.get("/api/request-metadata")
    def request_metadata(request: Request):
        return {
            "scheme": request.url.scheme,
            "client": request.client.host if request.client else None,
            "host": request.headers.get("host"),
        }

    client = TestClient(app)
    response = client.get(
        "/api/request-metadata",
        headers={
            "Host": "esa.lovelearnlearning.cn",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "203.0.113.20",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "scheme": "https",
        "client": "203.0.113.20",
        "host": "esa.lovelearnlearning.cn",
    }


def test_untrusted_client_cannot_spoof_forwarded_headers(tmp_path):
    app = _app(tmp_path, forwarded_allow_ips=("127.0.0.1",))

    @app.get("/api/request-metadata")
    def request_metadata(request: Request):
        return {
            "scheme": request.url.scheme,
            "client": request.client.host if request.client else None,
        }

    client = TestClient(app)
    response = client.get(
        "/api/request-metadata",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "203.0.113.20",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"scheme": "http", "client": "testclient"}
    assert client.get(
        "/api/health",
        headers={"Host": "attacker.example"},
    ).status_code == 400


def test_legacy_routes_remain_available_during_migration(tmp_path):
    client = TestClient(_app(tmp_path, enable_legacy_routes=True))

    response = client.post(
        "/auth/login",
        json={"username": "missing", "password": "wrong-password"},
    )

    assert response.status_code == 401
