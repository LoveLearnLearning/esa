from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.core.services.auth_service import AuthService
from backend.core.services.frontier_tracking_service import FrontierTrackingService
from backend.core.services.research_data_service import ResearchDataService
from backend.core.services.research_writing_service import ResearchWritingService
from backend.core.stores.frontier_tracking_store import FrontierTrackingStore
from backend.core.stores.research_data_store import ResearchDataStore
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.research_writing_store import ResearchWritingStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.sqlite_connection import connect_sqlite
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.web.webAPI import create_app


class _QueueRecorder:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def submit(self, job_id: str) -> None:
        self.job_ids.append(job_id)


class _FakeLLM:
    async def chat(self, messages, *, max_tokens, temperature):
        assert messages
        assert max_tokens == 3000
        assert temperature == 0.2
        return "# Revised research outline\n\n- Evidence-backed section"


def _app(tmp_path):
    database = tmp_path / "research.db"
    user_store = UserStore(database)
    session_store = SessionStore(database)
    app = create_app(
        app_lifespan=None,
        trusted_hosts=("testserver",),
        forwarded_allow_ips=("testclient",),
        enable_legacy_routes=False,
    )
    app.state.user_store = user_store
    app.state.session_store = session_store
    app.state.user_presence_store = UserPresenceStore(database)
    app.state.research_project_store = ResearchProjectStore(database)
    app.state.frontier_tracking_store = FrontierTrackingStore(database)
    app.state.research_writing_store = ResearchWritingStore(database)
    app.state.research_data_store = ResearchDataStore(database)
    app.state.frontier_tracking_service = _QueueRecorder()
    app.state.research_writing_service = _QueueRecorder()
    app.state.research_data_service = ResearchDataService(
        app.state.research_data_store,
        tmp_path / "research_data",
    )
    app.state.auth = AuthService(user_store, session_store)
    return app


def _login(client: TestClient, username: str) -> dict[str, str]:
    user = client.app.state.auth.register(
        username,
        "correct-password",
        "student",
        email=f"{username}@example.test",
        email_verified_at="2026-08-12T00:00:00+00:00",
    )
    assert user is not None
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['session_id']}"}


def _project(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/research/projects",
        headers=headers,
        json={"name": "Agent research", "description": "Production demo"},
    )
    assert response.status_code == 201
    return response.json()


def test_queue_recovery_stays_read_only_when_no_job_was_interrupted(tmp_path):
    database = tmp_path / "research.db"
    store = FrontierTrackingStore(database)
    job_id = "queued-job"
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO research_frontier_jobs (
                job_id, project_id, user_id, query, status,
                created_at, updated_at
            ) VALUES (?, 'project', 'user', 'query', 'queued', ?, ?)
            """,
            (job_id, now, now),
        )

    reader = sqlite3.connect(database)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM research_frontier_jobs").fetchall()
    store._connect = lambda: connect_sqlite(database, timeout=0.05)
    try:
        assert store.requeue_interrupted() == [job_id]
    finally:
        reader.close()


def test_frontier_job_is_user_scoped_and_uses_real_search_results(tmp_path):
    client = TestClient(_app(tmp_path))
    alice = _login(client, "alice")
    bob = _login(client, "bob")
    project = _project(client, alice)

    created = client.post(
        f"/api/research/projects/{project['project_id']}/frontier-jobs",
        headers=alice,
        json={"query": "agent memory", "time_window_years": 5, "max_results": 10},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert client.app.state.frontier_tracking_service.job_ids == [job_id]
    assert client.get(f"/api/research/frontier-jobs/{job_id}", headers=bob).status_code == 404

    year = datetime.now(timezone.utc).year

    def fake_search(query, **kwargs):
        assert query == "agent memory"
        assert kwargs["sort_by"] in {"submitted", "relevance"}
        return {
            "total_results": 2,
            "results": [
                {
                    "arxiv_id": "2601.00001",
                    "title": "Persistent Memory for Reliable Agents",
                    "abstract": "Persistent memory improves reliable agent planning.",
                    "published": f"{year}-01-01",
                    "categories": ["cs.AI"],
                    "arxiv_url": "https://arxiv.org/abs/2601.00001",
                },
                {
                    "arxiv_id": "2602.00002",
                    "title": "Evaluation of Agent Memory",
                    "abstract": "Benchmarks evaluate persistent agent memory.",
                    "published": f"{year}-02-01",
                    "categories": ["cs.CL"],
                    "arxiv_url": "https://arxiv.org/abs/2602.00002",
                },
            ],
        }

    service = FrontierTrackingService(
        client.app.state.frontier_tracking_store,
        search=fake_search,
    )
    result = service.run_job(job_id)
    assert result["status"] == "succeeded"
    assert result["result"]["source"] == "arXiv"
    assert result["result"]["paper_count"] == 2
    assert result["result"]["hotspots"]


def test_writing_job_versions_document_without_fabricating_sources(tmp_path):
    client = TestClient(_app(tmp_path))
    headers = _login(client, "writer")
    project = _project(client, headers)
    created = client.post(
        f"/api/research/projects/{project['project_id']}/documents",
        headers=headers,
        json={
            "title": "Paper outline",
            "document_type": "outline",
            "content": "Known evidence only.",
        },
    )
    assert created.status_code == 201
    document = created.json()

    queued = client.post(
        f"/api/research/documents/{document['document_id']}/writing-jobs",
        headers=headers,
        json={"operation": "polish", "instruction": "Make it formal"},
    )
    assert queued.status_code == 202
    job_id = queued.json()["job_id"]
    service = ResearchWritingService(
        client.app.state.research_writing_store,
        _FakeLLM(),
    )
    completed = asyncio.run(service.run_job(job_id))
    assert completed["status"] == "succeeded"

    refreshed = client.get(
        f"/api/research/documents/{document['document_id']}",
        headers=headers,
    ).json()
    assert refreshed["version"] == 2
    assert refreshed["content"].startswith("# Revised")
    versions = client.get(
        f"/api/research/documents/{document['document_id']}/versions",
        headers=headers,
    ).json()
    assert [item["version"] for item in versions] == [2, 1]


def test_dataset_upload_profile_and_correlation_analysis(tmp_path):
    client = TestClient(_app(tmp_path))
    headers = _login(client, "analyst")
    project = _project(client, headers)
    uploaded = client.post(
        f"/api/research/projects/{project['project_id']}/datasets",
        headers=headers,
        data={"name": "Experiment results"},
        files={"file": ("results.csv", b"x,y,group\n1,2,a\n2,4,a\n3,6,b\n4,8,b\n", "text/csv")},
    )
    assert uploaded.status_code == 201
    dataset = uploaded.json()
    assert dataset["row_count"] == 4
    assert dataset["column_count"] == 3
    assert "file_path" not in dataset

    queued = client.post(
        f"/api/research/datasets/{dataset['dataset_id']}/analysis-jobs",
        headers=headers,
        json={"analysis_type": "correlation", "parameters": {}},
    )
    assert queued.status_code == 202
    completed = client.app.state.research_data_service.run_job(queued.json()["job_id"])
    assert completed["status"] == "succeeded"
    assert completed["result"]["pairs"][0]["pearson_r"] == 1.0
    assert "does not establish causality" in completed["result"]["method_note"]

    rejected = client.post(
        f"/api/research/projects/{project['project_id']}/datasets",
        headers=headers,
        data={"name": "Executable"},
        files={"file": ("payload.exe", b"unsafe", "application/octet-stream")},
    )
    assert rejected.status_code == 422
