# backend/tests/test_agent_action_and_core_memory_v2.py

"""验证 `agent_action_and_core_memory_v2` 相关行为与回归场景。"""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.agent.memories.core_memory_models import (
    MemoryRevisionConflict,
    MemoryScope,
)
from backend.agent.memories.core_memory_service import CoreMemoryService
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.agent.workspaces.capability_runtime import CapabilityRuntime
from backend.core.router.models import ResourceScope, WorkspaceRoute
from backend.core.services.agent_action_service import AgentActionService
from backend.core.services.research_project_profile_service import (
    ResearchProjectProfileService,
)
from backend.core.stores.agent_action_store import AgentActionStore
from backend.core.stores.classroom_conversation_store import (
    ClassroomConversationStore,
)
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.core_memory_store import CoreMemoryStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.frontier_tracking_store import FrontierTrackingStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.research_project_profile_store import (
    ResearchProjectProfileStore,
)
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord
from backend.core.workflows.research import (
    ResearchWorkflowFacade,
    execute_research_action,
    validate_research_action,
)


def _database(tmp_path):
    """处理 `_database` 相关逻辑。"""
    database = tmp_path / "runtime.db"
    users = UserStore(database)
    assert users.create(
        UserRecord(id="u1", username="alice", password_hash="hash", status="active")
    )
    GroupStore(database)
    chats = ChatStore(database)
    run_migrations(database)
    conversation = chats.create_conversation("u1", workspace_type="research")
    return database, conversation["conversation_id"]


def _request_action(service, conversation_id, key="same-key"):
    """处理 `_request_action` 相关逻辑。"""
    return service.request(
        user_id="u1",
        conversation_id=conversation_id,
        workspace_type="research",
        action_type="start_frontier_tracking",
        arguments={"query": "agent memory", "project_id": "p1"},
        resource_snapshot={"project_id": "p1"},
        policy_id="research.v1",
        idempotency_key=key,
    )


def _memory_executor(
    service: CoreMemoryService,
    conversation_id: str,
    *,
    workspace_type: str,
    request_id: str,
):
    """处理 `_memory_executor` 相关逻辑。"""
    scope = ResourceScope()
    route = WorkspaceRoute(
        workspace_type=workspace_type,
        agent_profile_id=f"{workspace_type}.default.v1",
        skill_scopes=frozenset({"common", workspace_type}),
        tool_scopes=frozenset({"common", workspace_type}),
        prompt_key=f"{workspace_type}.v1",
        profile_policy=f"{workspace_type}.v1",
        memory_policy_id=f"{workspace_type}.v1",
        resource_scope=scope,
        action_policy=f"{workspace_type}.v1",
    )
    context = ToolExecutionContext(
        user_id="u1",
        conversation_id=conversation_id,
        workspace_route=route,
        authorized_resources=scope,
        conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(core_memory_service=service),
        request_id=request_id,
    )
    return CapabilityRuntime().compile(
        skill_scopes=route.skill_scopes,
        tool_scopes=route.tool_scopes,
        profile_fingerprint=f"{workspace_type}:1",
        policy_versions=(route.memory_policy_id,),
    ).bind(context)


def test_agent_action_create_is_atomic_and_approval_executes_once(tmp_path):
    """验证 `agent_action_create_is_atomic_and_approval_executes_once` 场景。"""
    database, conversation_id = _database(tmp_path)
    calls: list[str] = []

    def execute(action):
        """执行 `execute` 相关数据。"""
        calls.append(action["action_id"])
        return {"job_id": "job-1"}

    service = AgentActionService(
        AgentActionStore(database),
        executors={"start_frontier_tracking": execute},
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(
            pool.map(lambda _index: _request_action(service, conversation_id), range(16))
        )
    assert len({item["action_id"] for item in created}) == 1
    action_id = created[0]["action_id"]
    assert calls == []

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _index: service.approve_and_execute(action_id, "u1"),
                range(16),
            )
        )
    final = service.store.get(action_id, "u1")
    assert final["status"] == "succeeded"
    assert final["result"] == {"job_id": "job-1"}
    assert calls == [action_id]
    assert {item["action_id"] for item in results} == {action_id}


def test_agent_action_reject_expire_and_cross_user_guards(tmp_path):
    """验证 `agent_action_reject_expire_and_cross_user_guards` 场景。"""
    database, conversation_id = _database(tmp_path)
    service = AgentActionService(AgentActionStore(database))
    rejected = _request_action(service, conversation_id, "reject")
    assert service.reject(rejected["action_id"], "u1")["status"] == "rejected"
    assert service.reject(rejected["action_id"], "u1")["status"] == "rejected"
    with pytest.raises(ValueError, match="not pending"):
        service.approve(rejected["action_id"], "u1")
    with pytest.raises(KeyError):
        service.approve(rejected["action_id"], "other")

    expired = service.request(
        user_id="u1",
        conversation_id=conversation_id,
        workspace_type="research",
        action_type="start_frontier_tracking",
        arguments={"query": "expired"},
        resource_snapshot={},
        policy_id="research.v1",
        idempotency_key="expired",
        ttl_minutes=-1,
    )
    with pytest.raises(ValueError, match="expired"):
        service.approve(expired["action_id"], "u1")
    assert service.store.get(expired["action_id"], "u1")["status"] == "expired"


def test_core_memory_create_update_candidate_and_audit_are_transactional(tmp_path):
    """验证 `core_memory_create_update_candidate_and_audit_are_transactional` 场景。"""
    database, _conversation_id = _database(tmp_path)
    store = CoreMemoryStore(database)
    scope = MemoryScope("global")
    memory = store.create(
        user_id="u1",
        memory_key="language",
        content="Python",
        category="preference",
        scope=scope,
        source_type="explicit_user",
        source_conversation_id=None,
        request_id="r1",
    )
    assert memory.revision == 1
    assert store.user_revision("u1") == 1
    assert len(store.versions(memory.memory_id, "u1")) == 1
    assert store.query_one(
        "SELECT COUNT(*) FROM core_memory_audit_log WHERE memory_id=?",
        (memory.memory_id,),
    )[0] == 1

    updated = store.update(
        memory_id=memory.memory_id,
        user_id="u1",
        expected_revision=1,
        content="Rust",
        category="preference",
        request_id="r2",
    )
    assert updated.revision == 2
    with pytest.raises(MemoryRevisionConflict) as conflict:
        store.update(
            memory_id=memory.memory_id,
            user_id="u1",
            expected_revision=1,
            content="Go",
            category="preference",
            request_id="r3",
        )
    assert conflict.value.current_revision == 2
    assert store.get(memory.memory_id, "u1").content == "Rust"

    candidate = store.create_candidate(
        user_id="u1",
        memory_id=memory.memory_id,
        memory_key="language",
        proposed_content="TypeScript",
        category="preference",
        scope=scope,
        candidate_type="replace",
        expected_revision=2,
        source_conversation_id=None,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    accepted = store.accept_candidate(
        candidate_id=candidate.candidate_id,
        user_id="u1",
        content="TypeScript",
        category="preference",
        scope=scope,
        source_conversation_id=None,
        request_id="r4",
    )
    assert accepted.revision == 3
    assert store.get_candidate(candidate.candidate_id, "u1").status == "accepted"
    assert [item["revision"] for item in store.versions(memory.memory_id, "u1")] == [3, 2, 1]


def test_memory_tools_separate_explicit_writes_from_inferred_candidates(tmp_path):
    """验证 `memory_tools_separate_explicit_writes_from_inferred_candidates` 场景。"""
    database, conversation_id = _database(tmp_path)
    store = CoreMemoryStore(database)
    service = CoreMemoryService(store)
    register_builtin_tools()
    executor = _memory_executor(
        service,
        conversation_id,
        workspace_type="research",
        request_id="memory-proposal",
    )

    proposal = asyncio.run(
        executor.execute(
            "propose_core_memory",
            {
                "memory_key": "citation_style",
                "content": "Prefers APA citations",
                "category": "preference",
                "scope_type": "workspace",
            },
        )
    )

    assert proposal["status"] == "confirmation_required"
    assert proposal["candidate"]["status"] == "pending"
    assert proposal["candidate"]["workspace_type"] == "research"
    assert store.list_user("u1") == []
    assert len(store.list_candidates("u1")) == 1
    audit = store.query_one(
        "SELECT event_type,request_id FROM core_memory_audit_log WHERE user_id=?",
        ("u1",),
    )
    assert tuple(audit) == ("memory.candidate_created", "memory-proposal")


def test_delete_memory_tool_uses_memory_id_and_enforces_workspace_scope(tmp_path):
    """验证 `delete_memory_tool_uses_memory_id_and_enforces_workspace_scope` 场景。"""
    database, conversation_id = _database(tmp_path)
    store = CoreMemoryStore(database)
    service = CoreMemoryService(store)
    register_builtin_tools()
    research = _memory_executor(
        service,
        conversation_id,
        workspace_type="research",
        request_id="memory-create",
    )
    created = asyncio.run(
        research.execute(
            "save_core_memory",
            {
                "memory_key": "project_constraint",
                "content": "Use public datasets only",
                "category": "constraint",
                "scope_type": "workspace",
            },
        )
    )
    memory_id = created["memory"]["memory_id"]

    invalid = asyncio.run(
        research.execute("delete_core_memory", {"memory_key": "project_constraint"})
    )
    assert invalid["error"] == "invalid_tool_arguments"
    learning = _memory_executor(
        service,
        conversation_id,
        workspace_type="learning",
        request_id="cross-workspace-delete",
    )
    with pytest.raises(PermissionError, match="outside the current workspace"):
        asyncio.run(
            learning.execute("delete_core_memory", {"memory_id": memory_id})
        )
    assert store.get(memory_id, "u1") is not None

    deleted = asyncio.run(
        research.execute("delete_core_memory", {"memory_id": memory_id})
    )
    assert deleted == {"deleted": True}
    assert store.get(memory_id, "u1") is None


def test_candidate_accept_failure_rolls_back_memory_and_candidate(tmp_path):
    """验证 `candidate_accept_failure_rolls_back_memory_and_candidate` 场景。"""
    database, _conversation_id = _database(tmp_path)
    store = CoreMemoryStore(database)
    scope = MemoryScope("global")
    memory = store.create(
        user_id="u1",
        memory_key="goal",
        content="old",
        category="general",
        scope=scope,
        source_type="explicit_user",
        source_conversation_id=None,
        request_id="r1",
    )
    candidate = store.create_candidate(
        user_id="u1",
        memory_id=memory.memory_id,
        memory_key="goal",
        proposed_content="candidate",
        category="general",
        scope=scope,
        candidate_type="replace",
        expected_revision=1,
        source_conversation_id=None,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    store.update(
        memory_id=memory.memory_id,
        user_id="u1",
        expected_revision=1,
        content="concurrent",
        category="general",
        request_id="r2",
    )
    with pytest.raises(MemoryRevisionConflict):
        store.accept_candidate(
            candidate_id=candidate.candidate_id,
            user_id="u1",
            content="candidate",
            category="general",
            scope=scope,
            source_conversation_id=None,
            request_id="r3",
        )
    assert store.get(memory.memory_id, "u1").content == "concurrent"
    assert store.get(memory.memory_id, "u1").revision == 2
    assert store.get_candidate(candidate.candidate_id, "u1").status == "pending"
    assert len(store.versions(memory.memory_id, "u1")) == 2
    assert store.user_revision("u1") == 2


def test_core_memory_create_rolls_back_when_audit_fails(tmp_path, monkeypatch):
    """验证 `core_memory_create_rolls_back_when_audit_fails` 场景。"""
    database, _conversation_id = _database(tmp_path)
    store = CoreMemoryStore(database)

    def fail_audit(*_args, **_kwargs):
        """处理 `fail_audit` 相关逻辑。

        Args:
            _args: object => `_args` 参数。
            _kwargs: object => `_kwargs` 参数。
        """
        raise sqlite3.OperationalError("audit unavailable")

    monkeypatch.setattr(store, "_audit", fail_audit)
    with pytest.raises(sqlite3.OperationalError, match="audit unavailable"):
        store.create(
            user_id="u1",
            memory_key="rollback",
            content="must not persist",
            category="general",
            scope=MemoryScope("global"),
            source_type="explicit_user",
            source_conversation_id=None,
            request_id="r1",
        )
    assert store.list_user("u1") == []
    assert store.user_revision("u1") == 0
    assert store.query_one("SELECT COUNT(*) FROM core_memory_versions")[0] == 0


def test_research_project_profile_is_user_scoped_and_revisioned(tmp_path):
    """验证 `research_project_profile_is_user_scoped_and_revisioned` 场景。"""
    database, _conversation_id = _database(tmp_path)
    users = UserStore(database)
    assert users.create(
        UserRecord(id="u2", username="bob", password_hash="hash", status="active")
    )
    projects = ResearchProjectStore(database)
    project = projects.create_project("u1", "Project A")
    service = ResearchProjectProfileService(
        ResearchProjectProfileStore(database), projects
    )
    created = service.upsert(
        project["project_id"],
        "u1",
        agent_instructions="Use APA citations",
        expected_revision=0,
    )
    assert created["revision"] == 1
    with pytest.raises(KeyError):
        service.get(project["project_id"], "u2")

    def update(value):
        """更新 `update` 相关数据。"""
        try:
            return service.upsert(
                project["project_id"],
                "u1",
                agent_instructions=value,
                expected_revision=1,
            )
        except MemoryRevisionConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ("First", "Second")))
    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(isinstance(item, MemoryRevisionConflict) for item in results) == 1
    assert service.get(project["project_id"], "u1")["revision"] == 2


def test_classroom_binding_cannot_be_rebound_by_another_user(tmp_path):
    """验证 `classroom_binding_cannot_be_rebound_by_another_user` 场景。"""
    database, conversation_id = _database(tmp_path)
    users = UserStore(database)
    assert users.create(
        UserRecord(id="u2", username="bob", password_hash="hash", status="active")
    )
    bindings = ClassroomConversationStore(database)
    created = bindings.bind(
        conversation_id=conversation_id,
        user_id="u1",
        class_id="class-a",
        assignment_id="assignment-a",
    )
    assert created["class_id"] == "class-a"
    with pytest.raises(PermissionError):
        bindings.bind(
            conversation_id=conversation_id,
            user_id="u2",
            class_id="class-b",
        )
    assert bindings.get(conversation_id, "u1")["class_id"] == "class-a"
    assert bindings.get(conversation_id, "u2") is None


class _QueueRecorder:
    """封装 `_QueueRecorder` 的状态与行为。"""
    def __init__(self) -> None:
        """初始化 `_QueueRecorder` 实例。"""
        self.job_ids: list[str] = []

    def submit(self, job_id: str) -> None:
        """处理 `submit` 相关逻辑。"""
        self.job_ids.append(job_id)


class _EmptyResourceStore:
    """封装 `empty resource store` 数据持久化操作。"""
    def get_document(self, _resource_id, _user_id):
        """获取 `document` 相关数据。

        Args:
            _resource_id: object =>  resource ID。
            _user_id: object =>  user ID。

        Returns:
            object => 处理结果。
        """
        return None

    def get_dataset(self, _resource_id, _user_id):
        """获取 `dataset` 相关数据。

        Args:
            _resource_id: object =>  resource ID。
            _user_id: object =>  user ID。

        Returns:
            object => 处理结果。
        """
        return None


def test_workflow_tool_action_facade_chain_is_confirmed_and_idempotent(tmp_path):
    """验证 `workflow_tool_action_facade_chain_is_confirmed_and_idempotent` 场景。"""
    database, conversation_id = _database(tmp_path)
    projects = ResearchProjectStore(database)
    project = projects.create_project("u1", "Project A")
    frontier = FrontierTrackingStore(database)
    queue = _QueueRecorder()
    empty = _EmptyResourceStore()
    facade = ResearchWorkflowFacade(
        project_store=projects,
        frontier_store=frontier,
        frontier_service=queue,
        writing_store=empty,
        writing_service=None,
        data_store=empty,
        data_service=None,
    )
    actions = AgentActionStore(database)

    def validate(action):
        """校验 `validate` 相关数据。"""
        validate_research_action(
            action,
            project_store=projects,
            writing_store=empty,
            data_store=empty,
        )

    action_service = AgentActionService(
        actions,
        validators={"start_frontier_tracking": validate},
        executors={
            "start_frontier_tracking": lambda action: execute_research_action(
                action, facade
            )
        },
    )
    register_builtin_tools()
    scope = ResourceScope(project_id=project["project_id"])
    route = WorkspaceRoute(
        workspace_type="research",
        agent_profile_id="research.default.v1",
        skill_scopes=frozenset({"common", "research"}),
        tool_scopes=frozenset({"common", "research"}),
        prompt_key="research.v1",
        profile_policy="research.v1",
        memory_policy_id="research.v1",
        resource_scope=scope,
        action_policy="research.v1",
    )
    context = ToolExecutionContext(
        user_id="u1",
        conversation_id=conversation_id,
        workspace_route=route,
        authorized_resources=scope,
        conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(
            agent_action_service=action_service
        ),
        request_id="r1",
    )
    executor = CapabilityRuntime().compile(
        skill_scopes=route.skill_scopes,
        tool_scopes=route.tool_scopes,
        profile_fingerprint="research:1",
        policy_versions=("research.v1",),
    ).bind(context)

    forged = asyncio.run(
        executor.execute(
            "start_frontier_tracking",
            {"query": "agents", "project_id": "other", "user_id": "other"},
        )
    )
    assert forged["error"] == "invalid_tool_arguments"
    action = asyncio.run(
        executor.execute(
            "start_frontier_tracking",
            {"query": "agent memory", "time_window_years": "5", "max_results": "20"},
        )
    )
    assert action["status"] == "pending"
    assert action["arguments"]["project_id"] == project["project_id"]
    assert frontier.list_jobs(project["project_id"], "u1") == []
    assert queue.job_ids == []

    completed = action_service.approve_and_execute(action["action_id"], "u1")
    retried = action_service.approve_and_execute(action["action_id"], "u1")
    jobs = frontier.list_jobs(project["project_id"], "u1")
    assert completed["status"] == "succeeded"
    assert retried["result"]["job_id"] == completed["result"]["job_id"]
    assert [item["job_id"] for item in jobs] == [completed["result"]["job_id"]]
    assert queue.job_ids == [completed["result"]["job_id"]]


def test_research_action_rejects_resource_from_another_bound_project():
    """验证 `research_action_rejects_resource_from_another_bound_project` 场景。"""
    class _Projects:
        """封装 `_Projects` 的状态与行为。"""
        def get_project(self, project_id, user_id):
            """获取 `project` 相关数据。

            Args:
                project_id: object => 项目 ID。
                user_id: object => 用户 ID。

            Returns:
                object => 处理结果。
            """
            return {"project_id": project_id, "user_id": user_id, "status": "active"}

    class _Documents(_EmptyResourceStore):
        """封装 `_Documents` 的状态与行为。"""
        def get_document(self, _resource_id, user_id):
            """获取 `document` 相关数据。

            Args:
                _resource_id: object =>  resource ID。
                user_id: object => 用户 ID。

            Returns:
                object => 处理结果。
            """
            return {"project_id": "project-b", "user_id": user_id}

    action = {
        "user_id": "u1",
        "action_type": "start_research_writing",
        "arguments": {"document_id": "d1", "operation": "polish"},
        "resource_snapshot": {"project_id": "project-a"},
    }
    with pytest.raises(ValueError, match="outside the bound project"):
        validate_research_action(
            action,
            project_store=_Projects(),
            writing_store=_Documents(),
            data_store=_EmptyResourceStore(),
        )
