# backend/core/web/webAPI.py

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

import backend.core.web.routers.auth as auth
from backend.core.services.auth_service import AuthService
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore

DB_PATH = Path(__file__).resolve().parent.parent / "stores" / "data" / "user.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.user_store = UserStore(DB_PATH)
    app.state.session_store = SessionStore(DB_PATH)
    app.state.chat_store = ChatStore(DB_PATH)
    app.state.auth = AuthService(app.state.user_store, app.state.session_store)
    yield


app = FastAPI(lifespan=lifespan)


app.include_router(auth.router)


@app.get("/")
def read_root():
    return {"Hello": "World"}
