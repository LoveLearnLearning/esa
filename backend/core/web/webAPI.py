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
from backend.core.web.routers import auth, chat

DB_PATH = Path(__file__).resolve().parent.parent / "stores" / "data" / "user.db"

MODEL_PATH = "Qwen/Qwen3.5-9B"


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
        model_path=MODEL_PATH,
        dtype="bfloat16",
        kv_cache_dtype="fp8",
        gpu_memory_utilization=0.95,
        max_model_len=32768,
        max_num_seqs=1,
        quantization="bitsandbytes",
    )
    if not app.state.agent.start():
        raise RuntimeError("Agent load failed!")
    yield


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


@app.get("/")
def read_root():
    return {"Hello": "World"}
