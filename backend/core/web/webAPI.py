# backend/core/web/webAPI.py

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agent.agent import Agent
from backend.core.services.auth_service import AuthService
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
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
from backend.core.web.routers import (
    auth,
    chat,
    groups,
    learning,
    memories,
    preferences,
)

DB_PATH = Path(__file__).resolve().parent.parent / "stores" / "data" / "user.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.user_store = UserStore(DB_PATH)
    app.state.session_store = SessionStore(DB_PATH)

    # ChatStore 必须先执行：它负责为旧 conversations 表迁移 group_id 列。
    app.state.chat_store = ChatStore(DB_PATH)
    app.state.group_store = GroupStore(DB_PATH)

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(groups.router)
app.include_router(preferences.router)
app.include_router(preferences.profile_router)
app.include_router(learning.router)
app.include_router(memories.router)


@app.get("/")
def read_root():
    return {"Hello": "World"}
