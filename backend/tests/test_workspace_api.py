# backend/tests/test_workspace_api.py

"""验证 `workspace_api` 相关行为与回归场景。"""

from fastapi.testclient import TestClient

from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.catalog import ScopedToolView
from backend.agent.tools.tools import tr
from backend.agent.memories.core_memory_service import CoreMemoryService
from backend.core.services.auth_service import AuthService
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.classroom_conversation_store import ClassroomConversationStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.core_memory_store import CoreMemoryStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.teaching_store import TeachingStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.web.webAPI import create_app


def _app(tmp_path):
    """处理 `_app` 相关逻辑。"""
    database = tmp_path / "workspace.db"
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
    app.state.group_store = GroupStore(database)
    app.state.chat_store = ChatStore(database)
    app.state.research_project_store = ResearchProjectStore(database)
    run_migrations(database)
    app.state.teaching_store = TeachingStore(database)
    app.state.classroom_conversation_store = ClassroomConversationStore(database)
    app.state.core_memory_store = CoreMemoryStore(database)
    app.state.core_memory_service = CoreMemoryService(app.state.core_memory_store)
    app.state.auth = AuthService(user_store, session_store)
    return app


def _register_and_login(
    client: TestClient,
    username: str,
    account_role: str,
) -> dict[str, str]:
    # Registration is covered by the email-verification API suite. These
    # workspace tests seed a verified identity through the domain service.
    """注册 `and login` 相关数据。"""
    registered = client.app.state.auth.register(
        username,
        "correct-password",
        account_role,
        email=f"{username}@example.test",
        email_verified_at="2026-08-12T00:00:00+00:00",
    )
    assert registered is not None
    assert registered.account_role == account_role
    logged_in = client.post(
        "/api/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert logged_in.status_code == 200
    payload = logged_in.json()
    assert payload["account_role"] == account_role
    return {"Authorization": f"Bearer {payload['session_id']}"}


def test_workspace_manifest_uses_backend_role_policy(tmp_path):
    """验证 `workspace_manifest_uses_backend_role_policy` 场景。"""
    client = TestClient(_app(tmp_path))
    student = _register_and_login(client, "student", "student")
    teacher = _register_and_login(client, "teacher", "teacher")

    student_manifest = client.get("/api/workspaces", headers=student)
    teacher_manifest = client.get("/api/workspaces", headers=teacher)

    assert student_manifest.status_code == 200
    assert [item["type"] for item in student_manifest.json()["workspaces"]] == [
        "learning",
        "research",
    ]
    assert student_manifest.json()["default_workspace"] == "learning"

    assert teacher_manifest.status_code == 200
    assert [item["type"] for item in teacher_manifest.json()["workspaces"]] == [
        "learning",
        "research",
        "teaching",
    ]
    assert teacher_manifest.json()["default_workspace"] == "teaching"


def test_core_memory_workspace_scope_uses_authorized_requested_workspace(tmp_path):
    """验证 `core_memory_workspace_scope_uses_authorized_requested_workspace` 场景。"""
    client = TestClient(_app(tmp_path))
    student = _register_and_login(client, "memory-student", "student")

    research = client.post(
        "/api/me/core-memories",
        headers=student,
        json={
            "memory_key": "research_style",
            "content": "Prefer concise experiment summaries",
            "category": "preference",
            "scope_type": "workspace",
            "workspace_type": "research",
        },
    )
    assert research.status_code == 201
    assert research.json()["scope_type"] == "workspace"
    assert research.json()["workspace_type"] == "research"

    denied = client.post(
        "/api/me/core-memories",
        headers=student,
        json={
            "memory_key": "forged_teaching_scope",
            "content": "This must not be stored",
            "scope_type": "workspace",
            "workspace_type": "teaching",
        },
    )
    assert denied.status_code == 403

    listed = client.get("/api/me/core-memories", headers=student)
    assert [item["memory_key"] for item in listed.json()] == ["research_style"]


def test_conversations_are_bound_to_an_authorized_workspace(tmp_path):
    """验证 `conversations_are_bound_to_an_authorized_workspace` 场景。"""
    client = TestClient(_app(tmp_path))
    student = _register_and_login(client, "student", "student")

    denied = client.post(
        "/api/conversations",
        headers=student,
        json={"title": "教师对话", "workspace_type": "teaching"},
    )
    assert denied.status_code == 403

    learning = client.post(
        "/api/conversations",
        headers=student,
        json={"title": "学习对话", "workspace_type": "learning"},
    )
    research = client.post(
        "/api/conversations",
        headers=student,
        json={"title": "科研对话", "workspace_type": "research"},
    )
    assert learning.status_code == 201
    assert research.status_code == 201
    assert learning.json()["workspace_type"] == "learning"
    assert research.json()["workspace_type"] == "research"

    listed = client.get(
        "/api/conversations?workspace_type=research",
        headers=student,
    )
    assert listed.status_code == 200
    assert [item["title"] for item in listed.json()] == ["科研对话"]


def test_learning_conversations_bind_only_active_student_classrooms(tmp_path):
    """验证学习对话只能绑定学生已加入的活动班级。"""
    client = TestClient(_app(tmp_path))
    student_headers = _register_and_login(client, "class-student", "student")
    teacher_headers = _register_and_login(client, "class-teacher", "teacher")
    outsider_headers = _register_and_login(client, "class-outsider", "student")
    teacher = client.app.state.user_store.get_by_username("class-teacher")
    student = client.app.state.user_store.get_by_username("class-student")
    assert teacher is not None and student is not None

    classroom = client.app.state.teaching_store.create_class(
        owner_id=teacher.id,
        name="Algorithms",
        course="Algorithms",
        term="2026",
        description="",
    )
    membership = client.app.state.teaching_store.invite_student(
        class_id=classroom["class_id"],
        teacher_id=teacher.id,
        student_id=student.id,
    )

    pending = client.post(
        "/api/conversations",
        headers=student_headers,
        json={
            "workspace_type": "learning",
            "class_id": classroom["class_id"],
        },
    )
    assert pending.status_code == 404
    client.app.state.teaching_store.respond_membership(
        membership_id=membership["membership_id"],
        student_id=student.id,
        accept=True,
    )

    bound = client.post(
        "/api/conversations",
        headers=student_headers,
        json={
            "title": "Class study",
            "workspace_type": "learning",
            "class_id": classroom["class_id"],
        },
    )
    assert bound.status_code == 201
    assert bound.json()["classroom_binding"]["class_id"] == classroom["class_id"]

    outsider = client.post(
        "/api/conversations",
        headers=outsider_headers,
        json={
            "workspace_type": "learning",
            "class_id": classroom["class_id"],
        },
    )
    assert outsider.status_code == 404
    assert client.post(
        "/api/conversations",
        headers=teacher_headers,
        json={
            "workspace_type": "teaching",
            "class_id": classroom["class_id"],
        },
    ).status_code == 201

    assignment = client.app.state.teaching_store.create_assignment(
        class_id=classroom["class_id"],
        title="Binary search",
        instructions="",
        due_at=None,
        questions=[],
        teacher_id=teacher.id,
    )
    draft = client.patch(
        f"/api/conversations/{bound.json()['conversation_id']}",
        headers=student_headers,
        json={"assignment_id": assignment["assignment_id"]},
    )
    assert draft.status_code == 404
    assert client.app.state.teaching_store.publish_assignment(
        assignment_id=assignment["assignment_id"], teacher_id=teacher.id
    )
    published = client.patch(
        f"/api/conversations/{bound.json()['conversation_id']}",
        headers=student_headers,
        json={"assignment_id": assignment["assignment_id"]},
    )
    assert published.status_code == 204


def test_research_projects_are_user_scoped_and_bind_research_chats(tmp_path):
    """验证 `research_projects_are_user_scoped_and_bind_research_chats` 场景。"""
    client = TestClient(_app(tmp_path))
    alice = _register_and_login(client, "alice", "student")
    bob = _register_and_login(client, "bob", "teacher")

    created = client.post(
        "/api/research/projects",
        headers=alice,
        json={"name": "多智能体科研", "description": "跟踪前沿与写作"},
    )
    assert created.status_code == 201
    project = created.json()
    assert project["status"] == "active"

    alice_projects = client.get("/api/research/projects", headers=alice)
    bob_projects = client.get("/api/research/projects", headers=bob)
    assert [item["project_id"] for item in alice_projects.json()] == [
        project["project_id"]
    ]
    assert bob_projects.json() == []

    bound = client.post(
        "/api/conversations",
        headers=alice,
        json={
            "title": "项目讨论",
            "workspace_type": "research",
            "research_project_id": project["project_id"],
        },
    )
    assert bound.status_code == 201
    assert bound.json()["research_project_id"] == project["project_id"]

    cross_user = client.post(
        "/api/conversations",
        headers=bob,
        json={
            "title": "越权项目",
            "workspace_type": "research",
            "research_project_id": project["project_id"],
        },
    )
    assert cross_user.status_code == 404

    wrong_workspace = client.post(
        "/api/conversations",
        headers=alice,
        json={
            "title": "错误绑定",
            "workspace_type": "learning",
            "research_project_id": project["project_id"],
        },
    )
    assert wrong_workspace.status_code == 422

    archived = client.patch(
        f"/api/research/projects/{project['project_id']}",
        headers=alice,
        json={"status": "archived"},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    archived_binding = client.post(
        "/api/conversations",
        headers=alice,
        json={
            "workspace_type": "research",
            "research_project_id": project["project_id"],
        },
    )
    assert archived_binding.status_code == 409

    existing_sync = client.post(
        f"/api/conversations/{bound.json()['conversation_id']}/messages",
        headers=alice,
        json={"content": "continue the project discussion"},
    )
    assert existing_sync.status_code == 409
    assert "archived" in existing_sync.json()["detail"]

    existing_stream = client.post(
        f"/api/conversations/{bound.json()['conversation_id']}/messages/stream",
        headers=alice,
        json={"content": "continue the project discussion"},
    )
    assert existing_stream.status_code == 409


def test_research_workspace_has_only_scoped_tools():
    """验证 `research_workspace_has_only_scoped_tools` 场景。"""
    register_builtin_tools()
    research_view = ScopedToolView.compile(tr, frozenset({"common", "research"}))
    research_tool_names = research_view.names
    assert "arxiv_search" in research_tool_names
    assert "web_search" in research_tool_names
    assert "get_mastery_report" not in research_tool_names
    assert "retrieve_knowledge" not in research_tool_names
