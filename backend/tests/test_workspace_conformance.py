# backend/tests/test_workspace_conformance.py

"""验证 Workspace 规范、授权、能力闭包和运行接口的一致性。"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.agent.agent import Agent
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.agent.skills.catalog import skill_declaration
from backend.agent.tools.skills import list_skill_definitions
from backend.agent.workspaces.definitions import WORKSPACE_DEFINITIONS
from backend.agent.workspaces.profile_registry import DEFAULT_PROFILE_REGISTRY
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.catalog import CAPABILITY_DECLARATIONS, ScopedToolView
from backend.agent.tools.tools import tr
from backend.agent.workspaces.capability_runtime import CapabilityRuntime
from backend.agent.workspaces.models import AgentTurnInput
from backend.agent.workspaces.runtime import WorkspaceRuntime
from backend.core.router.models import ResourceScope, TrustedIdentity, WorkspaceRoute
from backend.core.router.basic_router import route_workspace
from backend.core.router.context import (
    AttachmentAuthorization,
    ConversationContext,
    RoutingContext,
)
from backend.core.router.workspace_profiles import build_workspace_route
from backend.core.router.workspace_registry import resolve_workspace
from backend.core.services.teaching_context_adapter import TeachingContextAdapter
from backend.core.workspaces import WORKSPACE_CATALOG, WorkspaceAccessPolicy
from backend.core.utils.models import ParsedOutput


@pytest.mark.parametrize("definition", WORKSPACE_DEFINITIONS.values())
def test_registered_workspace_views_conform_to_the_canonical_definition(definition):
    """验证清单、运行 Profile 和路由均来自同一规范定义。"""
    descriptor = WORKSPACE_CATALOG[definition.workspace_type]
    assert descriptor.to_payload() == definition.to_manifest_payload()

    profile = DEFAULT_PROFILE_REGISTRY.resolve(
        definition.profile_id, definition.workspace_type
    )
    assert profile == definition.runtime_profile

    for role in definition.allowed_roles:
        identity = TrustedIdentity(f"{role}-id", role, role)
        registration = resolve_workspace(identity, definition.workspace_type)
        route = build_workspace_route(registration, ResourceScope())
        assert registration.definition_version == definition.definition_version
        assert route.agent_profile_id == definition.profile_id
        assert route.skill_scopes == definition.skill_scopes
        assert route.tool_scopes == definition.tool_scopes
        assert route.prompt_key == definition.prompt_key
        assert route.profile_policy == definition.profile_policy
        assert route.memory_policy_id == definition.memory_policy_id
        assert route.action_policy == definition.action_policy

        manifest = WorkspaceAccessPolicy.manifest(role)
        types = {item["type"] for item in manifest["workspaces"]}
        assert definition.workspace_type in types


def test_workspace_admission_fails_closed_for_unknown_workspace_and_role():
    """验证未知 Workspace 与无权角色均按拒绝处理。"""
    student = TrustedIdentity("u1", "student", "student")
    with pytest.raises(Exception, match="unsupported workspace"):
        resolve_workspace(student, "unknown")
    with pytest.raises(Exception, match="cannot access"):
        resolve_workspace(student, "teaching")
    assert WorkspaceAccessPolicy.allowed_workspaces("unknown") == ()


@pytest.mark.parametrize("workspace_type", tuple(WORKSPACE_DEFINITIONS))
def test_workspace_capabilities_have_schema_executor_and_resource_closure(workspace_type):
    """验证能力同时具备 Schema、执行器和所需资源授权。"""
    register_builtin_tools()
    definition = WORKSPACE_DEFINITIONS[workspace_type]
    empty = ScopedToolView.compile(
        tr, definition.tool_scopes, resource_capabilities=frozenset()
    )
    assert {schema["function"]["name"] for schema in empty.schemas} == empty.names

    if workspace_type == "research":
        assert "start_frontier_tracking" not in empty.names
        project = ScopedToolView.compile(
            tr,
            definition.tool_scopes,
            resource_capabilities=frozenset({"research_project"}),
        )
        assert "start_frontier_tracking" in project.names
    if workspace_type == "teaching":
        assert "get_teaching_context" not in empty.names


def test_compiled_skills_are_closed_over_the_resource_scoped_tool_view():
    """验证编译后的 Skill 不会依赖当前不可用的工具。"""
    register_builtin_tools()
    definition = WORKSPACE_DEFINITIONS["learning"]
    runtime = CapabilityRuntime()

    without_attachments = runtime.compile(
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        profile_fingerprint="learning:1",
        policy_versions=("learning.v1",),
        resource_capabilities=frozenset(),
        has_attachments=False,
    )
    assert "parse_pdf_attachment" not in without_attachments.capabilities.tool_names
    assert "parse_pdf_attachment" not in without_attachments.capabilities.skill_names

    with_attachments = runtime.compile(
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        profile_fingerprint="learning:1",
        policy_versions=("learning.v1",),
        resource_capabilities=frozenset({"attachments"}),
        has_attachments=True,
    )
    assert "parse_pdf_attachment" in with_attachments.capabilities.tool_names
    assert "parse_pdf_attachment" in with_attachments.capabilities.skill_names
    for skill in with_attachments.skills.definitions:
        assert set(skill.requires_tools) <= with_attachments.tools.names


def test_bound_executor_rechecks_required_resource_capabilities():
    """验证执行器会再次核对工具所需资源能力。"""
    register_builtin_tools()
    definition = WORKSPACE_DEFINITIONS["learning"]
    compiled = CapabilityRuntime().compile(
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        profile_fingerprint="learning:1",
        policy_versions=("learning.v1",),
        resource_capabilities=frozenset({"attachments"}),
        has_attachments=True,
    )
    scope = ResourceScope()
    route = WorkspaceRoute(
        workspace_type="learning",
        agent_profile_id=definition.profile_id,
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        prompt_key=definition.prompt_key,
        profile_policy=definition.profile_policy,
        memory_policy_id=definition.memory_policy_id,
        resource_scope=scope,
        action_policy=definition.action_policy,
    )
    context = ToolExecutionContext(
        user_id="u1",
        conversation_id="c1",
        workspace_route=route,
        authorized_resources=scope,
        conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(),
        request_id="r1",
    )
    denied = asyncio.run(
        compiled.bind(context).execute(
            "parse_pdf_attachment", {"attachment_id": "a1", "query": "summary"}
        )
    )
    assert denied == {
        "ok": False,
        "error": "resource_capability_required",
        "tool": "parse_pdf_attachment",
        "required": ["attachments"],
    }


def test_run_spec_and_manifest_are_serializable_and_share_the_production_compiler():
    """验证运行清单可序列化且评测复用生产编译路径。"""
    register_builtin_tools()
    identity = TrustedIdentity("u1", "student", "student")
    registration = resolve_workspace(identity, "learning")
    scope = ResourceScope(
        metadata={"conversation_id": "c1"},
        policy_version="resource.v2",
        revision_set={"learning_state": "7"},
        audit_markers=("authorized-by:test",),
    )
    route = build_workspace_route(registration, scope)
    turn = AgentTurnInput(
        route=route,
        identity=identity,
        conversation_id="c1",
        current_message="explain binary search",
        request_metadata={"request_id": "request-1", "run_id": "run-1"},
    )
    runtime = WorkspaceRuntime(AgentRuntimeDependencies())

    executable = runtime.prepare(turn)
    serialized = json.loads(json.dumps(executable.spec.to_dict()))
    assert serialized["manifest"]["definition_version"] == 1
    assert serialized["manifest"]["request_id"] == "request-1"
    assert serialized["manifest"]["run_id"] == "run-1"
    assert serialized["manifest"]["runtime_identity"] == "u1"
    assert serialized["manifest"]["policy_versions"]["resource"] == "resource.v2"
    assert serialized["manifest"]["resource_revisions"] == {"learning_state": "7"}
    assert "tool_executor" not in serialized
    assert "execution_context" not in serialized
    assert executable.tool_executor is executable.binding.tool_executor
    assert executable.execution_context is executable.binding.execution_context

    evaluation_spec = runtime.prepare_evaluation(turn)
    assert evaluation_spec == executable.spec
    assert evaluation_spec.manifest.context_fingerprint
    assert evaluation_spec.manifest.capability_fingerprint


def test_core_router_derives_capabilities_from_authorized_resource_references():
    """验证路由只从已授权的资源引用派生能力。"""
    identity = TrustedIdentity("u1", "student", "student")
    route = route_workspace(
        identity,
        RoutingContext(
            ConversationContext("c1", "u1", "research", "project-1"),
            attachments=AttachmentAuthorization(("attachment-1",)),
            project_owned=True,
        ),
    )
    assert route.resource_scope.capabilities >= {
        "research_project",
        "attachments",
    }


def test_every_registered_capability_is_versioned_and_actions_are_explicit():
    """验证注册能力均有版本且高影响动作被显式声明。"""
    register_builtin_tools()
    assert set(tr.registered_tools) == set(CAPABILITY_DECLARATIONS)
    assert all(item.version >= 1 for item in CAPABILITY_DECLARATIONS.values())

    research_actions = {
        name
        for name, item in CAPABILITY_DECLARATIONS.items()
        if item.kind == "action"
    }
    assert research_actions == {
        "start_frontier_tracking",
        "start_research_writing",
        "start_dataset_analysis",
    }
    for name in research_actions:
        declaration = CAPABILITY_DECLARATIONS[name]
        assert declaration.scope == "research"
        assert declaration.required_resource_capabilities == {"research_project"}
        assert declaration.approval_mode == "approval_required"
        assert declaration.policy_version == "research.v1"

    skill_declarations = [
        skill_declaration(skill) for skill in list_skill_definitions()
    ]
    assert all(item.version >= 1 and item.scope for item in skill_declarations)
    attachment_skills = {
        item.name: item for item in skill_declarations if item.name.startswith("parse_")
    }
    assert attachment_skills
    assert all(
        item.required_resource_capabilities == {"attachments"}
        for item in attachment_skills.values()
    )


def test_teaching_context_capability_is_read_only_scoped_and_server_bound():
    """验证教学上下文能力只读、受资源约束且由服务端绑定身份。"""

    class Reader:
        """提供测试用教学上下文读取器。"""

        def read_teaching_context(self, *, user_id, class_id, assignment_id):
            """回显服务端传入的可信教学资源参数。"""
            return {
                "user_id": user_id,
                "class_id": class_id,
                "assignment_id": assignment_id,
            }

    register_builtin_tools()
    definition = WORKSPACE_DEFINITIONS["teaching"]
    compiled = CapabilityRuntime().compile(
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        profile_fingerprint="teaching:1",
        policy_versions=("teaching.v1",),
        resource_capabilities=frozenset({"classroom"}),
    )
    assert "get_teaching_context" in compiled.capabilities.tool_names
    scope = ResourceScope(class_id="class-1", capabilities=frozenset({"classroom"}))
    route = WorkspaceRoute(
        workspace_type="teaching",
        agent_profile_id=definition.profile_id,
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        prompt_key=definition.prompt_key,
        profile_policy=definition.profile_policy,
        memory_policy_id=definition.memory_policy_id,
        resource_scope=scope,
        action_policy=definition.action_policy,
    )
    context = ToolExecutionContext(
        user_id="teacher-1",
        conversation_id="c1",
        workspace_route=route,
        authorized_resources=scope,
        conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(
            teaching_context_reader=Reader()
        ),
        request_id="r1",
    )
    executor = compiled.bind(context)
    result = asyncio.run(executor.execute("get_teaching_context", {}))
    assert result == {
        "user_id": "teacher-1",
        "class_id": "class-1",
        "assignment_id": None,
    }
    forged = asyncio.run(
        executor.execute("get_teaching_context", {"user_id": "other"})
    )
    assert forged["error"] == "invalid_tool_arguments"


def test_workspace_runtime_hides_teaching_context_without_a_bound_classroom():
    """验证未绑定班级时不会向模型暴露教学上下文工具。"""
    register_builtin_tools()
    identity = TrustedIdentity("teacher-1", "teacher", "teacher")
    registration = resolve_workspace(identity, "teaching")
    unbound_route = build_workspace_route(registration, ResourceScope())
    unbound_turn = AgentTurnInput(
        route=unbound_route,
        identity=identity,
        conversation_id="c1",
        current_message="summarize my class",
        request_metadata={"request_id": "r1"},
    )
    runtime = WorkspaceRuntime(AgentRuntimeDependencies())
    assert "get_teaching_context" not in runtime.prepare(unbound_turn).run_metadata[
        "tool_names"
    ]

    bound_route = build_workspace_route(
        registration, ResourceScope(class_id="class-1")
    )
    bound_turn = AgentTurnInput(
        route=bound_route,
        identity=identity,
        conversation_id="c1",
        current_message="summarize my class",
        request_metadata={"request_id": "r2"},
    )
    assert "get_teaching_context" in runtime.prepare(bound_turn).run_metadata[
        "tool_names"
    ]


def test_teaching_context_adapter_revalidates_teacher_ownership_and_state():
    """验证教学适配器在读取时重新校验教师归属和班级状态。"""

    class Store:
        """提供测试用班级和作业存储。"""

        def get_class(self, class_id):
            """返回测试班级。"""
            if class_id == "class-1":
                return {
                    "class_id": class_id,
                    "owner_teacher_id": "teacher-1",
                    "name": "Algorithms",
                    "canonical_course": "Algorithms",
                    "term": "2026",
                    "status": "active",
                }
            return None

        def get_assignment(self, _assignment_id):
            """返回空作业结果。"""
            return None

    adapter = TeachingContextAdapter(Store())
    result = adapter.read_teaching_context(
        user_id="teacher-1", class_id="class-1", assignment_id=None
    )
    assert result["classroom"]["name"] == "Algorithms"
    with pytest.raises(ValueError, match="no longer authorized"):
        adapter.read_teaching_context(
            user_id="other", class_id="class-1", assignment_id=None
        )


def test_bound_teaching_context_errors_are_returned_as_tool_results():
    """验证教学上下文异常会转换为结构化工具结果。"""

    class Reader:
        """提供始终拒绝读取的测试适配器。"""

        def read_teaching_context(self, **_kwargs):
            """模拟资源在执行前失去授权。"""
            raise ValueError("teaching classroom is no longer authorized")

    register_builtin_tools()
    definition = WORKSPACE_DEFINITIONS["teaching"]
    scope = ResourceScope(class_id="class-1", capabilities=frozenset({"classroom"}))
    route = WorkspaceRoute(
        workspace_type="teaching",
        agent_profile_id=definition.profile_id,
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        prompt_key=definition.prompt_key,
        profile_policy=definition.profile_policy,
        memory_policy_id=definition.memory_policy_id,
        resource_scope=scope,
        action_policy=definition.action_policy,
    )
    compiled = CapabilityRuntime().compile(
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        profile_fingerprint="teaching:1",
        policy_versions=("teaching.v1",),
        resource_capabilities=frozenset({"classroom"}),
    )
    context = ToolExecutionContext(
        user_id="teacher-1",
        conversation_id="c1",
        workspace_route=route,
        authorized_resources=scope,
        conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(teaching_context_reader=Reader()),
        request_id="r1",
    )

    result = asyncio.run(
        compiled.bind(context).execute("get_teaching_context", {})
    )

    assert result == {
        "ok": False,
        "error": "tool_execution_error",
        "tool": "get_teaching_context",
        "detail": "teaching classroom is no longer authorized",
    }


def test_workspace_compiler_rejects_undeclared_resource_capabilities():
    """验证编译器拒绝 Workspace 未声明的伪造资源能力。"""
    identity = TrustedIdentity("u1", "student", "student")
    definition = WORKSPACE_DEFINITIONS["learning"]
    scope = ResourceScope(capabilities=frozenset({"forged_capability"}))
    route = WorkspaceRoute(
        workspace_type="learning",
        agent_profile_id=definition.profile_id,
        skill_scopes=definition.skill_scopes,
        tool_scopes=definition.tool_scopes,
        prompt_key=definition.prompt_key,
        profile_policy=definition.profile_policy,
        memory_policy_id=definition.memory_policy_id,
        resource_scope=scope,
        action_policy=definition.action_policy,
    )
    turn = AgentTurnInput(
        route=route,
        identity=identity,
        conversation_id="c1",
        current_message="hello",
        request_metadata={"request_id": "r1"},
    )
    with pytest.raises(ValueError, match="undeclared resource capabilities"):
        WorkspaceRuntime(AgentRuntimeDependencies()).prepare(turn)


def test_executable_run_preserves_agent_run_and_stream_interfaces():
    """验证可执行运行对象兼容 Agent 普通与流式接口。"""

    class StreamParser:
        """提供测试用增量响应解析器。"""
        raw_text = ""

        def feed(self, chunk):
            """接收一个增量内容片段。"""
            self.raw_text += chunk
            return [("content", chunk)]

        def finish(self):
            """结束解析且不产生额外事件。"""
            return []

    class Provider:
        """提供普通与流式生成接口的测试模型。"""

        async def generate(self, _messages, _schemas):
            """返回固定普通响应。"""
            return "compiled answer"

        async def generate_stream(self, _messages, _schemas):
            """生成固定流式响应。"""
            yield "compiled answer"

        def create_stream_parser(self):
            """创建测试流式解析器。"""
            return StreamParser()

        def parse_output(self, response, _schemas):
            """把响应转换为 Agent 解析结果。"""
            return ParsedOutput(content=response)

    identity = TrustedIdentity("u1", "student", "student")
    registration = resolve_workspace(identity, "learning")
    route = build_workspace_route(
        registration, ResourceScope(metadata={"conversation_id": "c1"})
    )
    turn = AgentTurnInput(
        route=route,
        identity=identity,
        conversation_id="c1",
        current_message="hello",
        request_metadata={"request_id": "r1"},
    )
    executable = WorkspaceRuntime(AgentRuntimeDependencies()).prepare(turn)
    agent = object.__new__(Agent)
    agent.llm_provider = Provider()

    messages = asyncio.run(agent.run(executable))
    assert messages[-1]["content"] == "compiled answer"

    async def collect_stream():
        """收集 Agent 产生的全部流式事件。"""
        return [event async for event in agent.run_stream(executable)]

    events = asyncio.run(collect_stream())
    assert events[-1].event == "complete"
    assert events[-1].data["messages"][-1]["content"] == "compiled answer"


def test_stream_emits_heartbeat_while_model_has_no_visible_output():
    """模型长时间无可见 token 时仍持续产生 SSE 保活事件。"""

    class StreamParser:
        raw_text = ""

        def feed(self, chunk):
            self.raw_text += chunk
            return [("content", chunk)]

        def finish(self):
            return []

    class SlowProvider:
        async def generate_stream(self, _messages, _schemas):
            await asyncio.sleep(0.03)
            yield "delayed answer"

        def create_stream_parser(self):
            return StreamParser()

        def parse_output(self, response, _schemas):
            return ParsedOutput(content=response)

    identity = TrustedIdentity("u1", "student", "student")
    registration = resolve_workspace(identity, "learning")
    route = build_workspace_route(registration, ResourceScope())
    executable = WorkspaceRuntime(AgentRuntimeDependencies()).prepare(
        AgentTurnInput(
            route=route,
            identity=identity,
            conversation_id="c1",
            current_message="hello",
            request_metadata={"request_id": "r1"},
        )
    )
    agent = object.__new__(Agent)
    agent.llm_provider = SlowProvider()
    agent.stream_heartbeat_seconds = 0.005

    async def collect_stream():
        return [event async for event in agent.run_stream(executable)]

    events = asyncio.run(collect_stream())
    event_names = [event.event for event in events]
    assert "heartbeat" in event_names
    assert event_names.index("heartbeat") < event_names.index("content")
    assert event_names[-1] == "complete"
