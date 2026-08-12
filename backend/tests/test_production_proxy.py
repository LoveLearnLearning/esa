from fastapi import Request
from fastapi.testclient import TestClient

from backend.core.services.auth_service import AuthService
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.web.webAPI import create_app


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
    return app


def test_api_auth_contract_and_health(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)

    health = client.get("/api/health")
    registered = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "correct-password"},
    )
    logged_in = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct-password"},
    )
    rejected = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    wrong_method = client.get("/api/auth/login")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert registered.status_code == 201
    assert logged_in.status_code == 200
    assert rejected.status_code == 401
    assert wrong_method.status_code == 405
    assert all(path.startswith("/api/") for path in app.openapi()["paths"])

    token = logged_in.json()["session_id"]
    logged_out = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logged_out.status_code == 204


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
