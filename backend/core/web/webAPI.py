# backend/core/web/webAPI.py

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.agent.agent import Agent
from backend.agent.memories.kg_loader import ensure_knowledge_graph_seeded
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.learning.knowledge_map_service import KnowledgeMapService
from backend.agent.memories.kp_resolver import KnowledgePointResolver
from backend.agent.memories.core_memory_service import CoreMemoryService
from backend.agent.memories.paths import (
    KNOWLEDGE_GRAPH_DB_PATH,
    LEARNING_EVIDENCE_DB_PATH,
    MASTERY_DB_PATH,
    USER_DB_PATH,
)
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.agent.memories.profile_projection import ProfileProjection
from backend.agent.mm import (
    MMConfig,
    MultimodalIngestionService,
    MultimodalSessionService,
)
from backend.agent.rag.lifecycle import RAGApplicationLifecycle
from backend.agent.tools.learning.mastery import EsaMasteryStore
from backend.core.services.auth_service import AuthService
from backend.core.services.agent_action_service import AgentActionService
from backend.core.services.auxiliary_llm_service import AuxiliaryLLMClient
from backend.core.services.conversation_compression_service import (
    ConversationCompressionService,
)
from backend.core.services.email_verification_service import (
    EmailServiceSender,
    EmailVerificationService,
    VerificationPolicy,
)
from backend.core.services.frontier_tracking_service import FrontierTrackingService
from backend.core.services.lsp_service import LspService
from backend.core.services.research_data_service import ResearchDataService
from backend.core.services.research_project_profile_service import (
    ResearchProjectProfileService,
)
from backend.core.services.research_writing_service import ResearchWritingService
from backend.core.services.teaching_analysis_service import TeachingAnalysisService
from backend.core.services.user_attachment_service import UserAttachmentStore
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.agent_action_store import AgentActionStore
from backend.core.stores.classroom_conversation_store import ClassroomConversationStore
from backend.core.stores.core_memory_store import CoreMemoryStore
from backend.core.stores.conversation_summary_store import ConversationSummaryStore
from backend.core.stores.email_verification_store import EmailVerificationStore
from backend.core.stores.frontier_tracking_store import FrontierTrackingStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.profile_store import ProfileStore
from backend.core.stores.research_data_store import ResearchDataStore
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.research_project_profile_store import (
    ResearchProjectProfileStore,
)
from backend.core.stores.research_writing_store import ResearchWritingStore
from backend.core.stores.schedule_store import ScheduleStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.teaching_store import TeachingStore
from backend.core.stores.user_course_store import UserCourseStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.config import (
    AGENT_LOOP_TIME,
    API_PREFIX,
    AUXILIARY_MODEL_BASE_URL,
    AUXILIARY_MODEL_NAME,
    AUXILIARY_MODEL_REQUEST_TIMEOUT,
    CONVERSATION_COMPRESSION_ENABLED,
    CONVERSATION_COMPRESSION_KEEP_RECENT_MESSAGES,
    CONVERSATION_COMPRESSION_MAX_INPUT_CHARS,
    CONVERSATION_COMPRESSION_MAX_OUTPUT_TOKENS,
    CONVERSATION_COMPRESSION_MIN_MESSAGES,
    CONVERSATION_COMPRESSION_MIN_NEW_MESSAGES,
    CONVERSATION_COMPRESSION_SCAN_INTERVAL,
    CONVERSATION_OFFLINE_AFTER_SECONDS,
    CORS_ALLOWED_ORIGINS,
    EMAIL_CODE_COOLDOWN_SECONDS,
    EMAIL_CODE_EMAIL_HOURLY_LIMIT,
    EMAIL_CODE_IP_HOURLY_LIMIT,
    EMAIL_CODE_MAX_ATTEMPTS,
    EMAIL_CODE_TTL_SECONDS,
    EMAIL_PROVIDER,
    EMAIL_SERVICE_TOKEN,
    EMAIL_SERVICE_URL,
    EMAIL_VERIFICATION_SECRET,
    ENABLE_LEGACY_API_ROUTES,
    FORWARDED_ALLOW_IPS,
    LSP_ALLOWED_ORIGINS,
    LSP_DOCUMENT_FILENAMES,
    LSP_ENABLED,
    LSP_MAX_MESSAGE_BYTES,
    LSP_MAX_SESSIONS,
    LSP_MAX_SESSIONS_PER_USER,
    LSP_SERVER_COMMANDS,
    MODEL_DTYPE,
    MODEL_GPU_MEMORY_UTILIZATION,
    MODEL_KV_CACHE_DTYPE,
    MODEL_MAX_MODEL_LENGTH,
    MODEL_MAX_NUM_SEQS,
    MODEL_MAX_OUTPUT_TOKENS,
    MODEL_PATH,
    MODEL_QUANTIZATION,
    MODEL_TENSOR_PARALLEL_SIZE,
    TRUSTED_HOSTS,
    USER_ATTACHMENT_MAX_BYTES,
    USER_ATTACHMENT_ROOT,
    validate_startup_config,
)
from backend.core.web.concurrency import ConversationTurnCoordinator
from backend.core.web.routers import (
    agent_actions,
    auth,
    chat,
    groups,
    learning,
    lsp,
    memories,
    preferences,
    research,
    research_capabilities,
    schedule,
    student_teaching,
    teaching,
    workspaces,
)
from backend.core.workflows.research import (
    RESEARCH_ACTION_TYPES,
    ResearchWorkflowFacade,
    execute_research_action,
    validate_research_action,
)

DB_PATH = USER_DB_PATH
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup_config()
    mm_config = MMConfig.from_env()
    mm_config.validate_startup()
    # 先让各 Store 补齐老库的新增列，再由版本迁移原子重建外键表。
    app.state.user_store = UserStore(DB_PATH)
    app.state.group_store = GroupStore(DB_PATH)
    app.state.chat_store = ChatStore(DB_PATH)
    app.state.session_store = SessionStore(DB_PATH)
    app.state.profile_store = ProfileStore(DB_PATH)
    app.state.user_attachment_store = UserAttachmentStore(
        USER_ATTACHMENT_ROOT,
        max_bytes=USER_ATTACHMENT_MAX_BYTES,
    )
    app.state.teaching_store = TeachingStore(DB_PATH)
    app.state.knowledge_graph_store = KnowledgeGraphStore(KNOWLEDGE_GRAPH_DB_PATH)
    app.state.mastery_store = EsaMasteryStore(MASTERY_DB_PATH)
    app.state.learning_evidence_store = LearningEvidenceStore(LEARNING_EVIDENCE_DB_PATH)
    app.state.learning_state_service = LearningStateService(
        kg_store=app.state.knowledge_graph_store,
        mastery_store=app.state.mastery_store,
        evidence_store=app.state.learning_evidence_store,
    )
    app.state.knowledge_map_service = KnowledgeMapService(
        kg_store=app.state.knowledge_graph_store,
        mastery_store=app.state.mastery_store,
        evidence_store=app.state.learning_evidence_store,
    )

    run_migrations(DB_PATH)
    app.state.core_memory_store = CoreMemoryStore(DB_PATH)
    app.state.profile_projection = ProfileProjection(
        app.state.user_store,
        app.state.profile_store,
    )
    app.state.core_memory_service = CoreMemoryService(
        app.state.core_memory_store,
        projection=app.state.profile_projection,
    )
    app.state.research_project_store = ResearchProjectStore(DB_PATH)
    app.state.classroom_conversation_store = ClassroomConversationStore(DB_PATH)
    app.state.research_project_profile_store = ResearchProjectProfileStore(DB_PATH)
    app.state.research_project_profile_service = ResearchProjectProfileService(
        app.state.research_project_profile_store,
        app.state.research_project_store,
    )
    app.state.frontier_tracking_store = FrontierTrackingStore(DB_PATH)
    app.state.frontier_tracking_service = FrontierTrackingService(
        app.state.frontier_tracking_store
    )
    app.state.research_writing_store = ResearchWritingStore(DB_PATH)
    app.state.research_data_store = ResearchDataStore(DB_PATH)
    app.state.research_data_service = ResearchDataService(
        app.state.research_data_store,
        DB_PATH.parent / "research_data",
    )
    app.state.research_workflow_facade = ResearchWorkflowFacade(
        project_store=app.state.research_project_store,
        frontier_store=app.state.frontier_tracking_store,
        frontier_service=app.state.frontier_tracking_service,
        writing_store=app.state.research_writing_store,
        writing_service=None,
        data_store=app.state.research_data_store,
        data_service=app.state.research_data_service,
    )
    app.state.email_verification_store = EmailVerificationStore(DB_PATH)
    app.state.email_verification_service = None
    if EMAIL_PROVIDER == "service":
        # validate_startup_config has already guaranteed these values.
        if (
            not EMAIL_SERVICE_URL
            or not EMAIL_SERVICE_TOKEN
            or not EMAIL_VERIFICATION_SECRET
        ):
            raise RuntimeError("邮件服务配置不完整")
        app.state.email_verification_service = EmailVerificationService(
            store=app.state.email_verification_store,
            sender=EmailServiceSender(
                base_url=EMAIL_SERVICE_URL,
                service_token=EMAIL_SERVICE_TOKEN,
            ),
            digest_secret=EMAIL_VERIFICATION_SECRET,
            policy=VerificationPolicy(
                ttl_seconds=EMAIL_CODE_TTL_SECONDS,
                cooldown_seconds=EMAIL_CODE_COOLDOWN_SECONDS,
                email_hourly_limit=EMAIL_CODE_EMAIL_HOURLY_LIMIT,
                ip_hourly_limit=EMAIL_CODE_IP_HOURLY_LIMIT,
                max_attempts=EMAIL_CODE_MAX_ATTEMPTS,
            ),
        )
    app.state.user_course_store = UserCourseStore(DB_PATH)
    app.state.schedule_store = ScheduleStore(DB_PATH)
    app.state.user_presence_store = UserPresenceStore(DB_PATH)
    app.state.lsp_service = LspService(
        commands=LSP_SERVER_COMMANDS,
        filenames=LSP_DOCUMENT_FILENAMES,
        enabled=LSP_ENABLED,
        max_sessions=LSP_MAX_SESSIONS,
        max_sessions_per_user=LSP_MAX_SESSIONS_PER_USER,
        max_message_bytes=LSP_MAX_MESSAGE_BYTES,
    )
    app.state.conversation_summary_store = ConversationSummaryStore(DB_PATH)
    app.state.conversation_turn_coordinator = ConversationTurnCoordinator(DB_PATH)
    app.state.auxiliary_llm_client = AuxiliaryLLMClient(
        base_url=AUXILIARY_MODEL_BASE_URL,
        model=AUXILIARY_MODEL_NAME,
        timeout=AUXILIARY_MODEL_REQUEST_TIMEOUT,
    )
    if not await app.state.auxiliary_llm_client.is_ready():
        logger.warning("辅助 Qwen 服务尚未就绪，课表解析与离线上下文压缩将暂时不可用")
    app.state.research_writing_service = ResearchWritingService(
        app.state.research_writing_store,
        app.state.auxiliary_llm_client,
    )
    app.state.research_workflow_facade.writing_service = (
        app.state.research_writing_service
    )
    app.state.agent_action_store = AgentActionStore(DB_PATH)

    def _validate_research_action(action: dict) -> None:
        validate_research_action(
            action,
            project_store=app.state.research_project_store,
            writing_store=app.state.research_writing_store,
            data_store=app.state.research_data_store,
        )

    def _execute_research_action(action: dict) -> dict:
        return execute_research_action(action, app.state.research_workflow_facade)

    app.state.agent_action_service = AgentActionService(
        app.state.agent_action_store,
        validators={name: _validate_research_action for name in RESEARCH_ACTION_TYPES},
        executors={name: _execute_research_action for name in RESEARCH_ACTION_TYPES},
    )
    app.state.teaching_analysis_service = TeachingAnalysisService(
        app.state.teaching_store,
        app.state.auxiliary_llm_client,
    )

    # Recover durable SQLite queues before vLLM forks its worker processes.
    # Performing these writes after the GPU workers exist can leave the shared
    # NFS-backed database waiting on inherited SQLite locks during startup.
    for job_id in app.state.frontier_tracking_store.requeue_interrupted():
        app.state.frontier_tracking_service.submit(job_id)
    for job_id in app.state.research_writing_store.requeue_interrupted():
        app.state.research_writing_service.submit(job_id)
    for job_id in app.state.research_data_store.requeue_interrupted():
        app.state.research_data_service.submit(job_id)

    synced_points, synced_edges = ensure_knowledge_graph_seeded(
        app.state.knowledge_graph_store
    )
    if app.state.knowledge_graph_store.count_points() <= 0:
        raise RuntimeError("Knowledge Graph 初始化失败：未从 YAML 加载任何知识点")
    logger.info(
        "Knowledge Graph 已同步：points=%s, edges=%s",
        synced_points,
        synced_edges,
    )
    app.state.kp_resolver = KnowledgePointResolver(app.state.knowledge_graph_store)
    app.state.auth = AuthService(
        app.state.user_store,
        app.state.session_store,
    )
    app.state.agent = Agent(
        loop_times=AGENT_LOOP_TIME,
        model_path=MODEL_PATH,
        dtype=MODEL_DTYPE,
        kv_cache_dtype=MODEL_KV_CACHE_DTYPE,
        gpu_memory_utilization=MODEL_GPU_MEMORY_UTILIZATION,
        max_model_len=MODEL_MAX_MODEL_LENGTH,
        max_output_tokens=MODEL_MAX_OUTPUT_TOKENS,
        max_num_seqs=MODEL_MAX_NUM_SEQS,
        quantization=MODEL_QUANTIZATION,
        tensor_parallel_size=MODEL_TENSOR_PARALLEL_SIZE,
    )
    app.state.profile_builder = ProfileBuilder(
        user_store=app.state.user_store,
        mastery_store=app.state.mastery_store,
        kg_store=app.state.knowledge_graph_store,
        profile_store=app.state.profile_store,
        evidence_store=app.state.learning_evidence_store,
    )
    app.state.conversation_compression_service = ConversationCompressionService(
        llm_client=app.state.auxiliary_llm_client,
        summary_store=app.state.conversation_summary_store,
        offline_after_seconds=CONVERSATION_OFFLINE_AFTER_SECONDS,
        scan_interval_seconds=CONVERSATION_COMPRESSION_SCAN_INTERVAL,
        min_messages=CONVERSATION_COMPRESSION_MIN_MESSAGES,
        min_new_messages=CONVERSATION_COMPRESSION_MIN_NEW_MESSAGES,
        keep_recent_messages=CONVERSATION_COMPRESSION_KEEP_RECENT_MESSAGES,
        max_input_chars=CONVERSATION_COMPRESSION_MAX_INPUT_CHARS,
        max_output_tokens=CONVERSATION_COMPRESSION_MAX_OUTPUT_TOKENS,
        enabled=CONVERSATION_COMPRESSION_ENABLED,
    )
    app.state.conversation_compression_service.start()
    app.state.rag_lifecycle = RAGApplicationLifecycle()
    app.state.rag_service = app.state.rag_lifecycle.start()
    app.state.mm_sessions = (
        MultimodalSessionService(MultimodalIngestionService(mm_config))
        if mm_config.enabled
        else None
    )
    app.state.frontier_tracking_service.start(recover_interrupted=False)
    app.state.research_writing_service.start(recover_interrupted=False)
    app.state.research_data_service.start(recover_interrupted=False)
    try:
        yield
    finally:
        await app.state.frontier_tracking_service.stop()
        await app.state.research_writing_service.stop()
        await app.state.research_data_service.stop()
        if app.state.email_verification_service is not None:
            await app.state.email_verification_service.close()
        if app.state.mm_sessions is not None:
            await app.state.mm_sessions.close()
        app.state.rag_lifecycle.close()
        await app.state.conversation_compression_service.stop()
        await app.state.auxiliary_llm_client.close()
        app.state.agent.llm_provider.engine.shutdown()


business_router = APIRouter()
business_router.include_router(auth.router)
business_router.include_router(agent_actions.router)
business_router.include_router(chat.router)
business_router.include_router(groups.router)
business_router.include_router(preferences.router)
business_router.include_router(preferences.profile_router)
business_router.include_router(preferences.memory_settings_router)
business_router.include_router(learning.router)
business_router.include_router(lsp.router)
business_router.include_router(schedule.router)
business_router.include_router(memories.router)
business_router.include_router(workspaces.router)
business_router.include_router(research.router)
business_router.include_router(research_capabilities.router)
business_router.include_router(teaching.router)
business_router.include_router(student_teaching.router)

api_router = APIRouter()
api_router.include_router(business_router)


@api_router.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    """Process liveness only; deliberately avoids models, RAG, and databases."""

    return {"status": "ok"}


@api_router.get("/internal/metrics", tags=["operations"])
def get_internal_metrics(request: Request):
    """Expose the in-process profile metrics snapshot for operations."""

    profile_builder = getattr(request.app.state, "profile_builder", None)
    if profile_builder is None:
        return {"error": "profile_builder not initialized"}
    return profile_builder.get_metrics_snapshot()


@api_router.get(
    "/internal/metrics/prometheus",
    response_class=PlainTextResponse,
    tags=["operations"],
)
def get_metrics_prometheus(request: Request):
    """Expose profile metrics using the Prometheus text format."""

    profile_builder = getattr(request.app.state, "profile_builder", None)
    if profile_builder is None:
        return "profile_builder not initialized\n"
    return profile_builder.get_metrics_prometheus()


def create_app(
    *,
    app_lifespan=lifespan,
    api_prefix: str = API_PREFIX,
    cors_allowed_origins: tuple[str, ...] = CORS_ALLOWED_ORIGINS,
    trusted_hosts: tuple[str, ...] = TRUSTED_HOSTS,
    forwarded_allow_ips: tuple[str, ...] = FORWARDED_ALLOW_IPS,
    lsp_allowed_origins: tuple[str, ...] = LSP_ALLOWED_ORIGINS,
    enable_legacy_routes: bool = ENABLE_LEGACY_API_ROUTES,
) -> FastAPI:
    """Build the HTTP application with an explicit reverse-proxy contract."""

    application = FastAPI(lifespan=app_lifespan)
    application.state.lsp_allowed_origins = tuple(lsp_allowed_origins)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Cache-Control",
            "Content-Type",
            "Last-Event-ID",
        ],
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(trusted_hosts),
        www_redirect=False,
    )
    application.add_middleware(
        ProxyHeadersMiddleware,
        trusted_hosts=list(forwarded_allow_ips),
    )

    # Canonical production API.  Nginx must preserve this prefix upstream.
    application.include_router(api_router, prefix=api_prefix)

    # Keep pre-existing clients functional during deployment.  These aliases
    # are deliberately omitted from OpenAPI so /api remains canonical.
    if enable_legacy_routes:
        application.include_router(business_router, include_in_schema=False)
        application.add_api_route(
            "/internal/metrics",
            get_internal_metrics,
            methods=["GET"],
            include_in_schema=False,
        )
        application.add_api_route(
            "/internal/metrics/prometheus",
            get_metrics_prometheus,
            methods=["GET"],
            response_class=PlainTextResponse,
            include_in_schema=False,
        )

    return application


app = create_app()


@app.get("/", include_in_schema=False)
def read_root():
    return {"Hello": "World"}
