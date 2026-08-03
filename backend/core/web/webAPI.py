# backend/core/web/webAPI.py

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agent.agent import Agent
from backend.core.services.auth_service import AuthService
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.config import (
    AGENT_LOOP_TIME,
    MODEL_DTYPE,
    MODEL_GPU_MEMORY_UTILIZATION,
    MODEL_KV_CACHE_DTYPE,
    MODEL_MAX_MODEL_LENGTH,
    MODEL_MAX_NUM_SEQS,
    MODEL_PATH,
    MODEL_QUANTIZATION,
    MODEL_TENSOR_PARALLEL_SIZE,
)
from backend.core.web.routers import auth, chat, preferences

DB_PATH = Path(__file__).resolve().parent.parent / "stores" / "data" / "user.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.user_store = UserStore(DB_PATH)
    app.state.session_store = SessionStore(DB_PATH)
    app.state.chat_store = ChatStore(DB_PATH)
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
        max_num_seqs=MODEL_MAX_NUM_SEQS,
        quantization=MODEL_QUANTIZATION,
        tensor_parallel_size=MODEL_TENSOR_PARALLEL_SIZE,
    )
    try:
        yield
    finally:
        app.state.agent.llm_provider.engine.shutdown()


app = FastAPI(lifespan=lifespan)

# 允许 Flutter web / 前端跨域调用 开发阶段放开所有来源
# 部署时应把 allow_origins 收窄到前端实际域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # 用 Bearer 头认证 不依赖 cookie
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(preferences.router)
app.include_router(preferences.profile_router)


@app.get("/")
def read_root():
    return {"Hello": "World"}
